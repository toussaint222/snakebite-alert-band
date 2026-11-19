"""Store-and-forward outbox (hardened in M4).

Research demonstrator — not a medical device.

Every message is put here BEFORE any send attempt and removed only when the
link reports success. Link loss is the normal case, not an error.

Live readings (D-21): just before a send, the band may refresh a queued
message's context fields (position, vitals, battery) to "now"; what the
message reports (type, seq, event time, state, families, reasons) never changes.

Order: urgent messages (ALERT, CANCELLED_LOCAL, RESOLVED) always go first,
oldest event first. A retry keeps the same `seq` and `event_time`, gets a new
`send_time`, and sets the retransmission flag.

Retry policy (R-26, numbers in thresholds.json):
  * One schedule for the whole queue (one modem, one session at a time), so a
    HEARTBEAT can never get out ahead of a waiting ALERT.
  * While anything urgent is waiting: try every retry_interval_s. If the signal
    reads 0 bars, that try is only a cheap signal check, but a full send is
    forced at least every urgent_blind_attempt_s (R-26). Worst case: a wrong
    0-bar reading delays a send that would have worked by up to 5 min.
  * Only routine messages waiting: look at the signal first (cheap); try only
    if it shows at least link_min_signal bars; after each failure wait twice
    as long, up to retry_backoff_max_s.
  * After a success: the next message may go at once.

Bounded size (R-26): at most queue_max messages. Only one HEARTBEAT is ever
kept (the newest). When full, the oldest routine message is dropped. Urgent
messages are never dropped to make room.

Power-cycle safe (R-25): with `path`, the queue AND the next sequence number
are written to a JSON file after every change (write to a temp file, flush to
disk, then rename, so a power cut leaves either the old or the new file). On
start-up the file is read back; a damaged file is set aside, not trusted.
"""
import json
import os

from . import packet as P

URGENT = (P.ALERT, P.CANCELLED_LOCAL, P.RESOLVED)


