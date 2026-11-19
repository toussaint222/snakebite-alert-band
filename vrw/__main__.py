"""Command line: python3 -m vrw <command>

Research demonstrator — not a medical device.

  run <scenario.json> [-v]   run one scenario, print timeline and checks
  run-all [-v]               run every scenario in scenarios/, print PASS/FAIL
  decode <hex>               decode a 50-byte uplink or 16-byte downlink
  example                    print an encoded example ALERT (used in the packet spec)
  demo <scenario.json>       play a scenario live into the dashboard (start it first:
                             python3 -m dashboard), at --speed times real time
  cassette <image.png>       read a cassette image: control line, family lines, bands
  vitals <file.csv>          check a vitals CSV: rows, gaps, dropped artifacts
  canopy                     M4: what happens to an ALERT under canopy of different lengths
  battery                    M4: radio/GPS energy and credits, fixed vs hardened retry
  make-data                  rebuild the synthetic files in scenarios/data/
  field <scenario.json>      M4 field run: print the timing table (bite -> responder on
                             scene). --url runs it through a running dashboard.
"""
import argparse
import os
import sys

from . import packet as P
from . import scenario as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISCLAIMER = "Research demonstrator - not a medical device."


def run_one(path, verbose):
    scn = S.load(path)
    res = S.run(scn)
    checks = S.check(res)
    ok = all(c[1] for c in checks)
    print("=" * 78)
    print("%s  [%s]" % (scn.get("name", os.path.basename(path)), "PASS" if ok else "FAIL"))
    print(scn.get("description", ""))
    print("-" * 78)
    for line in S.timeline_lines(res, verbose):
        print(line)
    print("-" * 78)
    for name, good, detail in checks:
        print("  [%s] %s%s" % ("ok" if good else "XX", name, ("  (%s)" % detail) if detail else ""))
    print("  link: %d uplink attempts, %d bytes delivered, %d duplicate(s) ignored at base" % (
        res.link.uplink_attempts, res.link.uplink_bytes_sent, res.base.duplicates))
    return ok


def example_alert():
    u = P.Uplink(msg_type=P.ALERT, device_id=1001, seq=3, event_time=1795075200,
                 send_time=1795075212, state=3,
                 flags=P.F_SIMULATED | P.F_TRAINER_HARDWARE | P.F_LOCAL_POSITIVE |
                 P.F_SYSTEMIC_POSITIVE | P.F_GPS_VALID,
                 family_mask=P.FM_3FTX | P.FM_PLA2, family_level=[3, 1, 0, 0],
                 local_source=P.SRC_LATERAL_FLOW, escalation_reason=P.R_ISF_RISE | P.R_SPO2_FALL,
                 lat=int(-3.4653 * 1e7), lon=int(-62.2159 * 1e7), fix_age=42, hdop=12,
                 heart_rate=112, spo2=90, resp_rate=26, spo2_slope=-4, rr_slope=5,
                 skin_temp=3412, isf_trend=1, battery=88, sensor_age=95, wear_site=0)
    return u


