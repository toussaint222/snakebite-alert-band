"""M2 gate tests: the dashboard as the base station. Run: python3 -m unittest -v

Research demonstrator — not a medical device.
"""
import glob
import json
import os
import re
import threading
import unittest
import urllib.error
import urllib.request

from dashboard import checklist as CL
from dashboard.server import make_server
from vrw import packet as P
from vrw import scenario as S
from vrw.remote import HttpBase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCN = os.path.join(ROOT, "scenarios")


class DashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.srv = make_server(port=0)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=5) as r:
            return r.read().decode()

    def state(self):
        return json.loads(self.get("/api/state"))

    def sim(self, name, scripted_base=False):
        scn = S.load(os.path.join(SCN, name + ".json"))
        base = HttpBase(self.url)
        base.reset(scn["name"], scn.get("base_position"))
        sim = S.Simulation(scn, base=base, scripted_base=scripted_base)
        base.sim = sim
        return sim

    def band(self, st, dev):
        return next(b for b in st["bands"] if b["device_id"] == dev)


class GateTests(DashboardTestCase):
    def test_elapid_alert_and_checklist_within_60s_then_close_from_dashboard(self):
        """M2 gate: simulated bite -> correct, readable alert + checklist, < 60 s simulated latency."""
        sim = self.sim("elapid_systemic")
        while not sim.done and not self.band_or_none(sim, "dispatch"):
            sim.step()
        st = self.state()
        b = self.band(st, 1003)
        d = b["dispatch"]
        self.assertEqual(b["state"], "ESCALATED")
        self.assertEqual(d["payload_class"], "FAMILY_MATCHED")
        self.assertLess(d["latency_s"], 60)
        self.assertTrue(any("3FTx" in f for f in d["families"]))
        self.assertTrue(any("3FTx" in c for c in d["checklist"]["carry"]))
        self.assertTrue(any("bag-valve" in r for r in d["checklist"]["reminders"]))
        self.assertTrue(any("rising" in r for r in d["reasons"]))
        self.assertEqual(d["checklist"]["status"], "PLACEHOLDER")
        self.assertIsNotNone(b["position"])
        self.assertTrue(b["can_resolve"])
        # a person closes it on the dashboard; RESOLVE must travel down the link to the band
        req = urllib.request.Request(self.url + "/api/resolve", method="POST",
                                     data=json.dumps({"device_id": 1003}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
        for _ in range(60):
            sim.step()
        self.assertEqual(sim.dev.machine.state.name, "RESOLVED")
        closed = self.band(self.state(), 1003)
        self.assertEqual(closed["state"], "RESOLVED")
        self.assertEqual(closed["cancelled_after_dispatch"], [])   # a normal close is not an R-18 recall question

    def band_or_none(self, sim, key):
        st = self.state()
        for b in st["bands"]:
            if b.get(key):
                return b
        return None

    def test_canopy_alert_shows_its_delay(self):
        sim = self.sim("canopy_link_loss")
        while not sim.done:
            sim.step()
        b = self.band(self.state(), 1006)
        self.assertGreaterEqual(b["dispatch"]["latency_s"], 3000)
        self.assertEqual(b["dispatch"]["alert_event_time"], sim.result().escalated_at())

    def test_cancel_before_send_never_shows_dispatch(self):
        sim = self.sim("canopy_cancel_before_send")
        while not sim.done:
            sim.step()
        b = self.band(self.state(), 1009)
        self.assertIsNone(b["dispatch"])
        self.assertEqual(b["state"], "RESOLVED")
        self.assertEqual(b["last_type"], "CANCELLED_LOCAL")

    def test_dry_bite_never_shows_dispatch(self):
        scn = S.load(os.path.join(SCN, "dry_bite.json"))
        scn["duration_s"] = 3600          # first hour is enough: contact info, no alert
        base = HttpBase(self.url); base.reset(scn["name"])
        sim = S.Simulation(scn, base=base); base.sim = sim
        while not sim.done:
            sim.step()
        b = self.band(self.state(), 1001)
        self.assertIsNone(b["dispatch"])
        self.assertIn("Not a dispatch", b["last_note"])

    def test_viper_local_danger_gets_broad_checklist(self):
        sim = self.sim("viper_local_only")
        while not sim.done:
            sim.step()
        d = self.band(self.state(), 1004)["dispatch"]
        self.assertEqual(d["payload_class"], "BROAD")
        self.assertTrue(any("broad" in c.lower() for c in d["checklist"]["carry"]))


class ServerSafetyTests(DashboardTestCase):
    def test_rejects_non_simulated_packet(self):
        u = P.Uplink(P.ALERT, 9, 1, 1, 1, 3, flags=0)
        req = urllib.request.Request(self.url + "/api/uplink", data=u.to_bytes(), method="POST")
        self.assertFalse(json.loads(urllib.request.urlopen(req, timeout=5).read())["accepted"])
        self.assertEqual(len(self.state()["rejected"]), 1)
        self.assertEqual(self.state()["bands"], [])

    def test_static_path_traversal_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("/static/../server.py")
        self.assertEqual(e.exception.code, 404)

    def test_every_page_carries_disclaimer(self):
        self.assertIn("not a medical device", self.get("/"))
        self.assertIn("not a medical device", self.state()["disclaimer"])
        for p in glob.glob(os.path.join(ROOT, "dashboard", "static", "*.html")):
            with open(p) as f:
                self.assertIn("not a medical device", f.read(), p)

    def test_no_internet_dependencies(self):
        """Offline field use (R-10): no external scripts, styles, fonts or tiles."""
        for p in glob.glob(os.path.join(ROOT, "dashboard", "static", "*")):
            with open(p) as f:
                text = f.read()
            urls = [u for u in re.findall(r"https?://[^\s\"')]+", text) if "w3.org/2000/svg" not in u]
            self.assertEqual(urls, [], p)


class ChecklistTests(unittest.TestCase):
    def setUp(self):
        self.cfg = CL.load()

    def test_broad(self):
        c = CL.build(self.cfg, "BROAD", ["SVMP"])
        self.assertIn(self.cfg["broad"]["carry"], c["carry"])

    def test_family_matched_combines_and_dedupes(self):
        c = CL.build(self.cfg, "FAMILY_MATCHED", ["3FTx", "PLA2"])
        self.assertEqual(len(c["carry"]), 2)
        self.assertEqual(len(c["reminders"]), len(set(c["reminders"])))
        for a in self.cfg["always"]:
            self.assertIn(a, c["reminders"])

    def test_no_treatment_language(self):
        """Copy names what to carry and reminders; never dosing or treatment instructions (guardrail)."""
        text = json.dumps(self.cfg).lower()
        for word in ("dose", "dosage", "mg", "vial", "inject the", "administer the", "diagnos", "treat "):
            self.assertNotIn(word, text, word)

    def test_placeholder_until_ruled(self):
        self.assertEqual(self.cfg["status"], "PLACEHOLDER")


if __name__ == "__main__":
    unittest.main()
