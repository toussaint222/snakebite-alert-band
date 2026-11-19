"""M1 gate tests. Run: python3 -m unittest -v

Research demonstrator — not a medical device.
"""
import glob
import json
import os
import random
import tempfile
import unittest

from vrw import packet as P
from vrw import scenario as S
from vrw.base import Base
from vrw.link.sim_sbd import SimLink
from vrw.outbox import Outbox
from vrw.trigger import ALLOWED, State, TriggerMachine, load_thresholds, DEFAULT_THRESHOLDS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = 1795075200


def alert(**kw):
    d = dict(msg_type=P.ALERT, device_id=7, seq=1, event_time=T0, send_time=T0, state=3)
    d.update(kw)
    return P.Uplink(**d)


class PacketTests(unittest.TestCase):
    def test_crc_check_value(self):
        self.assertEqual(P.crc16(b"123456789"), 0x29B1)

    def test_sizes_fit_budget(self):
        self.assertEqual(P.UPLINK_SIZE, 50)
        self.assertEqual(P.DOWNLINK_SIZE, 16)
        self.assertLessEqual(P.UPLINK_SIZE, 340)
        self.assertLessEqual(P.DOWNLINK_SIZE, 270)

    def test_round_trip_extremes(self):
        for u in [alert(), alert(device_id=0xFFFFFFFF, seq=0xFFFF, lat=-900000000, lon=1800000000,
                                 spo2_slope=-127, rr_slope=127, skin_temp=-32767,
                                 family_level=[0, 1, 4, 255])]:
            self.assertEqual(P.Uplink.from_bytes(u.to_bytes()), u)

    def test_corruption_rejected(self):
        b = bytearray(alert().to_bytes())
        b[10] ^= 0x01
        with self.assertRaises(P.PacketError):
            P.Uplink.from_bytes(bytes(b))

    def test_wrong_length_rejected(self):
        with self.assertRaises(P.PacketError):
            P.Uplink.from_bytes(alert().to_bytes()[:-1])

    def test_out_of_range_raises_not_wraps(self):
        with self.assertRaises(P.PacketError):
            alert(heart_rate=300).to_bytes()

    def test_clamp_keeps_sentinel_reserved(self):
        self.assertEqual(P.clamp_i8(-500), -127)
        self.assertEqual(P.clamp_i8(None), P.NA_I8)

    def test_downlink_round_trip(self):
        d = P.Downlink(P.DL_RESOLVE, 7, 12, T0, 3, 15)
        self.assertEqual(P.Downlink.from_bytes(d.to_bytes()), d)

    def test_default_flags_are_simulated_trainer(self):
        need = P.F_SIMULATED | P.F_TRAINER_HARDWARE
        self.assertEqual(alert().flags & need, need)


