"""Optional driver for a RockBLOCK 9603-class Iridium modem (R-12). UNTESTED ON HARDWARE.

Research demonstrator — not a medical device.

Same interface as the simulated link (signal / attempt_uplink / due_downlinks),
so the outbox can drive a real modem. Written from the vendor's AT-command
documentation and checked only against FakeModem in tests/test_m4.py. Before any
field use it must be tested on a real modem (D-23).

Safety and cost:
  * It never opens a serial port unless called with allow_real_modem=True.
  * Every real send costs message credits (1 per 50 bytes or part of 50;
    D-08) and needs an active line rental.
  * Packets still carry the simulated + trainer flags; the base rejects others.

Commands used (Iridium SBD AT set):
  AT          attention          AT&K0  no flow control     ATE0  no echo
  AT+CSQ      signal bars 0-5    AT+SBDWB=<n>  write n bytes + 2-byte checksum
  AT+SBDIX    run a session: +SBDIX: <MO status>,<MOMSN>,<MT status>,<MTMSN>,<MT length>,<MT queued>
              MO status 0-4 = sent; MT status 1 = a message from base came down
  AT+SBDRB    read the downloaded message: 2-byte length, data, 2-byte checksum
  AT+SBDD0    clear the outgoing buffer
pyserial is needed only for a real port (pinned, installed into .venv when used).
"""
import struct
import time

MO_MAX = 340
MT_MAX = 270


class ModemError(RuntimeError):
    pass


def checksum(data):
    return struct.pack(">H", sum(data) & 0xFFFF)


class RockBlockLink:
    def __init__(self, port, clock=time.time, timeout_s=60):
        """`port` is anything with write(bytes), readline() -> bytes, read(n) -> bytes."""
        self.port = port
        self.clock = clock
        self.timeout_s = timeout_s
        self.downlinks = []
        self.uplink_attempts = 0
        self.uplink_bytes_sent = 0

    @classmethod
    def open(cls, device, allow_real_modem=False, baud=19200):
        if not allow_real_modem:
            raise ModemError("refusing to open a real modem without allow_real_modem=True "
                             "(each send costs credits; see vrw/link/rockblock.py)")
        import serial          # pinned pyserial, only for real hardware
        link = cls(serial.Serial(device, baud, timeout=1))
        link.setup()
        return link

    # ------------------------------------------------------------ AT plumbing
    def _cmd(self, cmd, expect=b"OK", raw=None):
        self.port.write(cmd.encode() + b"\r")
        lines = []
        deadline = self.clock() + self.timeout_s
        while True:
            line = self.port.readline()
            if not line:
                if self.clock() > deadline:
                    raise ModemError("timeout waiting for %r after %s" % (expect, cmd))
                continue
            line = line.strip()
            if not line or line == cmd.encode():
                continue
            if line == b"ERROR":
                raise ModemError("%s -> ERROR" % cmd)
            if line == expect:
                return lines
            lines.append(line)

    def setup(self):
        self._cmd("AT")
        self._cmd("ATE0")
        self._cmd("AT&K0")

    # ------------------------------------------------------------ link interface
    def signal(self, now=None):
        for line in self._cmd("AT+CSQ"):
            if line.startswith(b"+CSQ:"):
                return int(line.split(b":")[1])
        raise ModemError("no +CSQ reply")

    def attempt_uplink(self, now, data):
        """One SBD session. Returns (sent, None): the gateway gives no arrival time at the base."""
        if not 1 <= len(data) <= MO_MAX:
            raise ValueError("uplink %d bytes outside 1..%d" % (len(data), MO_MAX))
        self.uplink_attempts += 1
        self._cmd("AT+SBDWB=%d" % len(data), expect=b"READY")
        self.port.write(bytes(data) + checksum(data))
        status = self._read_status()
        if status != 0:
            raise ModemError("SBDWB status %d (1 timeout, 2 bad checksum, 3 bad size)" % status)
        mo, mt = self._session()
        if mt == 1:
            self._read_mt(now)
        if mo <= 4:
            self._cmd("AT+SBDD0")
            self.uplink_bytes_sent += len(data)
            return True, None
        return False, None

    def _read_status(self):
        while True:
            line = self.port.readline().strip()
            if line in (b"0", b"1", b"2", b"3"):
                st = int(line)
                if self.port.readline().strip() != b"OK":
                    raise ModemError("no OK after SBDWB status")
                return st
            if line == b"ERROR":
                raise ModemError("SBDWB -> ERROR")

    def _session(self):
        for line in self._cmd("AT+SBDIX"):
            if line.startswith(b"+SBDIX:"):
                f = [int(x) for x in line.split(b":")[1].split(b",")]
                return f[0], f[2]
        raise ModemError("no +SBDIX reply")

    def _read_mt(self, now):
        self.port.write(b"AT+SBDRB\r")
        n = struct.unpack(">H", self.port.read(2))[0]
        if n > MT_MAX:
            raise ModemError("downlink length %d > %d" % (n, MT_MAX))
        data = self.port.read(n)
        if self.port.read(2) != checksum(data):
            raise ModemError("downlink checksum mismatch")
        while self.port.readline().strip() != b"OK":
            pass
        self.downlinks.append((now, data))

    def due_downlinks(self, now):
        out, self.downlinks = self.downlinks, []
        return out


