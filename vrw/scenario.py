"""Scenario runner: plays a scripted timeline through band -> link -> base.

Research demonstrator — not a medical device.

All time is simulated (D-05): a 13-hour scenario runs in about a second.
Scenario file format is documented in scenarios/README.md.
"""
import json
import os
import tempfile
from datetime import datetime, timezone

from . import packet as P
from .base import Base
from .device import Device
from .link.sim_sbd import SimLink
from .responder import Responder
from .sensors import lateral_flow
from .sensors.vitals import VitalsCSV
from .trigger import State, load_thresholds, DEFAULT_THRESHOLDS


def load(path):
    with open(path) as f:
        s = json.load(f)
    s.setdefault("_path", path)
    return s


def _epoch(s):
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def _interp(keyframes, t):
    """Linear interpolation of vitals keyframes [(t, {..})]; None before the first."""
    if not keyframes or t < keyframes[0][0]:
        return None
    for (t0, a), (t1, b) in zip(keyframes, keyframes[1:]):
        if t0 <= t <= t1:
            f = (t - t0) / float(t1 - t0) if t1 > t0 else 1.0
            return {k: a[k] + (b.get(k, a[k]) - a[k]) * f for k in a}
    return dict(keyframes[-1][1])


class Result:
    def __init__(self, scn, start, device, base, link, events):
        self.scn, self.start = scn, start
        self.device, self.base, self.link, self.events = device, base, link, events
        self.machine = device.machine
        self.lfa_reads = []
        self.responder = None

    @property
    def final_state(self):
        return self.machine.state

    def states_visited(self):
        return {State.IDLE} | {to for _, _, to, _ in self.machine.log}

    def escalated_at(self):
        return next((t for t, frm, to, _ in self.machine.log if to == State.ESCALATED and frm != to), None)

    def first_dispatch(self):
        return self.base.dispatches[0] if self.base.dispatches else None

    def received_types(self):
        return {u.type_name for _, u in self.base.received}

    def all_packets(self):
        return [u for _, u in self.device.enqueued]


