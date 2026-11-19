"""M4 gate tests: field hardening. Run: python3 -m unittest -v

Research demonstrator — not a medical device.

Gate (docs/03-MILESTONES.md): a timed end-to-end field simulation (open field
-> forest edge) reaches a human responder, run through the real dashboard
server; times are recorded in STATUS.md (from `python3 -m vrw field`).
"""
import json
import os
import tempfile
import threading
import unittest

from dashboard.server import make_server
from vrw import fieldtools as FT
from vrw import packet as P
from vrw import scenario as S
from vrw.base import Base
from vrw.device import Device
from vrw.link.sim_sbd import SimLink
from vrw.outbox import Outbox
from vrw.remote import HttpBase
from vrw.trigger import State, load_thresholds

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TH = load_thresholds()
T0 = 1795075200


def msg(mt, seq, t=T0, **kw):
    d = dict(msg_type=mt, device_id=9, seq=seq, event_time=t, send_time=t, state=3,
             flags=P.F_SIMULATED | P.F_TRAINER_HARDWARE)
    d.update(kw)
    return P.Uplink(**d)


class FakeLink:
    """Signal and success are set by the test."""
    def __init__(self, bars=5, ok=True):
        self.bars, self.ok, self.sent = bars, ok, []

    def signal(self, now):
        return self.bars

    def attempt_uplink(self, now, data):
        if self.ok:
            self.sent.append(P.Uplink.from_bytes(data))
            return True, now + 20
        return False, None


def ob(path=None, urgent_blind_s=None):
    return Outbox(60, path, backoff_max_s=900, min_signal=2, max_items=6, urgent_blind_s=urgent_blind_s)


class SwitchLink(FakeLink):
    """Sends fail until `ok_from`; the signal reading is whatever `bars` says."""
    def __init__(self, bars, ok_from):
        FakeLink.__init__(self, bars=bars)
        self.ok_from = ok_from

    def attempt_uplink(self, now, data):
        self.ok = now >= self.ok_from
        return FakeLink.attempt_uplink(self, now, data)


class RebootTests(unittest.TestCase):
    def test_band_rebuilt_from_flash_keeps_queue_and_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "outbox.json")
            dev = Device(9, TH, outbox_path=path)
            dev.step(T0, lfa={"control_ok": True, "levels": {"3FTx": 2}})      # CONTACT_INFO seq 0
            self.assertEqual(len(dev.outbox), 1)
            dev2 = Device(9, TH, outbox_path=path)                             # power cycle
            self.assertEqual(len(dev2.outbox), 1)
            self.assertEqual(dev2.seq, 1)
            dev2.step(T0 + 600)
            self.assertEqual(dev2.machine.state, State.SYSTEMIC_WATCH)   # R-25: watch resumed
            self.assertEqual(dev2.machine.lfa_levels[0], 2)              # cassette result kept
            self.assertEqual(dev2.machine.confirmed_at, T0)              # 12 h watch not restarted
            self.assertEqual([i["uplink"].seq for i in dev2.outbox.items], [0])

    def test_isf_watch_resumes_with_families_and_history(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "outbox.json")
            dev = Device(9, TH, outbox_path=path)
            for k in range(0, 600, 60):
                dev.step(T0 + k, isf={"3FTx": 1})               # ISF confirms the local signal
            self.assertEqual(dev.machine.state, State.SYSTEMIC_WATCH)
            dev2 = Device(9, TH, outbox_path=path)
            dev2.step(T0 + 900)                                  # no new readings yet
            self.assertEqual(dev2.machine.state, State.SYSTEMIC_WATCH)
            self.assertEqual(dev2.machine.family_mask() & 0x0F, 1)    # 3FTx still named
            self.assertTrue(dev2.machine.local_positive())
            dev2.step(T0 + 960, isf={"3FTx": 2})                 # rise spans the outage
            self.assertEqual(dev2.machine.state, State.ESCALATED)

    def test_close_from_base_works_after_a_power_cycle(self):
        scn = S.load(os.path.join(ROOT, "scenarios", "canopy_power_cycle.json"))
        scn["timeline"] = [e for e in scn["timeline"] if "vitals" not in e or e["t"] < 3000]
        for blk in scn["isf_reads"]:
            blk["to"] = min(blk["to"], 2999)          # no re-detection possible after the reboot
        scn["timeline"].append({"t": 7200, "base": "resolve"})
        scn["expect"] = {}
        res = S.run(scn)
        self.assertEqual(res.final_state, State.RESOLVED)
        self.assertIn("RESOLVED", res.received_types())

    def test_base_keeps_new_message_that_reuses_a_number(self):
        b = Base()
        b.receive(T0, msg(P.CONTACT_INFO, 0).to_bytes())
        b.receive(T0 + 30, msg(P.CONTACT_INFO, 0).copy(send_time=T0 + 30).to_bytes())   # a retry
        self.assertEqual(b.duplicates, 1)
        b.receive(T0 + 900, msg(P.ALERT, 0, T0 + 880).to_bytes())   # seq restarted after a reboot
        self.assertEqual(len(b.received), 2)
        self.assertTrue(b.dispatch_for(9))

    def test_damaged_file_is_set_aside(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "outbox.json")
            with open(path, "w") as f:
                f.write('{"items": [{"hex": "zz')
            o = ob(path)
            self.assertEqual(len(o), 0)
            self.assertIsNotNone(o.load_error)
            self.assertTrue(os.path.exists(path + ".damaged"))

    def test_power_cycle_scenario(self):
        res = S.run(S.load(os.path.join(ROOT, "scenarios", "canopy_power_cycle.json")))
        self.assertTrue(all(c[1] for c in S.check(res)), [c for c in S.check(res) if not c[1]])
        self.assertTrue(any(e[1] == "reboot" for e in res.events))


