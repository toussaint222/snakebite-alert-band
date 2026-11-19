"""Simulated Iridium-class short-burst-data link.

Research demonstrator — not a medical device.

Models (assumptions, see DECISIONS D-08):
  * uplink max 340 bytes, downlink max 270 bytes
  * latency uniformly between latency_s[0] and latency_s[1] (default 10-60 s)
  * random drop probability per attempt
  * blackout windows (dense canopy): every attempt fails, nothing gets through
  * (M4) a profile of zones over time, e.g. open field -> forest edge -> canopy,
    each with its own drop probability (or a blackout)
  * (M4) a signal reading 0-5 bars, like a modem's signal-quality query: 0 in a
    blackout, otherwise roughly 5 x (1 - drop probability) with some jitter.
    It uses its own random generator, so adding signal checks never changes
    the latencies of earlier scenario runs.

Downlink (base -> band) is only received when the band can see the sky:
a downlink that would arrive during a blackout is delivered when the
blackout ends plus a fresh latency.
"""
import random

MO_MAX = 340
MT_MAX = 270


class SimLink:
    def __init__(self, latency_s=(10, 60), drop_prob=0.0, blackouts=(), seed=1, profile=()):
        self.latency_s = tuple(latency_s)
        self.drop_prob = drop_prob
        self.blackouts = [tuple(b) for b in blackouts]   # absolute (start, end) times
        self.rng = random.Random(seed)
        self.sig_rng = random.Random(seed + 7919)
        # profile: [(start, end, drop_prob or None for blackout, label)], absolute times
        self.profile = [tuple(z) for z in profile]
        self.blackouts += [(a, b) for a, b, p, _ in self.profile if p is None]
        self.downlinks = []                               # (arrival_time, bytes)
        self.uplink_bytes_sent = 0
        self.uplink_attempts = 0

    def in_blackout(self, t):
        return any(a <= t < b for a, b in self.blackouts)

    def zone(self, t):
        return next((z for z in self.profile if z[0] <= t < z[1]), None)

    def drop_at(self, t):
        z = self.zone(t)
        return self.drop_prob if z is None or z[2] is None else z[2]

    def signal(self, t):
        """Signal bars 0-5 as a modem would report them (cheap to ask)."""
        if self.in_blackout(t):
            return 0
        bars = 5 * (1 - self.drop_at(t)) + self.sig_rng.uniform(-1, 1)
        return max(0, min(5, int(round(bars))))

    def _latency(self):
        return self.rng.uniform(*self.latency_s)

    def attempt_uplink(self, now, data):
        """Returns (success, arrival_time_at_base)."""
        if len(data) > MO_MAX:
            raise ValueError("uplink %d bytes exceeds %d" % (len(data), MO_MAX))
        self.uplink_attempts += 1
        if self.in_blackout(now) or self.rng.random() < self.drop_at(now):
            return False, None
        self.uplink_bytes_sent += len(data)
        return True, now + self._latency()

    def send_downlink(self, now, data):
        if len(data) > MT_MAX:
            raise ValueError("downlink %d bytes exceeds %d" % (len(data), MT_MAX))
        t = now + self._latency()
        for a, b in sorted(self.blackouts):
            if a <= t < b:
                t = b + self._latency()
        self.downlinks.append((t, data))

    def due_downlinks(self, now):
        due = [d for d in self.downlinks if d[0] <= now]
        self.downlinks = [d for d in self.downlinks if d[0] > now]
        return sorted(due)