class Simulation:
    """Steps a scenario one tick at a time.

    `base` is anything with receive(arrival, data), resolve(now, device_id) and
    take_downlinks() -> [(time, bytes)]: the in-process Base, or the dashboard
    over HTTP (vrw/remote.py). `scripted_base=False` ignores the scenario's
    "base" actions so a person at the dashboard plays the base instead.
    """

    def __init__(self, scn, thresholds_path=DEFAULT_THRESHOLDS, base=None, scripted_base=True):
        self.scn = scn
        th = load_thresholds(thresholds_path, scn.get("threshold_overrides"))
        self.start = _epoch(scn.get("start_utc", "2026-11-18T08:00:00Z"))
        self.step_s = int(scn.get("step_s", 10))
        self.duration = int(scn["duration_s"])
        start = self.start
        lk = scn.get("link", {})
        self.link = SimLink(latency_s=lk.get("latency_s", (10, 60)), drop_prob=lk.get("drop_prob", 0.0),
                            blackouts=[(start + a, start + b) for a, b in lk.get("blackouts", [])],
                            seed=lk.get("seed", 1),
                            profile=[(start + z["from"], start + z["to"],
                                      None if z.get("blackout") else z.get("drop_prob", 0.0),
                                      z.get("label", "")) for z in lk.get("profile", [])])
        self.base = base if base is not None else Base()
        self.scripted_base = scripted_base
        # power_cycle: [{"at": s, "off_s": s}] - the band loses power and restarts
        # from what it saved to "flash" (the outbox file). R-25.
        self.power_cycles = [(int(p["at"]), int(p["at"]) + int(p["off_s"])) for p in scn.get("power_cycle", [])]
        self.flash_dir = tempfile.TemporaryDirectory(prefix="vrw-flash-") if self.power_cycles else None
        self.outbox_path = os.path.join(self.flash_dir.name, "outbox.json") if self.flash_dir else None
        self.off = False
        self.th_all = th
        self.dev = dev = Device(scn.get("device_id", 1001), th, wear_site=scn.get("wear_site", 0),
                                outbox_path=self.outbox_path)
        self.pos = scn.get("position")
        self.gps_every = int(scn.get("gps_fix_s", 60))
        if self.pos:
            dev.set_fix(start, self.pos["lat"], self.pos["lon"], self.pos.get("hdop", 1.0))
        self.bat = scn.get("battery", {"start": 95, "drain_per_hour": 1.0})
        sensor = scn.get("sensor", {"applied_t": 0, "life_s": 43200})
        dev.sensor_applied = start + sensor["applied_t"]
        self.sensor_life = sensor.get("life_s")
        self.events = []
        self.timeline = sorted(scn.get("timeline", []), key=lambda e: e["t"])
        self.vit_kf = [(e["t"], e["vitals"]) for e in self.timeline if "vitals" in e]
        self.vit_every = int(scn.get("vitals_sample_s", 60))
        self.th = th
        # M3 stand-ins: file paths are relative to the scenario file
        here = os.path.dirname(os.path.abspath(scn.get("_path", ".")))
        self.resolve_path = lambda p: p if os.path.isabs(p) else os.path.join(here, p)
        self.vit_csv = None
        if scn.get("vitals_csv"):
            if self.vit_kf:
                raise ValueError("scenario has both vitals keyframes and vitals_csv; use one")
            self.vit_csv = VitalsCSV(self.resolve_path(scn["vitals_csv"]), th["vitals_plausible"])
            for t, field, raw in self.vit_csv.artifacts:
                if t <= self.duration:
                    self.events.append((self.start + t, "vitals_artifact", field, raw))
        self.lfa_reads = []   # (t, image path, read result) for reporting
        self.isf_reads = {}
        for blk in scn.get("isf_reads", []):
            for t in range(blk["from"], blk["to"] + 1, blk["every_s"]):
                self.isf_reads[t] = blk["levels"]
        self.arrivals = []   # (arrival_time, bytes) in flight to the base
        self.gps_tries = 0   # GPS fix attempts (for the battery report)
        rc = scn.get("responder")
        self.responder = Responder(rc, scn["base_position"], start) if rc else None
        self.k = 0
        self.ti = 0

    @property
    def now(self):
        return self.start + self.k

    @property
    def done(self):
        return self.k > self.duration

    def _reboot(self, now):
        """Power back on: a new band object built only from what was saved to flash."""
        old = self.dev
        new = Device(old.device_id, self.th_all, wear_site=old.wear_site, outbox_path=self.outbox_path)
        new.sensor_applied = old.sensor_applied      # patch time is stored config
        new.battery = old.battery
        # simulation bookkeeping only (not band memory): keep the history for the report
        new.enqueued, new.superseded = old.enqueued, old.superseded
        new.machine.log = list(old.machine.log)
        new.resume(now)
        if not new.restored:
            new.machine.log.append((now, old.machine.state, State.IDLE, "power cycle: restarted in IDLE (R-25)"))
        self.dev = new
        self.events.append((now, "state", new.machine.log[-1]))
        self.events.append((now, "reboot", len(new.outbox), new.outbox.next_seq))

    def step(self):
        k, now = self.k, self.start + self.k
        off_now = any(a <= k < b for a, b in self.power_cycles)
        if off_now and not self.off:
            self.events.append((now, "power_off", len(self.dev.outbox)))
        if self.off and not off_now:
            self._reboot(now)
        self.off = off_now
        dev, events = self.dev, self.events
        # 1. things arriving at the base and at the band
        for a in sorted(x for x in self.arrivals if x[0] <= now):
            self.arrivals.remove(a)
            u = self.base.receive(a[0], a[1])
            if u:
                events.append((a[0], "base_received", u))
                if self.responder:
                    self.responder.observe(a[0], u)
        if self.responder:
            for status, eta in self.responder.step(now):
                r = self.responder
                where = {"dispatched": r.base_pos, "en_route": r.trailhead, "on_scene": r.target}[status]
                self.base.responder_update(now, dev.device_id, status, eta, where[0], where[1])
                events.append((now, "responder", status, eta))
                if status == "on_scene" and self.scripted_base:
                    self.base.resolve(now, dev.device_id)
                    events.append((now, "base_resolve", None))
        for t, data in self.base.take_downlinks():
            self.link.send_downlink(int(max(t, now)), data)
        # a switched-off band hears nothing; the gateway holds downlinks until it is back
        for at, data in ([] if self.off else self.link.due_downlinks(now)):
            dl = dev.on_downlink(now, data)
            events.append((now, "band_received", dl))
        # 2. scripted inputs for this step
        lfa = isf = action = None
        base_actions = []
        while self.ti < len(self.timeline) and self.timeline[self.ti]["t"] <= k:
            e = self.timeline[self.ti]
            lfa = e.get("lfa", lfa)
            if "lfa_image" in e:
                img = self.resolve_path(e["lfa_image"])
                lfa = lateral_flow.read_image(img, self.th)
                self.lfa_reads.append((now, e["lfa_image"], lfa))
                events.append((now, "cassette_read", e["lfa_image"], lfa))
            action = e.get("action", action)
            if "base" in e and self.scripted_base:
                base_actions.append(e["base"])
            if e.get("gps"):
                self.pos = e["gps"]
            self.ti += 1
        if self.off:                     # readings while switched off are lost
            for b in base_actions:
                if b == "resolve":
                    self.base.resolve(now, dev.device_id)
                    events.append((now, "base_resolve", None))
            self.k += self.step_s
            return
        # GPS refreshes every gps_fix_s, except under canopy (same blackout as the link)
        if self.pos and k % self.gps_every == 0:
            self.gps_tries += 1
            if not self.link.in_blackout(now):
                dev.set_fix(now, self.pos["lat"], self.pos["lon"], self.pos.get("hdop", 1.0))
        for t in [t for t in self.isf_reads if k - self.step_s < t <= k]:
            isf = self.isf_reads[t]
        if self.vit_csv is not None:
            vit = self.vit_csv.between(k - self.step_s, k)
        else:
            vit = _interp(self.vit_kf, k) if k % self.vit_every == 0 else None
        dev.battery = self.bat["start"] - self.bat["drain_per_hour"] * k / 3600.0
        # 3. band logic, then base actions, then one modem session
        n_log, n_enq, n_al = len(dev.machine.log), len(dev.enqueued), len(dev.alarms)
        dev.step(now, lfa=lfa, isf=isf, vitals=vit, action=action, sensor_life_s=self.sensor_life)
        for entry in dev.machine.log[n_log:]:
            events.append((entry[0], "state", entry))
        for t, u in dev.enqueued[n_enq:]:
            events.append((t, "enqueued", u))
        for t, what in dev.alarms[n_al:]:
            events.append((t, "alarm", what))
        for b in base_actions:
            if b == "resolve":
                self.base.resolve(now, dev.device_id)
                events.append((now, "base_resolve", None))
        sent = dev.outbox.process(now, self.link, events)
        if sent:
            u, arrival = sent
            self.arrivals.append((arrival, u.to_bytes()))
        self.k += self.step_s

    def result(self):
        r = Result(self.scn, self.start, self.dev, self.base, self.link, self.events)
        r.lfa_reads = self.lfa_reads
        r.responder = self.responder
        r.gps_tries = self.gps_tries
        if self.flash_dir is not None:
            self.flash_dir.cleanup()
        return r


