"""Talk to the dashboard over HTTP as if it were the base station's radio side.

Research demonstrator — not a medical device.
Same interface as vrw.base.Base, so vrw.scenario.Simulation can use either.
"""
import json
import urllib.request

from . import packet as P


class HttpBase:
    def __init__(self, url, sim=None):
        self.url = url.rstrip("/")
        self.sim = sim            # set by caller so downlink polls carry the sim clock

    def _req(self, method, path, data=None, headers=None):
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers or {})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read() or b"null")

    def reset(self, scenario, base_pos=None):
        return self._req("POST", "/api/reset", json.dumps({"scenario": scenario, "base": base_pos}).encode(),
                         {"Content-Type": "application/json"})

    def receive(self, arrival, data):
        r = self._req("POST", "/api/uplink", data, {"Content-Type": "application/octet-stream",
                                                      "X-Arrival-Time": repr(float(arrival))})
        return P.Uplink.from_bytes(data) if r.get("accepted") else None   # None = duplicate/rejected

    def resolve(self, now, device_id):
        self._req("POST", "/api/resolve", json.dumps({"device_id": device_id}).encode(),
                  {"Content-Type": "application/json"})

    def responder_update(self, now, device_id, status, eta_min=None, lat=None, lon=None):
        self._req("POST", "/api/responder", json.dumps(
            {"device_id": device_id, "status": status, "eta_min": eta_min, "lat": lat, "lon": lon,
             "time": float(now)}).encode(), {"Content-Type": "application/json"})

    def take_downlinks(self):
        q = "" if self.sim is None else "?now=%r" % float(self.sim.now)
        return [(d["t"], bytes.fromhex(d["hex"])) for d in self._req("GET", "/api/downlinks" + q)]
