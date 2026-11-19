"""Vitals from a CSV file (M3 stand-in for a wearable's SpO2 / breathing / heart sensors).

Research demonstrator — not a medical device. The CSVs in scenarios/data/ are
synthetic; a CSV exported from a wearable-class device in the same columns
would also load, for simulation only.

File format (one row per sample, any order of columns, extra columns ignored):

    # comment lines start with '#'
    t_s,spo2,rr,hr,skin_temp
    0,98,14,72,33.0
    60,,15,74,33.1          <- blank cell = no reading for that sensor

t_s is seconds from the scenario start. How values are handled (R-24):
  * a value outside vitals_plausible (e.g. SpO2 0 or 140) is a sensor
    artifact: it is dropped and counted, never passed to the trigger;
  * a missing or dropped value is NOT filled from an earlier row. Gaps stay
    gaps, and the trigger's "sustained" test refuses to bridge a gap longer
    than vitals_max_gap_s.
"""
import csv

FIELDS = ("spo2", "rr", "hr", "skin_temp")


class VitalsError(ValueError):
    pass


class VitalsCSV:
    def __init__(self, path, plausible):
        self.path = path
        self.rows = []              # (t, {field: value or None})
        self.artifacts = []         # (t, field, raw value)
        with open(path, newline="") as f:
            lines = [l for l in f if l.strip() and not l.lstrip().startswith("#")]
        reader = csv.DictReader(lines)
        if not reader.fieldnames or "t_s" not in reader.fieldnames:
            raise VitalsError("%s: first non-comment line must be a header with t_s" % path)
        last_t = None
        for n, r in enumerate(reader, start=1):
            try:
                t = int(float(r["t_s"]))
            except (TypeError, ValueError):
                raise VitalsError("%s: row %d has no valid t_s" % (path, n))
            if last_t is not None and t <= last_t:
                raise VitalsError("%s: row %d time %d is not after %d" % (path, n, t, last_t))
            last_t = t
            v = {}
            for k in FIELDS:
                raw = (r.get(k) or "").strip()
                if not raw:
                    v[k] = None
                    continue
                try:
                    x = float(raw)
                except ValueError:
                    self.artifacts.append((t, k, raw))
                    v[k] = None
                    continue
                lo, hi = plausible.get(k, (float("-inf"), float("inf")))
                if not lo <= x <= hi:
                    self.artifacts.append((t, k, raw))
                    v[k] = None
                else:
                    v[k] = x
            self.rows.append((t, v))

    def between(self, t0, t1):
        """Newest row with t0 < t <= t1, or None. Never repeats an older row."""
        hit = None
        for t, v in self.rows:
            if t0 < t <= t1:
                hit = v
            elif t > t1:
                break
        if hit is None or all(x is None for x in hit.values()):
            return None
        return dict(hit)