def run(scn, thresholds_path=DEFAULT_THRESHOLDS):
    sim = Simulation(scn, thresholds_path)
    while not sim.done:
        sim.step()
    return sim.result()


# ---------------------------------------------------------------- expectations
def check(res):
    """Compare a Result with the scenario's "expect" block. Returns [(name, ok, detail)]."""
    exp = res.scn.get("expect", {})
    out = []

    pk = res.all_packets()
    sizes = {len(u.to_bytes()) for u in pk}
    round_trip = all(P.Uplink.from_bytes(u.to_bytes()) == u for u in pk)
    out.append(("every packet is 50 bytes and round-trips", sizes <= {P.UPLINK_SIZE} and round_trip,
                "%d packets, sizes %s" % (len(pk), sorted(sizes))))

    seqs = [u.seq for u in pk]
    out.append(("every message number used once (survives power cycles)",
                len(seqs) == len(set(seqs)), "%d messages" % len(seqs)))

    esc_from = [frm for _, frm, to, _ in res.machine.log if to == State.ESCALATED and frm != to]
    out.append(("ESCALATED only ever entered from SYSTEMIC_WATCH (local confirmed)",
                all(f == State.SYSTEMIC_WATCH for f in esc_from), str([f.name for f in esc_from])))

    if "final_state" in exp:
        out.append(("final state is %s" % exp["final_state"],
                    res.final_state.name == exp["final_state"], res.final_state.name))
    for s in exp.get("visits", []):
        out.append(("visits %s" % s, State[s] in res.states_visited(), ""))
    for s in exp.get("never", []):
        out.append(("never enters %s" % s, State[s] not in res.states_visited(), ""))
    if "dispatched" in exp:
        d = res.first_dispatch()
        out.append(("responder dispatched = %s" % exp["dispatched"], bool(d) == exp["dispatched"],
                    "" if not d else "payload class %s" % d[2]))
    if "payload_class" in exp:
        d = res.first_dispatch()
        out.append(("payload class is %s" % exp["payload_class"],
                    bool(d) and d[2] == exp["payload_class"], d[2] if d else "no dispatch"))
    if "families_include" in exp:
        d = res.first_dispatch()
        fams = d[1].families if d else []
        out.append(("alert names families %s" % exp["families_include"],
                    all(f in fams for f in exp["families_include"]), str(fams)))
    if "reasons_include" in exp or "reasons_exact" in exp:
        d = res.first_dispatch()
        rs = d[1].reasons if d else []
        if "reasons_include" in exp:
            out.append(("first alert reasons include %s" % exp["reasons_include"],
                        all(r in rs for r in exp["reasons_include"]), str(rs)))
        if "reasons_exact" in exp:
            out.append(("first alert reasons are exactly %s" % exp["reasons_exact"],
                        sorted(rs) == sorted(exp["reasons_exact"]), str(rs)))
    if "responder_on_scene" in exp:
        rt = res.responder.times if res.responder else {}
        out.append(("responder reaches the wearer = %s" % exp["responder_on_scene"],
                    ("on_scene" in rt) == exp["responder_on_scene"],
                    fmt_rel(res.start, rt["on_scene"]) if "on_scene" in rt else "not on scene"))
    if "local_levels" in exp:
        got = {f: l for f, l in zip(P.FAMILIES, res.machine.local_levels()) if l}
        out.append(("band's local reading is %s" % exp["local_levels"], got == exp["local_levels"], str(got)))
    if "cassette_reads" in exp:
        got = [("INVALID" if not r["control_ok"] else r["levels"]) for _, _, r in res.lfa_reads]
        out.append(("cassette images read as %s" % exp["cassette_reads"], got == exp["cassette_reads"], str(got)))
    if "reasons_exclude" in exp:
        d = res.first_dispatch()
        rs = d[1].reasons if d else []
        out.append(("first alert reasons exclude %s" % exp["reasons_exclude"],
                    bool(d) and not any(r in rs for r in exp["reasons_exclude"]), str(rs)))
    if "first_state_change_after_s" in exp:
        first = res.machine.log[0][0] - res.start if res.machine.log else None
        out.append(("band stays idle until T+%ss" % exp["first_state_change_after_s"],
                    first is not None and first >= exp["first_state_change_after_s"],
                    "first change at %ss" % first))
    for t in exp.get("base_receives", []):
        out.append(("base receives %s" % t, t in res.received_types(), ""))
    for t in exp.get("base_never_receives", []):
        out.append(("base never receives %s" % t, t not in res.received_types(), ""))
    if "alert_latency_max_s" in exp or "alert_delay_min_s" in exp:
        d, e = res.first_dispatch(), res.escalated_at()
        lat = (d[0] - e) if (d and e) else None
        if "alert_latency_max_s" in exp:
            out.append(("escalation -> base in <= %ss" % exp["alert_latency_max_s"],
                        lat is not None and lat <= exp["alert_latency_max_s"],
                        "%.0fs" % lat if lat is not None else "n/a"))
        if "alert_delay_min_s" in exp:
            out.append(("alert held >= %ss by link loss, then delivered" % exp["alert_delay_min_s"],
                        lat is not None and lat >= exp["alert_delay_min_s"],
                        "%.0fs" % lat if lat is not None else "n/a"))
        if d and e:
            out.append(("alert keeps its original event_time", d[1].event_time == e,
                        "event %d vs escalation %d" % (d[1].event_time, e)))
    if exp.get("alert_retransmitted"):
        d = res.first_dispatch()
        out.append(("delivered alert carries retransmission flag",
                    bool(d) and bool(d[1].flags & P.F_RETRANSMISSION), ""))
    return out