def demo(path, url, speed, scripted_base):
    import time
    from .remote import HttpBase
    scn = S.load(path)
    base = HttpBase(url)
    try:
        base.reset(scn.get("name"), scn.get("base_position"))
    except OSError as e:
        print("Can't reach the dashboard at %s (%s). Start it first: python3 -m dashboard" % (url, e))
        return 1
    sim = S.Simulation(scn, base=base, scripted_base=scripted_base)
    base.sim = sim
    print("Playing '%s' at %gx into %s  (Ctrl-C to stop)" % (scn.get("name"), speed, url))
    if not scripted_base:
        print("You are the base: close the alert from the dashboard when the responder is on scene.")
    shown = 0
    try:
        while not sim.done:
            t0 = time.monotonic()
            sim.step()
            for ev in sorted(sim.events[shown:], key=lambda e: e[0]):
                line = S.format_event(sim.start, ev)
                if line:
                    print(line, flush=True)
            shown = len(sim.events)
            time.sleep(max(0.0, sim.step_s / speed - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        print("stopped")
    print("Final band state: %s" % sim.dev.machine.state.name)
    return 0


def field(path, url=None):
    scn = S.load(path)
    base = None
    if url:
        from .remote import HttpBase
        base = HttpBase(url)
        try:
            base.reset(scn.get("name"), scn.get("base_position"))
        except OSError as e:
            print("Can't reach the dashboard at %s (%s). Start it first: python3 -m dashboard" % (url, e))
            return 1
    sim = S.Simulation(scn, base=base)
    if base:
        base.sim = sim
    while not sim.done:
        sim.step()
    res = sim.result()
    shown = dash = None
    if url:
        st = base._req("GET", "/api/state")
        dash = next((b for b in st["bands"] if b["device_id"] == sim.dev.device_id), None)
        shown = dash["dispatch"]["arrival"] if dash and dash.get("dispatch") else None
    rows = S.field_times(res, shown)
    bite = scn.get("bite_t") or 0
    print("%s%s" % (scn.get("name"), "  (through the dashboard at %s)" % url if url else ""))
    print("Simulated time. 'measured' = band, link and base software; 'assumed' = responder")
    print("model with PLACEHOLDER speeds and delays (R-28). No real-world claim.")
    print("-" * 78)
    print("  %-8s  %-40s %10s %12s" % ("", "milestone", "T+", "after bite"))
    for kind, name, t in rows:
        if t is None:
            print("  %-8s  %-40s %10s %12s" % (kind, name, "-", "-"))
        else:
            print("  %-8s  %-40s %10s %12s" % (kind, name, S.fmt_rel(0, t)[2:], S.fmt_rel(0, t - bite)[2:]))
    print("-" * 78)
    if url:
        bad = [] if (dash and dash["state"] == "RESOLVED" and dash.get("responder")) else ["dashboard"]
        print("dashboard shows: band %s, responder %s, alert reached it %ss after it was raised" % (
            dash and dash["state"], dash and dash.get("responder", {}) and dash["responder"]["status"],
            dash and dash.get("dispatch") and dash["dispatch"]["latency_s"]))
    else:
        checks = S.check(res)
        bad = [c for c in checks if not c[1]]
        print("checks: %d/%d ok%s" % (len(checks) - len(bad), len(checks),
                                      "" if not bad else "; FAILED: " + "; ".join(c[0] for c in bad)))
    print("band: %d send attempts, %d delivered, %d signal checks; responder search added: %s" % (
        res.device.outbox.attempts, res.device.outbox.successes, res.device.outbox.signal_checks,
        "%d min" % (res.responder.search_s // 60) if res.responder and res.responder.target else "-"))
    return 0 if not bad else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m vrw", description=DISCLAIMER)
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run"); r.add_argument("path"); r.add_argument("-v", action="store_true")
    ra = sub.add_parser("run-all"); ra.add_argument("-v", action="store_true")
    d = sub.add_parser("decode"); d.add_argument("hex")
    sub.add_parser("example")
    dm = sub.add_parser("demo"); dm.add_argument("path")
    dm.add_argument("--speed", type=float, default=120, help="times real time (default 120)")
    dm.add_argument("--url", default="http://127.0.0.1:8765")
    dm.add_argument("--scripted-base", action="store_true",
                    help="also play the scenario's scripted base actions (default: you click)")
    c = sub.add_parser("cassette"); c.add_argument("path")
    v = sub.add_parser("vitals"); v.add_argument("path")
    sub.add_parser("make-data")
    sub.add_parser("canopy")
    sub.add_parser("battery")
    fd = sub.add_parser("field"); fd.add_argument("path")
    fd.add_argument("--url", help="run through a running dashboard (python3 -m dashboard)")
    a = ap.parse_args(argv)
    print(DISCLAIMER)
    if a.cmd == "run":
        return 0 if run_one(a.path, a.v) else 1
    if a.cmd == "run-all":
        results = [(p, run_one(p, a.v)) for p in S.scenario_paths(ROOT)]
        print("=" * 78)
        for p, ok in results:
            print("  %s  %s" % ("PASS" if ok else "FAIL", os.path.basename(p)))
        print("%d/%d scenarios pass" % (sum(ok for _, ok in results), len(results)))
        return 0 if all(ok for _, ok in results) else 1
    if a.cmd == "demo":
        return demo(a.path, a.url, a.speed, a.scripted_base)
    if a.cmd == "cassette":
        from .sensors import lateral_flow
        from .trigger import load_thresholds
        r = lateral_flow.read_image(a.path, load_thresholds())
        if not r["control_ok"]:
            print("INVALID test: %s. It counts for nothing; retest." % r["error"])
        else:
            names = {1: "trace", 2: "low", 3: "moderate", 4: "high"}
            print("Valid test (control line found).")
            print("Family lines: " + (", ".join("%s band %d (%s)" % (f, b, names[b])
                                                for f, b in sorted(r["levels"].items())) or "none"))
        if r.get("detail"):
            print("Detail: %s" % r["detail"])
        return 0 if r["control_ok"] else 1
    if a.cmd == "vitals":
        from .sensors.vitals import VitalsCSV
        from .trigger import load_thresholds
        th = load_thresholds()
        f = VitalsCSV(a.path, th["vitals_plausible"])
        ts = [t for t, _ in f.rows]
        gaps = [(x, y) for x, y in zip(ts, ts[1:]) if y - x > th["vitals_max_gap_s"]]
        print("%d rows, t=%d..%d s" % (len(ts), ts[0], ts[-1]) if ts else "no rows")
        for x, y in gaps:
            print("  gap: no rows from %d to %d s (%d min)" % (x, y, (y - x) // 60))
        for t, k, raw in f.artifacts:
            print("  dropped as artifact: t=%d %s=%s" % (t, k, raw))
        return 0
    if a.cmd in ("canopy", "battery"):
        from . import fieldtools
        (fieldtools.print_canopy if a.cmd == "canopy" else fieldtools.print_battery)()
        return 0
    if a.cmd == "field":
        return field(a.path, a.url)
    if a.cmd == "make-data":
        from .sensors import synth
        d = os.path.join(ROOT, "scenarios", "data")
        for n in synth.make_all(d):
            print("  wrote scenarios/data/%s" % n)
        return 0
    if a.cmd == "decode":
        data = bytes.fromhex(a.hex.replace(" ", ""))
        obj = P.Uplink.from_bytes(data) if len(data) == P.UPLINK_SIZE else P.Downlink.from_bytes(data)
        for k, v in (obj.as_dict() if hasattr(obj, "as_dict") else vars(obj)).items():
            print("  %-18s %s" % (k, v))
        return 0
    if a.cmd == "example":
        b = example_alert().to_bytes()
        print("%d bytes:" % len(b))
        for i in range(0, len(b), 16):
            print("  %04x  %s" % (i, " ".join("%02x" % x for x in b[i:i + 16])))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