class RetryPolicyTests(unittest.TestCase):
    def test_alert_is_first_out_after_blackout(self):
        o = ob()
        link = SimLink(blackouts=[(T0, T0 + 600)])
        o.put(msg(P.HEARTBEAT, 1), T0)
        o.process(T0, link)                       # routine fails (signal 0): backs off
        o.put(msg(P.ALERT, 2, T0 + 30), T0 + 30)  # urgent arrives: due now
        t = T0 + 30
        first = None
        while first is None and t < T0 + 2000:
            r = o.process(t, link)
            if r:
                first = r[0]
            t += 10
        self.assertEqual(first.msg_type, P.ALERT)
        self.assertLess(t, T0 + 700)              # within one urgent retry of the sky opening

    def test_without_blind_rule_signal_never_holds_back_urgent(self):
        o, link = ob(), FakeLink(bars=0)
        o.put(msg(P.ALERT, 1), T0)
        self.assertIsNotNone(o.process(T0, link))
        o.put(msg(P.HEARTBEAT, 2), T0 + 10)
        self.assertIsNone(o.process(T0 + 10, link))   # routine waits for signal
        self.assertEqual(o.attempts, 1)
        self.assertEqual(o.signal_checks, 1)

    def test_shipped_policy_worst_case_is_five_minutes(self):
        """R-26 as shipped: a reading of 0 bars can delay an urgent send that would have
        worked, but never by more than urgent_blind_s (300 s) after the last attempt."""
        o = ob(urgent_blind_s=300)
        link = SwitchLink(bars=0, ok_from=T0 + 30)       # reading wrong: sending works from T0+30
        o.put(msg(P.ALERT, 1), T0)
        self.assertIsNone(o.process(T0, link))           # first attempt fails
        t, sent = T0, None
        while sent is None:
            t += 10
            sent = o.process(t, link)
        self.assertEqual(t - T0, 300)
        self.assertGreater(o.signal_checks, 0)

    def test_shipped_policy_sends_within_a_minute_when_bars_show(self):
        o = ob(urgent_blind_s=300)
        link = SwitchLink(bars=0, ok_from=T0 + 30)
        o.put(msg(P.ALERT, 1), T0)
        o.process(T0, link)
        link.bars = 3                                    # sky opens and the reading shows it
        t, sent = T0, None
        while sent is None:
            t += 10
            sent = o.process(t, link)
        self.assertLessEqual(t - T0, 60)

    def test_stuck_alert_sets_off_local_alarm(self):
        dev = Device(9, TH)
        dev.machine.state = State.ESCALATED
        dev.machine.last_alert_at = T0
        dev._enqueue(T0, P.ALERT)
        link = SimLink(blackouts=[(T0, T0 + 1200)])
        for k in range(0, 1500, 10):
            dev.step(T0 + k)
            dev.outbox.process(T0 + k, link)
        self.assertEqual(dev.alarms[0], (T0 + TH["stuck_alarm_s"], "on"))
        self.assertEqual(dev.alarms[1][1], "off")
        self.assertGreaterEqual(dev.alarms[1][0], T0 + 1200)
        self.assertFalse(dev.alarm_on)

    def test_routine_backs_off_urgent_does_not(self):
        o, link = ob(), FakeLink(bars=5, ok=False)
        o.put(msg(P.HEARTBEAT, 1), T0)
        waits, t, last = [], T0, T0
        for _ in range(8):
            while o.process(t, link) is None and o.next_session > t:
                break
            waits.append(o.next_session - t)
            t = o.next_session
        self.assertEqual(waits[:5], [60, 120, 240, 480, 900])
        self.assertEqual(max(waits), 900)
        o.put(msg(P.ALERT, 2, t), t)
        o.process(t, link)
        self.assertEqual(o.next_session - t, 60)

    def test_queue_is_bounded_and_never_drops_urgent(self):
        o = ob()
        for i in range(5):
            o.put(msg(P.HEARTBEAT, i, T0 + i), T0 + i)
        self.assertEqual(len(o), 1)                   # only the newest heartbeat
        for i in range(10):
            o.put(msg(P.ALERT, 100 + i, T0 + 100 + i), T0 + 100)
        self.assertEqual(sum(1 for i in o.items if i["uplink"].msg_type == P.ALERT), 10)
        self.assertFalse(o.has_pending(P.HEARTBEAT))  # routine evicted to respect the limit
        self.assertEqual(len(o.evicted), 1)

    def test_retry_refreshes_position_not_what_happened(self):
        dev = Device(9, TH)
        dev.set_fix(T0, -3.0, -62.0, 4.0)
        dev.machine.state = State.ESCALATED
        dev._enqueue(T0, P.ALERT)
        queued = dev.outbox.items[0]["uplink"]
        dev.set_fix(T0 + 3000, -3.1, -62.1, 1.0)
        link = FakeLink()
        dev.outbox.process(T0 + 3000, link)
        sent = link.sent[0]
        self.assertAlmostEqual(sent.lat_deg, -3.1, places=5)
        self.assertEqual(sent.fix_age, 0)
        for f in ("msg_type", "seq", "event_time", "state", "family_mask", "escalation_reason"):
            self.assertEqual(getattr(sent, f), getattr(queued, f), f)


    def test_restored_alert_keeps_position_until_a_new_fix(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "outbox.json")
            dev = Device(9, TH, outbox_path=path)
            dev.set_fix(T0, -3.0, -62.0, 1.0)
            dev.vitals_latest = {"spo2": 88, "rr": 26, "hr": 110}
            dev.machine.state = State.ESCALATED
            dev._enqueue(T0, P.ALERT)
            dev2 = Device(9, TH, outbox_path=path)          # power cycle: no fix, no vitals yet
            link = FakeLink()
            dev2.outbox.process(T0 + 600, link)
            sent = link.sent[0]
            self.assertAlmostEqual(sent.lat_deg, -3.0, places=5)
            self.assertTrue(sent.flags & P.F_GPS_VALID)
            self.assertEqual(sent.fix_age, 600)               # aged, not reset
            self.assertEqual(sent.spo2, 88)

    def test_responder_waits_without_any_position(self):
        from vrw.responder import Responder
        cfg = {"decision_delay_s": 0, "trailhead": {"lat": -3.45, "lon": -62.2}, "vehicle_kmh": 25,
               "foot_kmh": 2.5, "search_s": 900, "fix_old_s": 900}
        r = Responder(cfg, {"lat": -3.43, "lon": -62.18}, T0)
        r.observe(T0, msg(P.ALERT, 1))                         # no GPS in the alert
        for t in range(T0, T0 + 7200, 10):
            r.step(t)
        self.assertNotIn("on_scene", r.times)
        self.assertEqual(r.phase, "driving")

