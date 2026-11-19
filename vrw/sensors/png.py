"""Minimal PNG reader and writer, standard library only (R-11).

Research demonstrator — not a medical device.

Reads non-interlaced 8-bit greyscale, grey+alpha, RGB and RGBA images with any
of the five PNG row filters. Anything else (palette, 16-bit, interlaced) raises
PngError with a plain message. The writer emits 8-bit greyscale and is only
used to make synthetic cassette images; it rotates through all five row
filters so the reader's filter code is exercised by our own files.
"""
import struct
import zlib

SIG = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}      # colour type -> samples per pixel


class PngError(ValueError):
    pass


def _chunks(data):
    if data[:8] != SIG:
        raise PngError("not a PNG file")
    i = 8
    while i + 8 <= len(data):
        n, typ = struct.unpack(">I4s", data[i:i + 8])
        body = data[i + 8:i + 8 + n]
        if len(body) != n:
            raise PngError("file is cut short")
        crc = struct.unpack(">I", data[i + 8 + n:i + 12 + n])[0] if i + 12 + n <= len(data) else None
        if crc is None or crc != zlib.crc32(typ + body) & 0xFFFFFFFF:
            raise PngError("damaged chunk %r" % typ)
        yield typ, body
        i += 12 + n
        if typ == b"IEND":
            return
    raise PngError("no end marker")


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read(path_or_bytes):
    """Return (width, height, rows) where rows[y][x] is luminance 0-255 (alpha ignored)."""
    data = path_or_bytes
    if not isinstance(data, (bytes, bytearray)):
        with open(path_or_bytes, "rb") as f:
            data = f.read()
    ihdr, idat = None, []
    for typ, body in _chunks(bytes(data)):
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif typ == b"IDAT":
            idat.append(body)
    if ihdr is None:
        raise PngError("missing header")
    w, h, depth, ctype, _comp, _filt, interlace = ihdr
    if depth != 8 or ctype not in CHANNELS:
        raise PngError("only 8-bit grey/RGB/RGBA images are supported (got depth %d, type %d)" % (depth, ctype))
    if interlace:
        raise PngError("interlaced PNG not supported")
    if not (1 <= w <= 4000 and 1 <= h <= 4000):
        raise PngError("image size %dx%d out of range" % (w, h))
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as e:
        raise PngError("damaged image data (%s)" % e)
    bpp = CHANNELS[ctype]
    stride = w * bpp
    if len(raw) < h * (stride + 1):
        raise PngError("image data too short")
    prev = bytearray(stride)
    rows = []
    for y in range(h):
        off = y * (stride + 1)
        ft = raw[off]
        line = bytearray(raw[off + 1:off + 1 + stride])
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(a, prev[i], c)) & 0xFF
        elif ft != 0:
            raise PngError("unknown row filter %d" % ft)
        prev = line
        if bpp <= 2:
            rows.append(list(line[0::bpp]))
        else:   # ITU-R BT.601 luma
            rows.append([(299 * line[i] + 587 * line[i + 1] + 114 * line[i + 2]) // 1000
                         for i in range(0, stride, bpp)])
    return w, h, rows


def _filter_row(ft, line, prev):
    out = bytearray(len(line))
    for i, x in enumerate(line):
        a = line[i - 1] if i else 0
        b = prev[i]
        c = prev[i - 1] if i else 0
        pred = (0, a, b, (a + b) >> 1, _paeth(a, b, c))[ft]
        out[i] = (x - pred) & 0xFF
    return out


def write_grey(path, rows):
    """Write rows (lists of 0-255 ints) as an 8-bit greyscale PNG."""
    h, w = len(rows), len(rows[0])
    prev = bytearray(w)
    raw = bytearray()
    for y, r in enumerate(rows):
        line = bytearray(max(0, min(255, int(v))) for v in r)
        ft = y % 5
        raw.append(ft)
        raw += _filter_row(ft, line, prev)
        prev = line

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    data = SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(data)
