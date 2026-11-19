"""Lateral-flow cassette image -> family code (M3 stand-in).

Research demonstrator — not a medical device. Reads synthetic images only;
it has never seen a real cassette and makes no diagnostic claim.

The image shows the cassette's result window: a dark frame with the test
strip inside it, running left to right:

    ##############################################
    # | C |  3FTx  |  PLA2  |  SVMP  |  SVSP  |   #
    ##############################################
       control      one test line per toxin family

How a read works (thresholds in vrw/thresholds.json, R-23):
  1. Average the middle rows into one brightness profile along the image.
  2. Find the window: the dark frame edges left and right. Every position
     below is a fraction of the window, so a photo taken off-centre still
     reads. No frame found = INVALID.
  3. Find the control line inside the narrow control zone. It must stand out
     from the strip beside it by lfa_control_min_contrast, or the read is
     INVALID (control_ok False) and counts for nothing.
  4. Each family line is looked for at its fixed place in the window, and its
     darkness is measured against the strip beside it (so a brighter or darker
     photo still reads).
  5. Line darkness / control darkness -> band 0-4 via lfa_band_ratios.
  6. A dark line anywhere the layout doesn't expect one -> INVALID. The
     layout is deliberately lopsided, so an image that is upside down or
     mirrored puts its lines in unexpected places and reads INVALID, never
     as a different family.

Any problem reading the file returns an INVALID read with the reason. A bad
or unexpected image can never produce a positive.

Limitation: the window must be roughly level and fully in the picture. Real
phone photos would need a cassette-finding and straightening step first
(later, with a pinned image library, R-11).
"""
from .. import packet as P
from . import png

# Geometry of the synthetic cassette (engineering, D-18), fractions of the window width.
CONTROL_X = 0.12              # off-centre on purpose: a flipped image puts every line
                              # 0.08 away from any real position (see D-18)
LINE_PITCH = 0.17             # family line i sits at CONTROL_X + (i+1) * LINE_PITCH
LINE_HALF = 0.025             # half-width searched for the darkest point
BG_NEAR, BG_FAR = 0.045, 0.075  # background sampled this far either side of a line
ROWS = (0.35, 0.65)           # rows of the image used for the profile
FRAME_DARK = 0.4              # a frame column is darker than this x the median


def invalid(reason, detail=None):
    r = {"control_ok": False, "levels": {}, "unclassified": False, "error": reason}
    if detail:
        r["detail"] = detail
    return r


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def read_profile(rows):
    h, w = len(rows), len(rows[0])
    r0 = int(h * ROWS[0])
    r1 = max(r0 + 1, int(h * ROWS[1]))
    n = float(r1 - r0)
    return [sum(rows[y][x] for y in range(r0, r1)) / n for x in range(w)]


def find_window(prof):
    """(left, right) pixel columns just inside the frame, or None."""
    cut = FRAME_DARK * _median(prof)
    dark = [i for i, v in enumerate(prof) if v < cut]
    if not dark:
        return None
    # left frame = first dark run, right frame = last dark run
    l = dark[0]
    while l + 1 < len(prof) and prof[l + 1] < cut:
        l += 1
    r = dark[-1]
    while r - 1 >= 0 and prof[r - 1] < cut:
        r -= 1
    if r - l < 0.3 * len(prof):
        return None
    return l + 1, r - 1


def read_rows(rows, th):
    w = len(rows[0])
    if w < 100 or len(rows) < 10:
        return invalid("image too small to read (%dx%d)" % (w, len(rows)))
    prof = read_profile(rows)
    win = find_window(prof)
    if win is None:
        return invalid("result window not found")
    left, right = win
    strip = prof[left:right + 1]
    sw = len(strip)

    def contrast(centre):
        lo = max(0, int(round((centre - LINE_HALF) * sw)))
        hi = min(sw - 1, int(round((centre + LINE_HALF) * sw)))
        core = strip[lo:hi + 1]
        darkest = min(core)
        xmin = lo + core.index(darkest)
        bg = [strip[i] for i in range(sw) if BG_NEAR * sw <= abs(i - xmin) <= BG_FAR * sw]
        return (_median(bg) - darkest if bg else 0.0), xmin / float(sw)

    lo, hi = th["lfa_control_search"]
    zone = strip[int(lo * sw):int(hi * sw) + 1]
    cx = (int(lo * sw) + zone.index(min(zone))) / float(sw)
    c_con, _ = contrast(cx)
    detail = {"window_px": [left, right], "control_x": round(cx, 3), "control_contrast": round(c_con, 1)}
    if c_con < th["lfa_control_min_contrast"]:
        return invalid("no control line (contrast %.0f < %s)" % (c_con, th["lfa_control_min_contrast"]), detail)
    levels, ratios = {}, {}
    expected = [cx]
    for i, fam in enumerate(P.FAMILIES):
        centre = CONTROL_X + (i + 1) * LINE_PITCH
        expected.append(centre)
        c, _ = contrast(centre)
        ratio = max(0.0, c / c_con)
        ratios[fam] = round(ratio, 2)
        band = sum(1 for cut in th["lfa_band_ratios"] if ratio >= cut)
        if band:
            levels[fam] = band
    detail["ratios"] = ratios
    f = 0.04
    while f <= 0.96:
        if all(abs(f - e) > LINE_HALF + 0.03 for e in expected):
            c, x = contrast(f)
            if c / c_con >= th["lfa_band_ratios"][0]:
                return invalid("unexpected line at %.0f%% of the window" % (100 * x), detail)
        f += 0.01
    return {"control_ok": True, "levels": levels, "unclassified": False, "detail": detail}


def read_image(path, th):
    """Read a cassette image file. Returns the dict the trigger machine takes as `lfa`."""
    try:
        _w, _h, rows = png.read(path)
    except (OSError, png.PngError) as e:
        return invalid("could not read image: %s" % e)
    return read_rows(rows, th)
