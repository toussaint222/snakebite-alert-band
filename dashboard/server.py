"""Local dashboard server — the base station.

Research demonstrator — not a medical device.

Standard library only. Binds to 127.0.0.1 (this Mac only). Endpoints:

  GET  /                     dashboard page
  GET  /static/<file>        page assets
  GET  /api/state            everything the page shows (JSON)
  POST /api/uplink           body = one 50-byte uplink; header X-Arrival-Time (UTC s)
  GET  /api/downlinks?now=T  downlinks waiting for the radio (hex); also sets the sim clock
  POST /api/resolve          {"device_id": N} — a person closes an alert (RESOLVE downlink)
  POST /api/responder        {"device_id", "status", "eta_min", "lat", "lon"} — responder progress
                             (field simulation); sent to the band as RESPONDER_STATUS
  POST /api/reset            {"scenario": "...", "base": {"lat":..,"lon":..}} — clear for a new run

Run:  python3 -m dashboard            (then open http://127.0.0.1:8765)
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from vrw import packet as P
from vrw.base import Base, payload_class
from vrw.trigger import State

from . import checklist as CL

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DISCLAIMER = "Research demonstrator — not a medical device."
MAX_BODY = 4096

STATE_WORDS = {
    State.IDLE: ("Normal wear", "Nothing detected."),
    State.CONTACT: ("Contact", "A local toxin signal was seen once; confirming."),
    State.SYSTEMIC_WATCH: ("Watching", "Local signal confirmed. Watching for body-wide signs. No dispatch."),
    State.ESCALATED: ("ESCALATED", "Dispatch a responder."),
    State.RESOLVED: ("Closed", "Alert closed."),
    State.STOOD_DOWN: ("Stood down", "Watch ended with no body-wide signs."),
    State.SYSTEMIC_ONLY: ("Body-wide signs only", "Vitals concerning but no toxin signal at the band. Not a dispatch."),
}
REASON_WORDS = {
    "isf_rise": "Toxin level in skin fluid rising",
    "spo2_fall": "Blood oxygen (SpO2) falling",
    "rr_rise": "Breathing rate rising",
    "hr_trend": "Heart-rate trend",
    "local_danger": "Strong local signal held past the danger timer (no body-wide sign)",
}
FAMILY_WORDS = {"3FTx": "3FTx (three-finger toxins)", "PLA2": "PLA2 (phospholipase A2)",
                "SVMP": "SVMP (metalloproteinases)", "SVSP": "SVSP (serine proteases)"}
SOURCE_WORDS = {P.SRC_NONE: "none", P.SRC_LATERAL_FLOW: "lateral-flow test",
                P.SRC_ISF: "skin-fluid (ISF) sensor", P.SRC_MANUAL: "manual entry"}
SITE_WORDS = {0: "left ankle", 1: "right ankle", 2: "left wrist", 3: "right wrist"}
WHY_NOT_DISPATCH = {
    P.CONTACT_INFO: "Information only — contact confirmed, watching. Not a dispatch.",
    P.SYSTEMIC_ONLY_INFO: "Information only — body-wide signs without a toxin signal. Not a dispatch.",
    P.STAND_DOWN: "Dry-bite stand-down. Not a dispatch.",
    P.SENSOR_EXPIRED: "Sensor patch expired during the watch; band keeps watching on vitals.",
    P.HEARTBEAT: "Band alive.",
}


class Dashboard:
    """Holds the Base and turns it into page state. Thread-safe via one lock."""

    def __init__(self, checklist_path=CL.DEFAULT):
        self.lock = threading.Lock()
        self.checklist_cfg = CL.load(checklist_path)
        self.reset()

    def reset(self, scenario=None, base_pos=None):
        self.base = Base()
        self.scenario = scenario
        self.base_pos = base_pos
        self.clock = None
        self.tracks = {}

    def now(self):
        return self.clock if self.clock is not None else time.time()

    def set_clock(self, t):
        if t is not None and (self.clock is None or t > self.clock):
            self.clock = t

    def uplink(self, data, arrival=None):
        arrival = self.now() if arrival is None else arrival
        self.set_clock(arrival)
        u = self.base.receive(arrival, data)
        if u and u.lat_deg is not None:
            self.tracks.setdefault(u.device_id, []).append(
                {"lat": u.lat_deg, "lon": u.lon_deg, "t": u.event_time})
        return u

    def resolve(self, device_id):
        self.base.resolve(self.now(), device_id)

    def responder(self, j):
        t = j.get("time")
        if t is not None:
            self.set_clock(float(t))
        self.base.responder_update(self.now(), int(j["device_id"]), j["status"], j.get("eta_min"),
                                   j.get("lat"), j.get("lon"))

    def downlinks(self):
        return [{"t": t, "hex": b.hex()} for t, b in self.base.take_downlinks()]

    # ---------------------------------------------------------------- page state
    def state(self):
        b = self.base
        bands = []
        for dev_id, u in sorted(b.bands.items()):
            arrival = max(a for a, x in b.received if x.device_id == dev_id and x.seq == u.seq
                          and x.event_time == u.event_time)
            st = State(u.state)
            d = b.dispatch_for(dev_id)
            dispatch = None
            if d:
                arr, al, cls = d
                dispatch = {
                    "arrival": arr, "alert_event_time": al.event_time,
                    "latency_s": round(arr - al.event_time, 1),
                    "payload_class": cls,
                    "families": [FAMILY_WORDS.get(f, f) for f in al.families],
                    "reasons": [REASON_WORDS.get(r, r) for r in al.reasons],
                    "checklist": CL.build(self.checklist_cfg, cls, al.families),
                }
            cad = [x for x in b.cancelled_after_dispatch if x[1].device_id == dev_id]
            bands.append({
                "device_id": dev_id,
                "state": st.name,
                "state_title": STATE_WORDS[st][0],
                "state_text": STATE_WORDS[st][1],
                "last_type": u.type_name,
                "last_note": WHY_NOT_DISPATCH.get(u.msg_type, ""),
                "event_time": u.event_time, "arrival": arrival,
                "age_s": round(self.now() - u.event_time, 1),
                "delay_s": round(arrival - u.event_time, 1),
                "families": [{"name": FAMILY_WORDS.get(f, f),
                              "level": P.LEVEL_NAMES.get(u.family_level[i], str(u.family_level[i]))}
                             for i, f in enumerate(P.FAMILIES) if u.family_mask & (1 << i)],
                "test_invalid": bool(u.family_mask & P.FM_TEST_INVALID),
                "unclassified": bool(u.family_mask & P.FM_UNCLASSIFIED),
                "reasons": [REASON_WORDS.get(r, r) for r in u.reasons],
                "local_source": SOURCE_WORDS.get(u.local_source, "?"),
                "wear_site": SITE_WORDS.get(u.wear_site, "unknown"),
                "vitals": {
                    "spo2": u.spo2 or None, "rr": u.resp_rate or None, "hr": u.heart_rate or None,
                    "spo2_slope": None if u.spo2_slope == P.NA_I8 else u.spo2_slope,
                    "rr_slope": None if u.rr_slope == P.NA_I8 else u.rr_slope,
                    "skin_temp": None if u.skin_temp == P.NA_I16 else u.skin_temp / 100.0,
                },
                "battery": None if u.battery == P.NA_U8 else u.battery,
                "sensor_age_min": None if u.sensor_age == P.NA_U16 else u.sensor_age,
                "flags": {
                    "sensor_expired": bool(u.flags & P.F_SENSOR_EXPIRED),
                    "battery_low": bool(u.flags & P.F_BATTERY_LOW),
                    "retransmission": bool(u.flags & P.F_RETRANSMISSION),
                    "gps_valid": bool(u.flags & P.F_GPS_VALID),
                },
                "position": None if u.lat_deg is None else {
                    "lat": u.lat_deg, "lon": u.lon_deg,
                    "fix_age_s": None if u.fix_age == P.NA_U16 else u.fix_age,
                    "hdop": None if u.hdop == P.NA_U8 else u.hdop / 10.0},
                "track": self.tracks.get(dev_id, []),
                "dispatch": dispatch,
                "cancelled_after_dispatch": [{"arrival": a, "type": x.type_name, "event_time": x.event_time}
                                             for a, x in cad],
                "stale_alerts": len([1 for _, x in b.stale_alerts if x.device_id == dev_id]),
                "resolved_by_base": b.resolved_by_base.get(dev_id),
                "can_resolve": st == State.ESCALATED and dev_id not in b.resolved_by_base,
                "responder": b.responders.get(dev_id),
            })
        log = [{"arrival": a, "event_time": u.event_time, "device_id": u.device_id, "seq": u.seq,
                "type": u.type_name, "state": State(u.state).name, "delay_s": round(a - u.event_time, 1),
                "retransmission": bool(u.flags & P.F_RETRANSMISSION)}
               for a, u in reversed(b.received)]
        return {"disclaimer": DISCLAIMER, "scenario": self.scenario, "now": self.now(),
                "sim_clock": self.clock is not None, "base_position": self.base_pos,
                "checklist_status": self.checklist_cfg.get("status"),
                "bands": bands, "log": log[:200], "duplicates": b.duplicates,
                "rejected": [{"arrival": a, "reason": r} for a, r in b.rejected][-20:]}


def make_handler(dash):
    class Handler(BaseHTTPRequestHandler):
        server_version = "VRWDashboard/1"

        def log_message(self, fmt, *args):   # quiet
            pass

        def _send(self, code, body, ctype="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("body too large")
            return self.rfile.read(n)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                return self._static("index.html")
            if url.path.startswith("/static/"):
                return self._static(url.path[len("/static/"):])
            if url.path == "/api/state":
                with dash.lock:
                    return self._send(200, dash.state())
            if url.path == "/api/downlinks":
                q = parse_qs(url.query)
                with dash.lock:
                    if "now" in q:
                        dash.set_clock(float(q["now"][0]))
                    return self._send(200, dash.downlinks())
            self._send(404, {"error": "not found"})

        def do_POST(self):
            url = urlparse(self.path)
            try:
                body = self._body()
                with dash.lock:
                    if url.path == "/api/uplink":
                        t = self.headers.get("X-Arrival-Time")
                        u = dash.uplink(body, float(t) if t else None)
                        return self._send(200, {"accepted": u is not None})
                    if url.path == "/api/resolve":
                        dash.resolve(int(json.loads(body or b"{}")["device_id"]))
                        return self._send(200, {"ok": True})
                    if url.path == "/api/responder":
                        dash.responder(json.loads(body or b"{}"))
                        return self._send(200, {"ok": True})
                    if url.path == "/api/reset":
                        j = json.loads(body or b"{}")
                        dash.reset(j.get("scenario"), j.get("base"))
                        return self._send(200, {"ok": True})
            except (ValueError, KeyError) as e:
                return self._send(400, {"error": str(e)})
            self._send(404, {"error": "not found"})

        def _static(self, name):
            path = os.path.normpath(os.path.join(STATIC, name))
            if not path.startswith(STATIC + os.sep) or not os.path.isfile(path):
                return self._send(404, {"error": "not found"})
            ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                     ".css": "text/css; charset=utf-8"}.get(os.path.splitext(path)[1], "application/octet-stream")
            with open(path, "rb") as f:
                self._send(200, f.read(), ctype)

    return Handler


def make_server(port=8765, host="127.0.0.1", dash=None):
    dash = dash or Dashboard()
    srv = ThreadingHTTPServer((host, port), make_handler(dash))
    srv.dash = dash
    return srv


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m dashboard", description=DISCLAIMER)
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    srv = make_server(a.port)
    print(DISCLAIMER)
    print("Dashboard on http://127.0.0.1:%d  (Ctrl-C to stop)" % a.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