class FakeModem:
    """A scripted stand-in for the modem's serial port, for tests. Not a real modem."""

    def __init__(self, bars=4, mo_status=0, mt_message=None):
        self.bars, self.mo_status, self.mt = bars, mo_status, mt_message
        self.out = []            # bytes the driver will read
        self.rx = b""            # bytes written by the driver
        self.sent = []           # messages that "went to the satellite"
        self.pending_len = None

    def _say(self, *lines):
        self.out += [l + b"\r\n" for l in lines]

    def write(self, b):
        if self.pending_len is not None:
            self.rx += b
            n = self.pending_len
            if len(self.rx) >= n + 2:
                data, ck = self.rx[:n], self.rx[n:n + 2]
                self.pending_len, self.rx = None, b""
                ok = ck == checksum(data)
                if ok:
                    self.buffer = data
                self._say(b"0" if ok else b"2", b"OK")
            return
        cmd = b.strip()
        if cmd in (b"AT", b"ATE0", b"AT&K0", b"AT+SBDD0"):
            self._say(b"OK")
        elif cmd == b"AT+CSQ":
            self._say(b"+CSQ:%d" % self.bars, b"OK")
        elif cmd.startswith(b"AT+SBDWB="):
            self.pending_len = int(cmd.split(b"=")[1])
            self._say(b"READY")
        elif cmd == b"AT+SBDIX":
            if self.mo_status <= 4:
                self.sent.append(self.buffer)
            mt = 1 if self.mt else 0
            self._say(b"+SBDIX: %d, 1, %d, 1, %d, 0" % (self.mo_status, mt, len(self.mt or b"")), b"OK")
        elif cmd == b"AT+SBDRB":
            m, self.mt = self.mt, None
            self.out.append(struct.pack(">H", len(m)) + m + checksum(m))
            self._say(b"OK")
        else:
            self._say(b"ERROR")

    def readline(self):
        if not self.out:
            return b""
        item = self.out[0]
        if b"\n" in item:
            i = item.index(b"\n") + 1
            line, rest = item[:i], item[i:]
        else:
            line, rest = item, b""
        if rest:
            self.out[0] = rest
        else:
            self.out.pop(0)
        return line

    def read(self, n):
        buf = b""
        while len(buf) < n and self.out:
            item = self.out[0]
            take = item[:n - len(buf)]
            buf += take
            if len(take) == len(item):
                self.out.pop(0)
            else:
                self.out[0] = item[len(take):]
        return buf
