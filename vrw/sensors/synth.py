"""Synthetic stand-in data: cassette images and vitals CSVs.

Research demonstrator — not a medical device. Everything this makes is
invented for simulation; none of it is clinical or measured data.
"""
import random

from .. import packet as P
from . import lateral_flow as LF

# Line darkness per band as a fraction of the control line's darkness. Chosen in
# the middle of each R-23 band so a correct reader lands in the right band.
BAND_RATIO = {0: 0.0, 1: 0.2, 2: 0.42, 3: 0.68, 4: 0.92}


def cassette_rows(levels, control=True, width=400, height=120, offset=0.0,
                  brightness=1.0, noise=4.0, seed=1, control_dark=110):
    """Greyscale rows of a synthetic cassette photo. levels: {family: band 0-4}.

    The result window is 80% of the image wide; `offset` moves it sideways by
    that fraction of the image width (an off-centre photo).
    """
    rnd = random.Random(seed)
    b = brightness
    housing, strip_bg, frame = 238.0 * b, 225.0 * b, 25.0 * b
    wl = (0.10 + offset) * width
    ww = 0.80 * width
    lines = []
    if control:
        lines.append((LF.CONTROL_X, control_dark * b))
    for i, fam in enumerate(P.FAMILIES):
        band = int(levels.get(fam, 0))
        if band:
            lines.append((LF.CONTROL_X + (i + 1) * LF.LINE_PITCH, control_dark * b * BAND_RATIO[band]))
    half = 0.012 * ww
    col = []
    for x in range(width):
        if x < wl - 5 or x > wl + ww + 5:
            col.append(housing)
            continue
        if x < wl or x > wl + ww:
            col.append(frame)
            continue
        v = strip_bg
        for cx, depth in lines:
            d = abs(x - (wl + cx * ww))
            if d <= half:
                v -= depth
            elif d <= half + 3:                   # soft edge
                v -= depth * (1 - (d - half) / 3.0)
        col.append(v)
    top, bot = int(0.12 * height), int(0.88 * height)
    rows = []
    for y in range(height):
        if y < top - 4 or y > bot + 4:
            base = [housing] * width
        elif y < top or y > bot:
            base = [frame if wl - 5 <= x <= wl + ww + 5 else housing for x in range(width)]
        else:
            base = col
        rows.append([max(0, min(255, int(round(v + rnd.gauss(0, noise))))) for v in base])
    return rows


def vitals_rows(keyframes, duration_s, every_s=60, seed=1, noise=None):
    """Sampled vitals from keyframes [(t, {spo2, rr, hr, skin_temp})] with small noise."""
    noise = noise or {"spo2": 0.4, "rr": 0.4, "hr": 1.5, "skin_temp": 0.05}
    rnd = random.Random(seed)
    out = []
    for t in range(0, duration_s + 1, every_s):
        for (t0, a), (t1, b) in zip(keyframes, keyframes[1:]):
            if t0 <= t <= t1:
                f = (t - t0) / float(t1 - t0) if t1 > t0 else 1.0
                v = {k: a[k] + (b[k] - a[k]) * f for k in a}
                break
        else:
            v = dict(keyframes[-1][1])
        row = {"t_s": t}
        for k, val in v.items():
            val += rnd.gauss(0, noise.get(k, 0))
            if k == "spo2":
                val = min(100, val)
            row[k] = round(val, 1) if k == "skin_temp" else int(round(val))
        out.append(row)
    return out


def write_vitals_csv(path, rows, header_note):
    cols = ["t_s", "spo2", "rr", "hr", "skin_temp"]
    with open(path, "w") as f:
        f.write("# Research demonstrator - not a medical device. SYNTHETIC data, invented for simulation.\n")
        for line in header_note.strip().splitlines():
            f.write("# %s\n" % line)
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join("" if r.get(c) is None else str(r[c]) for c in cols) + "\n")


# ------------------------------------------------------------ the shipped data set
CASSETTES = {
    # file name: (levels, control line present, offset, brightness, seed)
    "cassette_contact_trace_3ftx.png": ({"3FTx": 1}, True, 0.0, 1.0, 11),
    "cassette_elapid_3ftx2_pla2_1.png": ({"3FTx": 2, "PLA2": 1}, True, 0.05, 0.9, 12),
    "cassette_viper_svmp3_svsp2.png": ({"SVMP": 3, "SVSP": 2}, True, -0.04, 1.05, 13),
    "cassette_invalid_no_control.png": ({"3FTx": 3}, False, 0.0, 1.0, 14),
    "cassette_blank_control_only.png": ({}, True, 0.0, 1.0, 15),
}

CONTACT_ONLY_NOTE = """Contact-only vitals (no body-wide signs), 13 h, one row a minute.
Heart rate jumps after the bite (fright) and settles. SpO2 and breathing stay normal.
Built-in problems the reader must survive:
  t=7200-7380  SpO2 reads 86-88 for 3 min (a slipped probe) - too short to count as sustained
  t=9000       SpO2 reads 0 (sensor artifact) - dropped
  t=14400-15600 no rows at all (band taken off for 20 min) - a gap, not filled in
  t=20000-20100 RR cell blank - no reading"""

SYSTEMIC_NOTE = """Systemic (elapid-like) vitals, 3 h, one row a minute.
SpO2 falls from 97 to 88 and breathing rate climbs from 16 to 27 between 50 and 90 min."""


def make_all(data_dir):
    """(Re)write every synthetic file in scenarios/data/. Deterministic (fixed seeds)."""
    import os
    from . import png
    os.makedirs(data_dir, exist_ok=True)
    written = []
    for name, (levels, control, offset, bright, seed) in CASSETTES.items():
        png.write_grey(os.path.join(data_dir, name),
                       cassette_rows(levels, control=control, offset=offset, brightness=bright, seed=seed))
        written.append(name)

    kf = [(0, {"spo2": 98, "rr": 14, "hr": 72, "skin_temp": 33.0}),
          (300, {"spo2": 98, "rr": 15, "hr": 105, "skin_temp": 33.1}),
          (1800, {"spo2": 98, "rr": 14, "hr": 80, "skin_temp": 33.0}),
          (46800, {"spo2": 98, "rr": 14, "hr": 76, "skin_temp": 33.0})]
    rows = vitals_rows(kf, 46800, seed=21)
    out = []
    for r in rows:
        t = r["t_s"]
        if 7200 <= t <= 7380:
            r["spo2"] = 86 + (t // 60) % 3
        if t == 9000:
            r["spo2"] = 0
        if 14400 <= t <= 15600:
            continue
        if 20000 <= t <= 20100:
            r["rr"] = None
        out.append(r)
    write_vitals_csv(os.path.join(data_dir, "vitals_contact_only.csv"), out, CONTACT_ONLY_NOTE)
    written.append("vitals_contact_only.csv")

    kf = [(0, {"spo2": 98, "rr": 14, "hr": 75, "skin_temp": 33.0}),
          (300, {"spo2": 98, "rr": 15, "hr": 100, "skin_temp": 33.1}),
          (3000, {"spo2": 97, "rr": 16, "hr": 104, "skin_temp": 33.2}),
          (5400, {"spo2": 88, "rr": 27, "hr": 118, "skin_temp": 33.4}),
          (10800, {"spo2": 87, "rr": 28, "hr": 120, "skin_temp": 33.4})]
    write_vitals_csv(os.path.join(data_dir, "vitals_systemic.csv"), vitals_rows(kf, 10800, seed=22), SYSTEMIC_NOTE)
    written.append("vitals_systemic.csv")
    return written