def fmt_t(res, t):
    return fmt_rel(res.start, t)


def fmt_rel(start, t):
    s = int(round(t - start))
    return "T+%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)


def format_event(start, ev, verbose=False):
    """One readable line for one simulation event, or None to skip it."""
    t, kind = ev[0], ev[1]
    T = fmt_rel(start, t)
    if kind == "state":
        _, frm, to, why = ev[2]
        return "%s  band  %-14s -> %-14s %s" % (T, frm.name, to.name, why)
    if kind == "enqueued":
        u = ev[2]
        extra = (" families=%s reasons=%s" % (u.families, u.reasons)) if u.msg_type == P.ALERT else ""
        return "%s  band  queued %s seq=%d%s" % (T, u.type_name, u.seq, extra)
    if kind == "uplink_attempt":
        u, ok, n = ev[2], ev[3], ev[4]
        if verbose or (not ok and n == 1):
            return "%s  link  %s seq=%d attempt %d %s" % (
                T, u.type_name, u.seq, n, "sent" if ok else "FAILED - kept in queue, will retry")
        if ok and n > 1:
            return "%s  link  %s seq=%d sent on attempt %d" % (T, u.type_name, u.seq, n)
        return None
    if kind == "base_received":
        u = ev[2]
        return "%s  BASE  received %s seq=%d (event %s, delay %.0fs)" % (
            T, u.type_name, u.seq, fmt_rel(start, u.event_time), t - u.event_time)
    if kind == "band_received":
        return "%s  band  received downlink %s" % (T, ev[2].type_name)
    if kind == "cassette_read":
        name, r = ev[2], ev[3]
        if not r["control_ok"]:
            return "%s  band  cassette %s: INVALID (%s) - counts for nothing" % (T, os.path.basename(name), r.get("error"))
        lv = ", ".join("%s %d" % kv for kv in sorted(r["levels"].items())) or "no family lines"
        return "%s  band  cassette %s read: %s" % (T, os.path.basename(name), lv)
    if kind == "vitals_artifact":
        return "%s  band  vitals: %s=%s dropped as sensor artifact" % (T, ev[2], ev[3])
    if kind == "responder":
        words = {"dispatched": "responder leaves base", "en_route": "responder at trailhead, walking in",
                 "on_scene": "RESPONDER ON SCENE"}[ev[2]]
        eta = "" if ev[3] in (None, 0) else " (about %d min to the wearer)" % ev[3]
        return "%s  RESP  %s%s" % (T, words, eta)
    if kind == "alarm":
        return "%s  band  LOCAL ALARM %s%s" % (T, ev[2].upper(), " - alert not sent yet: move to open sky (R-27)"
                                               if ev[2] == "on" else " - alert sent")
    if kind == "power_off":
        return "%s  band  POWER OFF (%d message(s) in the saved queue)" % (T, ev[2])
    if kind == "reboot":
        return "%s  band  POWER ON: restored %d queued message(s) from flash, next seq %d" % (T, ev[2], ev[3])
    if kind == "signal_low":
        return None
    if kind == "base_resolve":
        return "%s  BASE  sends RESOLVE" % T
    return None