class TriggerTests(unittest.TestCase):
    def setUp(self):
        self.th = load_thresholds()

    def run_machine(self, m, seconds, step=60, lfa_at=None, isf=None, vitals=None, action_at=None):
        for k in range(0, seconds + 1, step):
            m.update(T0 + k,
                     lfa=lfa_at[1] if lfa_at and lfa_at[0] == k else None,
                     isf=isf(k) if isf else None,
                     vitals=vitals(k) if vitals else None,
                     action="local_cancel" if action_at == k else None)
        return m

    def test_contact_only_never_escalates_random(self):
        """Two-signal rule: weak local signal + normal vitals never escalates (200 random runs)."""
        rng = random.Random(42)
        for _ in range(200):
            m = TriggerMachine(self.th)
            fam = rng.choice(P.FAMILIES)
            lvl = rng.choice([1, 2])               # below danger_level
            self.run_machine(m, 6 * 3600, lfa_at=(rng.randrange(0, 3600, 60),
                                                  {"control_ok": True, "levels": {fam: lvl}}),
                             vitals=lambda k: {"spo2": rng.uniform(95, 99), "rr": rng.uniform(12, 18),
                                               "hr": rng.uniform(60, 110)})
            self.assertNotEqual(m.state, State.ESCALATED)
            self.assertNotIn(State.ESCALATED, [to for _, _, to, _ in m.log])

    def test_vitals_only_never_escalates_random(self):
        """No local signal: even terrible vitals never escalate (R-02)."""
        rng = random.Random(7)
        for _ in range(100):
            m = TriggerMachine(self.th)
            self.run_machine(m, 4 * 3600, vitals=lambda k: {
                "spo2": max(70, 99 - k / 300.0 * rng.uniform(0, 2)), "rr": 14 + k / 400.0, "hr": 120})
            self.assertNotIn(State.ESCALATED, [to for _, _, to, _ in m.log])

    def test_invalid_test_never_confirms(self):
        m = TriggerMachine(self.th)
        self.run_machine(m, 3600, lfa_at=(60, {"control_ok": False, "levels": {"3FTx": 4}}))
        self.assertEqual(m.state, State.IDLE)
        self.assertTrue(m.family_mask() & P.FM_TEST_INVALID)

    def test_isf_confirmation_needs_two_spaced_reads(self):
        m = TriggerMachine(self.th)
        m.update(T0, isf={"3FTx": 1})
        self.assertEqual(m.state, State.CONTACT)
        m.update(T0 + 60, isf={"3FTx": 1})                 # too soon
        self.assertEqual(m.state, State.CONTACT)
        m.update(T0 + 180, isf={"3FTx": 1})
        self.assertEqual(m.state, State.SYSTEMIC_WATCH)

    def test_one_isf_sensor_cannot_supply_both_signals(self):
        """R-19: ISF 0 -> 1 confirms local but is not also a systemic rise."""
        m = TriggerMachine(self.th)
        self.run_machine(m, 4 * 3600, isf=lambda k: {} if k < 300 else {"3FTx": 1},
                         vitals=lambda k: {"spo2": 98, "rr": 14, "hr": 80})
        self.assertEqual(m.state, State.SYSTEMIC_WATCH)
        # ...but a later real rise after confirmation still escalates
        m2 = TriggerMachine(self.th)
        self.run_machine(m2, 4 * 3600, isf=lambda k: {} if k < 300 else {"3FTx": 1 if k < 3600 else 2})
        self.assertEqual(m2.state, State.ESCALATED)
        self.assertEqual(m2.reason, P.R_ISF_RISE)

    def test_unconfirmed_contact_returns_to_idle(self):
        m = TriggerMachine(self.th)
        m.update(T0, isf={"3FTx": 1})
        for k in range(60, 1200, 60):
            m.update(T0 + k, isf={})
        self.assertEqual(m.state, State.IDLE)

    def test_danger_timer_needs_strong_level(self):
        for lvl, expect in [(2, State.SYSTEMIC_WATCH), (3, State.ESCALATED)]:
            m = TriggerMachine(self.th)
            self.run_machine(m, self.th["danger_time_s"] + 600,
                             lfa_at=(0, {"control_ok": True, "levels": {"SVMP": lvl}}))
            self.assertEqual(m.state, expect, "level %d" % lvl)
            if expect == State.ESCALATED:
                self.assertEqual(m.reason, P.R_LOCAL_DANGER)

    def test_local_cancel_before_danger(self):
        m = TriggerMachine(self.th)
        self.run_machine(m, 3 * 3600, lfa_at=(0, {"control_ok": True, "levels": {"SVMP": 4}}),
                         action_at=1800)
        self.assertEqual(m.state, State.RESOLVED)

    def test_escalated_is_latched(self):
        m = TriggerMachine(self.th)
        self.run_machine(m, 30 * 3600, lfa_at=(0, {"control_ok": True, "levels": {"SVMP": 4}}))
        self.assertEqual(m.state, State.ESCALATED)        # 30 h later, still escalated
        out = m.on_downlink(T0 + 30 * 3600, P.Downlink(P.DL_RESOLVE, 1, 0, T0))
        self.assertEqual(out, [P.RESOLVED])
        self.assertEqual(m.state, State.RESOLVED)

    def test_illegal_transition_guard(self):
        m = TriggerMachine(self.th)
        self.assertNotIn((State.CONTACT, State.ESCALATED), ALLOWED)
        self.assertNotIn((State.IDLE, State.ESCALATED), ALLOWED)
        with self.assertRaises(AssertionError):
            m._set(T0, State.ESCALATED, "test")

    def test_thresholds_all_marked(self):
        with open(DEFAULT_THRESHOLDS) as f:
            raw = json.load(f)
        for k, v in raw.items():
            if k.startswith("_"):
                continue
            self.assertIn(v["status"], ("PLACEHOLDER", "RULED"), k)
            self.assertTrue(v["ruling"], k)