class FieldGateTests(unittest.TestCase):
    def setUp(self):
        self.srv = make_server(port=0)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_field_run_reaches_responder_through_dashboard(self):
        scn = S.load(os.path.join(ROOT, "scenarios", "field_open_to_forest.json"))
        base = HttpBase(self.url)
        base.reset(scn["name"], scn["base_position"])
        sim = S.Simulation(scn, base=base)
        base.sim = sim
        while not sim.done:
            sim.step()
        st = base._req("GET", "/api/state")
        b = next(x for x in st["bands"] if x["device_id"] == scn["device_id"])
        self.assertEqual(b["state"], "RESOLVED")                    # band confirmed the close
        self.assertEqual(b["responder"]["status"], "on_scene")
        self.assertEqual(b["dispatch"]["payload_class"], "FAMILY_MATCHED")
        self.assertEqual(sim.dev.machine.responder[0], 3)          # band heard "on scene"
        rows = S.field_times(sim.result(), b["dispatch"]["arrival"])
        self.assertTrue(all(t is not None for _, _, t in rows), rows)
        times = [t for _, _, t in rows]
        self.assertEqual(times, sorted(times))                     # milestones in order
        # responder went to the band's REPORTED position after canopy, not the old one
        self.assertAlmostEqual(sim.responder.target[0], -3.4610, places=3)

    def test_field_scenario_checks_in_process(self):
        res = S.run(S.load(os.path.join(ROOT, "scenarios", "field_open_to_forest.json")))
        self.assertEqual([c for c in S.check(res) if not c[1]], [])


