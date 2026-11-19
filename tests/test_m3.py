"""M3 gate tests: sensor stand-ins. Run: python3 -m unittest -v

Research demonstrator — not a medical device.

Gate (docs/03-MILESTONES.md): a contact-only scenario fed by stand-in inputs
stays out of ESCALATED; a systemic scenario escalates. Both run here from the
real files in scenarios/data/, through the image and CSV readers.
"""
import glob
import json
import os
import shutil
import tempfile
import unittest
import zlib

from vrw import scenario as S
from vrw.sensors import lateral_flow as LF
from vrw.sensors import png, synth
from vrw.sensors.vitals import VitalsCSV, VitalsError
from vrw.trigger import State, TriggerMachine, load_thresholds

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "scenarios", "data")
FIX = os.path.join(ROOT, "tests", "fixtures")
TH = load_thresholds()


def run(name, **changes):
    scn = S.load(os.path.join(ROOT, "scenarios", name))
    scn.update(changes)
    return S.run(scn)


class GateTests(unittest.TestCase):
    def test_contact_only_from_standins_never_escalates(self):
        res = run("standin_contact_only.json")
        visited = res.states_visited()
        self.assertNotIn(State.ESCALATED, visited)
        self.assertIsNone(res.first_dispatch())
        # not vacuous: the image really was read and confirmed the local signal
        self.assertIn(State.SYSTEMIC_WATCH, visited)
        self.assertEqual(res.lfa_reads[0][2]["levels"], {"3FTx": 1})
        self.assertEqual(res.final_state, State.STOOD_DOWN)

    def test_systemic_from_standins_escalates_on_vitals(self):
        res = run("standin_systemic_vitals.json")
        self.assertIn(State.ESCALATED, res.states_visited())
        d = res.first_dispatch()
        self.assertIsNotNone(d)
        self.assertEqual(d[2], "FAMILY_MATCHED")
        self.assertEqual(sorted(d[1].families), ["3FTx", "PLA2"])
        # the CSV, not the scripted ISF, caused it
        self.assertTrue(set(d[1].reasons) & {"spo2_fall", "rr_rise"})
        self.assertNotIn("isf_rise", d[1].reasons)

    def test_contact_only_with_systemic_vitals_would_escalate(self):
        # Same contact-only story with the systemic CSV swapped in: proves the
        # contact-only result comes from the data, not from a dead input path.
        res = run("standin_contact_only.json", vitals_csv="data/vitals_systemic.csv", duration_s=10800)
        self.assertIn(State.ESCALATED, res.states_visited())

    def test_invalid_cassette_counts_for_nothing(self):
        res = run("standin_invalid_then_retest.json")
        self.assertFalse(res.lfa_reads[0][2]["control_ok"])
        self.assertGreaterEqual(res.machine.log[0][0] - res.start, 1200)
        self.assertEqual(res.final_state, State.SYSTEMIC_WATCH)

    def test_all_scenarios_pass(self):
        for p in S.scenario_paths(ROOT):
            res = S.run(S.load(p))
            bad = [c for c in S.check(res) if not c[1]]
            self.assertEqual(bad, [], os.path.basename(p))


class PngTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_round_trip_all_five_filters(self):
        rows = [[(x * 7 + y * 13) % 256 for x in range(37)] for y in range(11)]   # 11 rows: every filter used
        p = os.path.join(self.tmp, "a.png")
        png.write_grey(p, rows)
        w, h, back = png.read(p)
        self.assertEqual((w, h), (37, 11))
        self.assertEqual(back, rows)

    def test_reads_rgb_from_apple_encoder(self):
        # made with macOS sips from the shipped elapid cassette (colour type 2, Apple's own filters)
        for name in ("cassette_elapid_rgb_apple.png", "cassette_elapid_via_jpeg.png"):
            r = LF.read_image(os.path.join(FIX, name), TH)
            self.assertTrue(r["control_ok"], name)
            self.assertEqual(r["levels"], {"3FTx": 2, "PLA2": 1}, name)

    def test_bad_files_are_errors(self):
        p = os.path.join(self.tmp, "x.png")
        with open(p, "wb") as f:
            f.write(b"not a png at all")
        with self.assertRaises(png.PngError):
            png.read(p)
        with open(os.path.join(DATA, "cassette_blank_control_only.png"), "rb") as f:
            good = f.read()
        with self.assertRaises(png.PngError):
            png.read(good[:len(good) // 2])              # cut short
        bad = bytearray(good)
        bad[40] ^= 0xFF                                  # damage the header chunk
        with self.assertRaises(png.PngError):
            png.read(bytes(bad))


class CassetteReaderTests(unittest.TestCase):
    def read(self, levels, **kw):
        return LF.read_rows(synth.cassette_rows(levels, **kw), TH)

    def test_every_band_and_family(self):
        for fam in ("3FTx", "PLA2", "SVMP", "SVSP"):
            for band in (1, 2, 3, 4):
                r = self.read({fam: band}, seed=band)
                self.assertTrue(r["control_ok"])
                self.assertEqual(r["levels"], {fam: band}, (fam, band, r["detail"]))

    def test_blank_strip_is_valid_negative(self):
        r = LF.read_image(os.path.join(DATA, "cassette_blank_control_only.png"), TH)
        self.assertTrue(r["control_ok"])
        self.assertEqual(r["levels"], {})

    def test_no_control_is_invalid_even_with_strong_lines(self):
        for off in (-0.08, 0.0, 0.08):
            r = self.read({"3FTx": 4, "PLA2": 3}, control=False, offset=off)
            self.assertFalse(r["control_ok"], off)
            self.assertEqual(r["levels"], {})

    def test_shift_and_brightness_never_change_the_family(self):
        want = {"3FTx": 2, "PLA2": 1}
        for off in (-0.08, -0.04, 0.0, 0.04, 0.08):
            for b in (0.6, 0.8, 1.0, 1.1):
                r = self.read(want, offset=off, brightness=b, seed=int(off * 100 + b * 10))
                if b >= 0.8:
                    self.assertTrue(r["control_ok"], (off, b))
                if r["control_ok"]:
                    self.assertEqual(r["levels"], want, (off, b))

    def test_flipped_image_is_invalid_never_another_family(self):
        cases = [(v[0], v[1]) for v in synth.CASSETTES.values()]
        cases += [({f: b}, True) for f in ("3FTx", "PLA2", "SVMP", "SVSP") for b in (1, 2, 3, 4)]
        cases += [({"3FTx": 2, "PLA2": 1, "SVMP": 3, "SVSP": 4}, True)]
        for levels, control in cases:
            for off in (-0.06, 0.0, 0.06):
                rows = synth.cassette_rows(levels, control=control, offset=off)
                mirrored = [r[::-1] for r in rows]
                upside_down = [r[::-1] for r in rows[::-1]]
                for flipped in (mirrored, upside_down):
                    r = LF.read_rows(flipped, TH)
                    self.assertFalse(r["control_ok"], (levels, off, r.get("detail")))

    def test_unexpected_line_is_invalid(self):
        rows = synth.cassette_rows({"3FTx": 2})
        w = len(rows[0])
        mid = LF.CONTROL_X + 1.5 * LF.LINE_PITCH        # half-way between 3FTx and PLA2 lines
        x = int(w * (0.10 + 0.80 * mid))
        for row in rows[20:100]:
            for i in range(x - 4, x + 5):
                row[i] -= 80
        r = LF.read_rows(rows, TH)
        self.assertFalse(r["control_ok"])
        self.assertIn("unexpected", r["error"])

    def test_no_window_or_unreadable_file_is_invalid(self):
        flat = [[200] * 300 for _ in range(80)]
        self.assertFalse(LF.read_rows(flat, TH)["control_ok"])
        r = LF.read_image(os.path.join(ROOT, "README.md"), TH)
        self.assertFalse(r["control_ok"])
        r = LF.read_image(os.path.join(ROOT, "no_such_file.png"), TH)
        self.assertFalse(r["control_ok"])

    def test_shipped_images_read_as_named(self):
        for name, (levels, control, *_rest) in synth.CASSETTES.items():
            r = LF.read_image(os.path.join(DATA, name), TH)
            self.assertEqual(r["control_ok"], control, name)
            if control:
                self.assertEqual(r["levels"], {k: v for k, v in levels.items() if v}, name)

    def test_shipped_data_matches_generator(self):
        tmp = tempfile.mkdtemp()
        try:
            for name in synth.make_all(tmp):
                with open(os.path.join(tmp, name), "rb") as a, open(os.path.join(DATA, name), "rb") as b:
                    self.assertEqual(a.read(), b.read(), name + " differs: run python3 -m vrw make-data")
        finally:
            shutil.rmtree(tmp)


class VitalsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def csv(self, text):
        p = os.path.join(self.tmp, "v.csv")
        with open(p, "w") as f:
            f.write(text)
        return VitalsCSV(p, TH["vitals_plausible"])

    def test_artifacts_dropped_blanks_kept_blank(self):
        v = self.csv("# note\nt_s,spo2,rr,hr\n0,98,14,70\n60,0,,71\n120,140,15,abc\n")
        self.assertEqual(v.between(-1, 0), {"spo2": 98, "rr": 14, "hr": 70, "skin_temp": None})
        self.assertEqual(v.between(0, 60), {"spo2": None, "rr": None, "hr": 71, "skin_temp": None})
        self.assertEqual(sorted((t, k) for t, k, _ in v.artifacts), [(60, "spo2"), (120, "hr"), (120, "spo2")])

    def test_no_carry_forward_across_a_gap(self):
        v = self.csv("t_s,spo2\n0,90\n600,90\n")
        self.assertIsNotNone(v.between(-10, 0))
        for k in range(10, 600, 10):
            self.assertIsNone(v.between(k - 10, k), k)

    def test_bad_files(self):
        with self.assertRaises(VitalsError):
            self.csv("spo2,rr\n98,14\n")
        with self.assertRaises(VitalsError):
            self.csv("t_s,spo2\n60,98\n0,97\n")

    def test_gap_breaks_a_sustained_low(self):
        def feed(times):
            m = TriggerMachine(TH)
            for t in times:
                m.update(t, vitals={"spo2": 99 - t // 100, "rr": 14, "hr": 80})
            return m
        full = feed(range(0, 1201, 60))
        self.assertTrue(full.vitals_reasons(1200))       # sustained low and falling: counts
        gappy = feed([t for t in range(0, 1201, 60) if not 1020 <= t <= 1140])
        self.assertFalse(gappy.vitals_reasons(1200))     # 4-minute hole inside the 5-minute hold window


class DataFolderTests(unittest.TestCase):
    def test_data_readme_says_synthetic_and_disclaimer(self):
        with open(os.path.join(DATA, "README.md")) as f:
            text = f.read()
        self.assertIn("not a medical device", text)
        self.assertIn("synthetic", text.lower())
        for p in glob.glob(os.path.join(DATA, "*.csv")):
            with open(p) as f:
                self.assertIn("not a medical device", f.readline(), p)


if __name__ == "__main__":
    unittest.main()
