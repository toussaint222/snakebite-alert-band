"""M4 field tools: canopy failure modes and the battery budget.

Research demonstrator — not a medical device.

    python3 -m vrw canopy     what happens to an ALERT under canopy of different lengths
    python3 -m vrw battery    radio/GPS energy and message credits, fixed vs hardened retry

Both run scenarios in simulated time. Energy figures come from vrw/power.json,
every value a PLACEHOLDER assumption: read the results as a comparison between
policies, never as a battery-life figure.
"""
import copy
import json
import os

from . import scenario as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POWER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "power.json")

# The M1-M3 behaviour: retry every 60 s whatever the message, never look at the signal.
FIXED_POLICY = {"retry_backoff_max_s": 60, "link_min_signal": 0, "urgent_blind_attempt_s": 0}


def load_power(path=POWER):
    with open(path) as f:
        return {k: v["value"] for k, v in json.load(f).items() if not k.startswith("_")}


def energy(res, power, hours):
    ob = res.device.outbox
    radio = ob.attempts * power["send_attempt_mas"] + ob.signal_checks * power["signal_check_mas"]
    gps = res.gps_tries * power["gps_fix_mas"]
    base = power["baseline_ma"] * hours * 3600
    mah = lambda mas: mas / 3600.0
    return {"radio_mah": mah(radio), "gps_mah": mah(gps), "base_mah": mah(base),
            "total_mah": mah(radio + gps + base),
            "pct": 100.0 * mah(radio + gps + base) / power["battery_mah"],
            "credits": ob.successes}


def scenario(name):
    return S.load(os.path.join(ROOT, "scenarios", name))


def run(scn, policy=None):
    scn = copy.deepcopy(scn)
    if policy:
        scn["threshold_overrides"] = dict(scn.get("threshold_overrides", {}), **policy)
    return S.run(scn)


# ------------------------------------------------------------------ canopy failure modes
def canopy_cases():
    """(label, blackout minutes after T+30 min or None = never clears, drop after canopy)."""
    return [("no canopy", 0, 0.0), ("10 min canopy", 10, 0.0), ("30 min canopy", 30, 0.0),
            ("60 min canopy", 60, 0.0), ("2 h canopy", 120, 0.0), ("4 h canopy", 240, 0.0),
            ("60 min canopy, then patchy sky (50% loss)", 60, 0.5),
            ("60 min canopy, then poor sky (90% loss)", 60, 0.9),
            ("canopy never clears", None, 0.0)]


def canopy_report(policy=None):
    base = scenario("elapid_systemic.json")
    base["timeline"] = [e for e in base["timeline"] if e.get("base") != "resolve"]
    base["duration_s"] = 8 * 3600
    base["expect"] = {}
    rows = []
    for label, mins, drop in canopy_cases():
        scn = copy.deepcopy(base)
        start = 1800
        end = scn["duration_s"] + 1 if mins is None else start + mins * 60
        prof = []
        if mins != 0:
            prof.append({"from": start, "to": end, "blackout": True, "label": "canopy"})
        if drop and mins is not None:
            prof.append({"from": end, "to": scn["duration_s"] + 1, "drop_prob": drop, "label": "after"})
        scn["link"] = {"seed": 3, "profile": prof}
        res = run(scn, policy)
        esc = res.escalated_at()
        d = res.first_dispatch()
        alert = d[1] if d else None
        rows.append({
            "case": label,
            "delivered": bool(d),
            "delay_s": (d[0] - esc) if (d and esc) else None,
            "fix_age_s": alert.fix_age if alert and alert.lat_deg is not None else None,
            "attempts": res.device.outbox.attempts,
            "energy": energy(res, load_power(), scn["duration_s"] / 3600.0),
        })
    return rows


def print_canopy():
    print("Canopy failure modes: the elapid bite (ALERT raised at T+40 min) with canopy")
    print("from T+30 min. Simulated; 8 h run; no base close. Radio energy uses PLACEHOLDER")
    print("power figures (vrw/power.json).")
    print("-" * 92)
    print("  %-42s %-10s %12s %10s %9s %10s" % ("case", "delivered", "ALERT delay", "fix age", "attempts", "radio mAh"))
    for r in canopy_report():
        dl = "-" if r["delay_s"] is None else "%d min" % round(r["delay_s"] / 60)
        fa = "-" if r["fix_age_s"] is None else "%d min" % round(r["fix_age_s"] / 60)
        print("  %-42s %-10s %12s %10s %9d %10.1f" % (r["case"], "yes" if r["delivered"] else "NO", dl, fa,
                                                    r["attempts"], r["energy"]["radio_mah"]))
    print("-" * 92)
    print("ALERT delay = escalation to base. fix age = how old the position in the delivered ALERT")
    print("was when sent (canopy blocks GPS too). If the canopy never clears the ALERT never")
    print("arrives; after 5 min the band's local alarm tells the people with the wearer to move")
    print("to open sky (R-27). In this simulator the signal reading follows the link's loss rate,")
    print("so it is never wrong; a real reading can be, costing up to 5 min (R-26).")


# ------------------------------------------------------------------ battery budget
BATTERY_SCENARIOS = [
    ("Elapid bite, open sky (3 h)", "elapid_systemic.json", None),
    ("Elapid bite, 1 h canopy (3 h)", "canopy_link_loss.json", None),
    ("Dry bite, open sky (13 h)", "dry_bite.json", None),
    ("Dry bite, 10 h under canopy (13 h)", "dry_bite.json", [[1800, 37800]]),
    ("Field run, open field to forest (4 h)", "field_open_to_forest.json", None),
]


def battery_report():
    power = load_power()
    rows = []
    for label, name, blackouts in BATTERY_SCENARIOS:
        scn = scenario(name)
        if blackouts:
            scn = copy.deepcopy(scn)
            scn.setdefault("link", {})["blackouts"] = blackouts
        hours = scn["duration_s"] / 3600.0
        out = {"case": label, "hours": hours}
        for pname, pol in (("fixed", FIXED_POLICY), ("hardened", None)):
            res = run(scn, pol)
            e = energy(res, power, hours)
            e["attempts"] = res.device.outbox.attempts
            e["checks"] = res.device.outbox.signal_checks
            e["dispatched"] = bool(res.first_dispatch())
            out[pname] = e
        rows.append(out)
    return rows, power


def print_battery():
    rows, power = battery_report()
    print("Battery and credit budget. Simulated runs; energy from vrw/power.json (every value a")
    print("PLACEHOLDER assumption, battery %d mAh). 'fixed' = retry every 60 s regardless (M1-M3);" % power["battery_mah"])
    print("'hardened' = R-26 (urgent: 60 s, cheap check at 0 bars, full send at least every 5 min;")
    print("routine: waits for signal and backs off).")
    print("-" * 96)
    print("  %-40s %-9s %8s %7s %10s %10s %8s %8s" % ("case", "policy", "attempts", "checks", "radio mAh",
                                                       "total mAh", "battery", "up credits"))
    for r in rows:
        for p in ("fixed", "hardened"):
            e = r[p]
            print("  %-40s %-9s %8d %7d %10.1f %10.1f %7.1f%% %8d" % (
                r["case"] if p == "fixed" else "", p, e["attempts"], e["checks"], e["radio_mah"],
                e["total_mah"], e["pct"], e["credits"]))
    print("-" * 96)
    print("Read as a comparison only. 'up credits' counts band -> base messages only (each 50 bytes = 1).")
    print("Same dispatch outcome under both policies is checked by the tests.")