class LinkAndBaseTests(unittest.TestCase):
    def test_outbox_persists_and_prioritises_alert(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "q.json")
            ob = Outbox(60, path)
            ob.put(alert(msg_type=P.HEARTBEAT, seq=1), T0)
            ob.put(alert(seq=2, event_time=T0 + 5), T0 + 5)
            ob2 = Outbox(60, path)                         # "power cycle"
            self.assertEqual(len(ob2), 2)
            link = SimLink(blackouts=[(T0, T0 + 120)])
            self.assertIsNone(ob2.process(T0 + 10, link))  # blackout
            sent = ob2.process(T0 + 130, link)
            self.assertEqual(sent[0].msg_type, P.ALERT)    # alert jumps the queue
            self.assertTrue(sent[0].flags & P.F_RETRANSMISSION)
            self.assertEqual(sent[0].seq, 2)
            self.assertEqual(sent[0].event_time, T0 + 5)

    def test_base_dedupes_and_orders_by_event_time(self):
        b = Base()
        newer = alert(seq=5, event_time=T0 + 100)
        older = alert(msg_type=P.CONTACT_INFO, seq=4, event_time=T0, state=2)
        b.receive(T0 + 200, newer.to_bytes())
        b.receive(T0 + 210, newer.copy(send_time=T0 + 150).to_bytes())   # retry copy
        b.receive(T0 + 220, older.to_bytes())                             # late arrival
        self.assertEqual(b.duplicates, 1)
        self.assertEqual(b.bands[7].msg_type, P.ALERT)                   # not overwritten by older

    def test_base_ignores_alert_that_arrives_after_its_cancel(self):
        b = Base()
        al = alert(seq=1, event_time=T0)
        cancel = alert(msg_type=P.CANCELLED_LOCAL, seq=2, event_time=T0 + 10, state=4)
        b.receive(T0 + 20, cancel.to_bytes())      # jitter: cancel overtakes the alert
        b.receive(T0 + 50, al.to_bytes())
        self.assertEqual(b.dispatches, [])
        self.assertEqual(len(b.stale_alerts), 1)

    def test_cancel_after_dispatch_is_recorded_not_auto_recalled(self):
        b = Base()
        b.receive(T0 + 20, alert(seq=1).to_bytes())
        b.receive(T0 + 90, alert(msg_type=P.CANCELLED_LOCAL, seq=2, event_time=T0 + 60, state=4).to_bytes())
        self.assertEqual(len(b.dispatches), 1)
        self.assertEqual(len(b.cancelled_after_dispatch), 1)

    def test_base_rejects_non_simulated(self):
        b = Base()
        b.receive(T0, alert(flags=0).to_bytes())
        self.assertEqual(len(b.received), 0)
        self.assertEqual(len(b.rejected), 1)


class ScenarioTests(unittest.TestCase):
    def test_every_scenario_passes(self):
        paths = S.scenario_paths(ROOT)
        self.assertGreaterEqual(len(paths), 4)
        for p in paths:
            with self.subTest(scenario=os.path.basename(p)):
                checks = S.check(S.run(S.load(p)))
                failed = [c for c in checks if not c[1]]
                self.assertEqual(failed, [])

    def test_brief_scenarios_present(self):
        names = {os.path.basename(p) for p in S.scenario_paths(ROOT)}
        for n in ["dry_bite.json", "elapid_systemic.json", "viper_local_only.json", "canopy_link_loss.json"]:
            self.assertIn(n, names)


class DisclaimerTests(unittest.TestCase):
    def test_every_doc_carries_disclaimer(self):
        docs = [os.path.join(ROOT, f) for f in ("README.md", "DECISIONS.md", "STATUS.md", "VISION.md")]
        docs += glob.glob(os.path.join(ROOT, "docs", "*.md"))
        docs += glob.glob(os.path.join(ROOT, "scenarios", "*.md"))
        for p in docs:
            with open(p) as f:
                self.assertIn("not a medical device", f.read(), p)


if __name__ == "__main__":
    unittest.main()