class FieldToolTests(unittest.TestCase):
    def test_hardened_never_costs_more_and_same_outcome(self):
        rows, _ = FT.battery_report()
        for r in rows:
            f, h = r["fixed"], r["hardened"]
            self.assertEqual(f["dispatched"], h["dispatched"], r["case"])
            # signal checks cost a little in open sky; never more than 1 mAh extra
            self.assertLessEqual(h["radio_mah"], f["radio_mah"] + 1.0, r["case"])
        canopy = next(r for r in rows if "10 h under canopy" in r["case"])
        self.assertLess(canopy["hardened"]["radio_mah"], canopy["fixed"]["radio_mah"] / 5)

    def test_canopy_sweep(self):
        rows = FT.canopy_report()
        never = rows[-1]
        self.assertFalse(never["delivered"])
        self.assertTrue(all(r["delivered"] for r in rows[:-1]))
        delays = [r["delay_s"] for r in rows[1:6]]
        self.assertEqual(delays, sorted(delays))                   # longer canopy, longer delay

    def test_power_file_all_placeholder(self):
        with open(FT.POWER) as f:
            raw = json.load(f)
        self.assertIn("not a medical device", raw["_note"])
        for k, v in raw.items():
            if not k.startswith("_"):
                self.assertEqual(v["status"], "PLACEHOLDER", k)


class ModemDriverTests(unittest.TestCase):
    """Against FakeModem only. This proves the driver follows our reading of the AT
    commands, NOT that it works with a real modem (D-23)."""

    def test_refuses_real_port_without_flag(self):
        from vrw.link.rockblock import ModemError, RockBlockLink
        with self.assertRaises(ModemError):
            RockBlockLink.open("/dev/null")

    def test_send_receive_and_signal(self):
        from vrw.link.rockblock import FakeModem, RockBlockLink
        dl = P.Downlink(P.DL_ACK, 9, 1, T0, responder_status=1).to_bytes()
        fake = FakeModem(bars=3, mt_message=dl)
        link = RockBlockLink(fake)
        link.setup()
        self.assertEqual(link.signal(), 3)
        up = msg(P.ALERT, 1).to_bytes()
        self.assertEqual(link.attempt_uplink(T0, up), (True, None))
        self.assertEqual(fake.sent, [up])
        self.assertEqual(link.due_downlinks(T0), [(T0, dl)])

    def test_outbox_drives_driver_and_keeps_message_on_failure(self):
        from vrw.link.rockblock import FakeModem, RockBlockLink
        fake = FakeModem(mo_status=32)            # 32 = no network service
        o = ob()
        o.put(msg(P.ALERT, 1), T0)
        link = RockBlockLink(fake)
        self.assertIsNone(o.process(T0, link))
        self.assertEqual(len(o), 1)
        fake.mo_status = 0
        self.assertIsNotNone(o.process(T0 + 60, link))
        self.assertEqual(len(o), 0)


class ReadmeCompletenessTests(unittest.TestCase):
    """The README is the full system reference: it must name every field, type, state and threshold."""

    def test_readme_names_everything(self):
        import dataclasses
        with open(os.path.join(ROOT, "README.md")) as f:
            text = f.read()
        names = [f.name for f in dataclasses.fields(P.Uplink)] + ["crc16"]
        names += [f.name for f in dataclasses.fields(P.Downlink)]
        names += list(P.UPLINK_NAMES.values()) + list(P.DOWNLINK_NAMES.values())
        names += [st.name for st in State]
        with open(os.path.join(ROOT, "vrw", "thresholds.json")) as f:
            names += [k for k in json.load(f) if not k.startswith("_")]
        with open(FT.POWER) as f:
            names += [k for k in json.load(f) if not k.startswith("_")]
        missing = [n for n in names if n not in text]
        self.assertEqual(missing, [])
        self.assertIn("not a medical device", text)
        self.assertIn("Start here", text)


if __name__ == "__main__":
    unittest.main()