class Outbox:
    def __init__(self, retry_interval_s, path=None, backoff_max_s=None, min_signal=0, max_items=64,
                 urgent_blind_s=None):
        self.retry_interval_s = retry_interval_s
        self.backoff_max_s = backoff_max_s if backoff_max_s is not None else retry_interval_s
        self.min_signal = min_signal
        self.max_items = max_items
        self.urgent_blind_s = urgent_blind_s    # R-26 (owner delegation): see process()
        self.last_attempt = None
        self.path = path
        self.items = []          # dicts: {uplink, attempts}
        self.next_seq = 0
        self.next_session = None  # earliest time for the next modem activity
        self.fails = 0           # consecutive failures (routine back-off)
        self.evicted = []        # (time, Uplink) routine messages dropped for room
        self.load_error = None
        self.refresh = None      # optional fn(uplink, now) -> uplink with live readings updated (D-21)
        # counters for the battery/credit report
        self.signal_checks = 0
        self.attempts = 0
        self.successes = 0
        if path and os.path.exists(path):
            self._load()

    URGENT = URGENT

    def __len__(self):
        return len(self.items)

    def has_pending(self, msg_type):
        return any(i["uplink"].msg_type == msg_type for i in self.items)

    def has_urgent(self):
        return any(i["uplink"].msg_type in URGENT for i in self.items)

    def take_seq(self):
        s = self.next_seq
        self.next_seq = (s + 1) & 0xFFFF
        return s

    def put(self, uplink, now):
        if uplink.msg_type == P.HEARTBEAT:
            self.items = [i for i in self.items if i["uplink"].msg_type != P.HEARTBEAT]
        self.items.append({"uplink": uplink, "attempts": 0})
        while len(self.items) > self.max_items:
            routine = [i for i in self.items if i["uplink"].msg_type not in URGENT]
            if not routine:
                break                                   # never drop urgent
            victim = min(routine, key=self._order)
            self.items.remove(victim)
            self.evicted.append((now, victim["uplink"]))
        if uplink.msg_type in URGENT or self.next_session is None:
            self.next_session = now if self.next_session is None else min(self.next_session, now)
            if uplink.msg_type in URGENT:
                self.fails = 0
        self._save()

    def drop(self, msg_type):
        """Remove unsent messages of one type (R-20: a cancel supersedes queued ALERTs)."""
        gone = [i["uplink"] for i in self.items if i["uplink"].msg_type == msg_type]
        self.items = [i for i in self.items if i["uplink"].msg_type != msg_type]
        if gone:
            self._save()
        return gone

    def _order(self, item):
        u = item["uplink"]
        return (0 if u.msg_type in URGENT else 1, u.event_time, u.seq)

    def process(self, now, link, events=None):
        """At most one modem session per call. Returns (uplink, arrival_time) or None."""
        if not self.items or (self.next_session is not None and now < self.next_session):
            return None
        urgent = self.has_urgent()
        if urgent and self.urgent_blind_s and hasattr(link, "signal"):
            # Urgent and the signal reads 0: check cheaply each retry, but still make a
            # full attempt at least every urgent_blind_s. Never fully held back.
            self.signal_checks += 1
            bars = link.signal(now)
            overdue = self.last_attempt is None or now - self.last_attempt >= self.urgent_blind_s
            if bars == 0 and not overdue:
                self._fail(now, urgent)
                if events is not None:
                    events.append((now, "signal_low", bars))
                return None
        elif not urgent and self.min_signal > 0:
            self.signal_checks += 1
            bars = link.signal(now) if hasattr(link, "signal") else 5
            if bars < self.min_signal:
                self._fail(now, urgent)
                if events is not None:
                    events.append((now, "signal_low", bars))
                return None
        item = min(self.items, key=self._order)
        u = item["uplink"]
        flags = u.flags | (P.F_RETRANSMISSION if item["attempts"] > 0 else 0)
        u = u.copy(send_time=now, flags=flags)
        if self.refresh is not None:
            u = self.refresh(u, now)
        item["attempts"] += 1
        self.attempts += 1
        self.last_attempt = now
        ok, arrival = link.attempt_uplink(now, u.to_bytes())
        if events is not None:
            events.append((now, "uplink_attempt", u, ok, item["attempts"]))
        if ok:
            self.successes += 1
            self.items.remove(item)
            self.fails = 0
            self.next_session = now          # the next one may go straight away
            self._save()
            return u, arrival
        self._fail(now, urgent)
        self._save()
        return None

    def _fail(self, now, urgent):
        self.fails += 1
        if urgent:
            wait = self.retry_interval_s
        else:
            wait = min(self.backoff_max_s, self.retry_interval_s * 2 ** (self.fails - 1))
        self.next_session = now + wait

    # --- persistence ---
    def _save(self):
        if not self.path:
            return
        data = {"version": 2, "next_seq": self.next_seq, "next_session": self.next_session,
                "fails": self.fails,
                "items": [{"hex": i["uplink"].to_bytes().hex(), "attempts": i["attempts"]}
                          for i in self.items]}
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def _load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
            if isinstance(data, list):                  # version 1 (M1-M3): list of items
                data = {"items": data}
            items = [{"uplink": P.Uplink.from_bytes(bytes.fromhex(d["hex"])),
                      "attempts": int(d.get("attempts", 0))} for d in data["items"]]
        except (OSError, ValueError, KeyError, TypeError, P.PacketError) as e:
            # Don't trust a damaged file; keep it for inspection and start empty.
            self.load_error = str(e)
            os.replace(self.path, self.path + ".damaged")
            return
        self.items = items
        top = max((i["uplink"].seq for i in items), default=-1)
        self.next_seq = max(int(data.get("next_seq", 0)), (top + 1) & 0xFFFF)
        self.next_session = data.get("next_session")
        self.fails = int(data.get("fails", 0))