def timeline_lines(res, verbose=False):
    lines = [l for l in (format_event(res.start, ev, verbose)
                         for ev in sorted(res.events, key=lambda e: e[0])) if l]
    for t, u, cls in res.base.dispatches:
        lines.append("%s  BASE  DISPATCH responder - payload class %s, families %s" % (
            fmt_t(res, t), cls, u.families or "none named"))
    return lines


def scenario_paths(root):
    d = os.path.join(root, "scenarios")
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json"))


# ---------------------------------------------------------------- field timing (M4 gate)
def field_times(res, shown_at=None):
    """Milestones of one run, in seconds from the scenario start (None = didn't happen).

    "measured" = produced by the simulated band, link and base/dashboard.
    "assumed"  = depends on the responder model's PLACEHOLDER numbers (R-28).
    """
    m, rel = res.machine, (lambda t: None if t is None else t - res.start)
    first = lambda st: next((t for t, _, to, _ in m.log if to == st), None)
    alert = next((u for u in res.all_packets() if u.msg_type == P.ALERT), None)
    tries = [ev for ev in res.events if ev[1] == "uplink_attempt" and alert and ev[2].seq == alert.seq]
    if shown_at is None:
        d = res.first_dispatch()
        shown_at = d[0] if d else None
    rt = res.responder.times if res.responder else {}
    band_resolved = next((t for t, _, to, why in m.log if to == State.RESOLVED and "base" in why), None)
    rows = [
        ("scripted", "bite", res.scn.get("bite_t")),
        ("measured", "local signal confirmed", rel(first(State.SYSTEMIC_WATCH))),
        ("measured", "band escalates, ALERT queued", rel(first(State.ESCALATED))),
        ("measured", "ALERT first send attempt", rel(tries[0][0]) if tries else None),
        ("measured", "ALERT leaves the band (attempt %d)" % len(tries) if tries else "ALERT leaves the band",
         rel(next((ev[0] for ev in tries if ev[3]), None))),
        ("measured", "ALERT shown at base / dashboard", rel(shown_at)),
        ("assumed", "responder leaves base", rel(rt.get("departed"))),
        ("assumed", "responder at trailhead", rel(rt.get("at_trailhead"))),
        ("assumed", "responder on scene", rel(rt.get("on_scene"))),
        ("measured", "band confirms the close (RESOLVED)", rel(band_resolved)),
    ]
    return rows
