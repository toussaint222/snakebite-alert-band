"""Trigger state machine — see docs/02-TRIGGER-STATE-MACHINE.md.

Research demonstrator — not a medical device.

This is the ONLY place that decides escalation. It applies the two-signal
rule (confirmed local signal AND systemic signal) plus the owner's R-01
amendment (strong local signal held past the danger timer). Every number
comes from thresholds.json; nothing is hard-coded here.

The machine does not build packets or talk to the link. `update()` returns
a list of message types the device should send.
"""
import json
import os
from collections import deque
from enum import IntEnum

from . import packet as P

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_THRESHOLDS = os.path.join(HERE, "thresholds.json")


class State(IntEnum):
    IDLE = 0
    CONTACT = 1
    SYSTEMIC_WATCH = 2
    ESCALATED = 3
    RESOLVED = 4
    STOOD_DOWN = 5
    SYSTEMIC_ONLY = 6


# Transitions that may ever happen. Anything else is a bug (checked in tests).
ALLOWED = {
    (State.IDLE, State.CONTACT), (State.IDLE, State.SYSTEMIC_ONLY),
    (State.CONTACT, State.SYSTEMIC_WATCH), (State.CONTACT, State.IDLE),
    (State.CONTACT, State.RESOLVED),
    (State.SYSTEMIC_WATCH, State.ESCALATED), (State.SYSTEMIC_WATCH, State.STOOD_DOWN),
    (State.SYSTEMIC_WATCH, State.RESOLVED),
    (State.ESCALATED, State.RESOLVED),
    (State.SYSTEMIC_ONLY, State.CONTACT), (State.SYSTEMIC_ONLY, State.IDLE),
    (State.SYSTEMIC_ONLY, State.RESOLVED),
    (State.STOOD_DOWN, State.IDLE), (State.RESOLVED, State.IDLE),
}


def load_thresholds(path=DEFAULT_THRESHOLDS, overrides=None):
    with open(path) as f:
        raw = json.load(f)
    t = {k: v["value"] for k, v in raw.items() if not k.startswith("_")}
    if overrides:
        unknown = set(overrides) - set(t)
        if unknown:
            raise KeyError("unknown thresholds: %s" % sorted(unknown))
        t.update(overrides)
    return t


class TriggerMachine:
    def __init__(self, thresholds=None):
        self.t = thresholds or load_thresholds()
        self.state = State.IDLE
        self.state_since = None
        self.log = []                    # (time, from, to, why)

        self.lfa_levels = [0, 0, 0, 0]   # latest valid lateral-flow read
        self.lfa_unclassified = False
        self.test_invalid = False
        self.isf_levels = [0, 0, 0, 0]   # latest ISF read
        self.isf_seen = False
        self.isf_history = deque()       # (t, max level)
        self.isf_pos_reads = []          # times of positive ISF reads during CONTACT
        self.local_source = P.SRC_NONE
        self.vitals = deque()            # (t, spo2, rr, hr)
        self.skin_temp = None

        self.contact_since = None
        self.confirmed_at = None
        self.strong_since = None
        self.systemic_clear_since = None
        self.reason = 0
        self.sensor_expired = False
        self.alert_acked = False
        self.responder = None            # (status, eta_min, time) from the last RESPONDER_STATUS
        self.last_alert_at = None

    # ------------------------------------------------------------ power-cycle memory (R-25)
    # Only these states are resumed after a restart; anything else restarts in IDLE.
    RESUMABLE = None   # set after class body (needs State)
    DURABLE = ("state_since", "contact_since", "confirmed_at", "strong_since", "reason",
               "sensor_expired", "alert_acked", "last_alert_at", "lfa_levels", "lfa_unclassified",
               "test_invalid", "local_source", "isf_levels", "isf_seen", "isf_history")

    def snapshot(self):
        """What the band writes to flash: the facts a watch or an alert depends on,
        including the ISF levels and their recent history (so a rise across the
        outage still counts). Vitals history is not kept; it is re-measured."""
        if self.state not in (State.SYSTEMIC_WATCH, State.ESCALATED):
            return {"state": int(State.IDLE)}
        d = {k: getattr(self, k) for k in self.DURABLE}
        d["isf_history"] = [list(x) for x in self.isf_history]
        d["state"] = int(self.state)
        return d

    def restore(self, d, now):
        """Resume after a power cycle. Not a state transition: the band never left this state."""
        st = State(d.get("state", 0))
        if st not in (State.SYSTEMIC_WATCH, State.ESCALATED):
            return False
        for k in self.DURABLE:
            if k in d:
                setattr(self, k, list(d[k]) if isinstance(d[k], list) else d[k])
        self.isf_history = deque(tuple(x) for x in d.get("isf_history", []))
        self.state = st
        self.log.append((now, st, st, "power cycle: resumed %s from flash (R-25)" % st.name))
        return True

    # ------------------------------------------------------------ inputs
    def _set(self, now, new, why):
        if (self.state, new) not in ALLOWED:
            raise AssertionError("illegal transition %s -> %s" % (self.state.name, new.name))
        self.log.append((now, self.state, new, why))
        self.state, self.state_since = new, now

    def local_levels(self):
        return [max(a, b) for a, b in zip(self.lfa_levels, self.isf_levels)]

    def local_positive(self):
        return max(self.local_levels()) >= 1 or self.lfa_unclassified

    def _ingest(self, now, lfa, isf, vitals):
        new_positive = False
        lfa_confirms = False
        if lfa is not None:
            if not lfa.get("control_ok", True):
                self.test_invalid = True          # invalid test: never counts
            else:
                self.test_invalid = False
                self.lfa_levels = [int(lfa.get("levels", {}).get(f, 0)) for f in P.FAMILIES]
                self.lfa_unclassified = bool(lfa.get("unclassified", False))
                if max(self.lfa_levels) >= 1 or self.lfa_unclassified:
                    new_positive = lfa_confirms = True
                    self.local_source = P.SRC_LATERAL_FLOW
        if isf is not None:
            self.isf_seen = True
            self.isf_levels = [int(isf.get(f, 0)) for f in P.FAMILIES]
            m = max(self.isf_levels)
            self.isf_history.append((now, m))
            while self.isf_history and self.isf_history[0][0] < now - 2 * self.t["isf_rise_window_s"]:
                self.isf_history.popleft()
            if m >= 1:
                new_positive = True
                self.isf_pos_reads.append(now)
                if self.local_source == P.SRC_NONE:
                    self.local_source = P.SRC_ISF
        if vitals is not None:
            self.vitals.append((now, vitals.get("spo2"), vitals.get("rr"), vitals.get("hr")))
            if vitals.get("skin_temp") is not None:
                self.skin_temp = vitals["skin_temp"]
            while self.vitals and self.vitals[0][0] < now - 3600:
                self.vitals.popleft()
        return new_positive, lfa_confirms

    # ------------------------------------------------------------ signals
    def _series(self, idx):
        return [(t, v[idx - 1]) for (t, *v) in self.vitals if v[idx - 1] is not None]

    @staticmethod
    def _slope_per_10min(series, now):
        """Change per 10 min, from the newest sample back to the sample nearest 10 min earlier."""
        if len(series) < 2:
            return None
        t1, v1 = series[-1]
        older = [(t, v) for t, v in series if t <= now - 540]
        if not older:
            return None
        t0, v0 = older[-1]
        if t1 == t0:
            return None
        return (v1 - v0) * 600.0 / (t1 - t0)

    def _sustained(self, series, now, hold_s, test):
        window = [(t, v) for t, v in series if t >= now - hold_s]
        if not window or window[0][0] > now - hold_s + 60:
            return False              # not enough history to say it has held
        # R-24: a gap in readings inside the window means we don't know it held
        times = [t for t, _ in window] + [now]
        if any(b - a > self.t["vitals_max_gap_s"] for a, b in zip(times, times[1:])):
            return False
        return all(test(v) for _, v in window)

    def spo2_slope(self, now):
        return self._slope_per_10min(self._series(1), now)

    def rr_slope(self, now):
        return self._slope_per_10min(self._series(2), now)

    def isf_trend(self, now):
        """Rise in the highest ISF level over the rise window.

        R-19: only reads taken AT OR AFTER local confirmation count. Otherwise
        a single ISF sensor going 0 -> 1 would supply both the local signal
        (positive read) and the systemic signal (rise) by itself, breaking the
        two-signal rule.
        """
        if not self.isf_history:
            return None
        start = now - self.t["isf_rise_window_s"]
        if self.confirmed_at is not None:
            start = max(start, self.confirmed_at)
        window = [m for t, m in self.isf_history if t >= start]
        if not window:
            return None
        return self.isf_history[-1][1] - min(window)

    def vitals_reasons(self, now):
        bits = 0
        t = self.t
        spo2 = self._series(1)
        s = self._slope_per_10min(spo2, now)
        if s is not None and s <= -t["spo2_fall_per_10min"] and \
                self._sustained(spo2, now, t["spo2_sustain_s"], lambda v: v <= t["spo2_low_pct"]):
            bits |= P.R_SPO2_FALL
        rr = self._series(2)
        s = self._slope_per_10min(rr, now)
        if s is not None and s >= t["rr_rise_per_10min"] and \
                self._sustained(rr, now, t["rr_sustain_s"], lambda v: v >= t["rr_high"]):
            bits |= P.R_RR_RISE
        return bits

    def vitals_out_of_range(self):
        spo2, rr = self._series(1), self._series(2)
        return bool((spo2 and spo2[-1][1] <= self.t["spo2_low_pct"]) or
                    (rr and rr[-1][1] >= self.t["rr_high"]))

    def systemic_reasons(self, now):
        bits = self.vitals_reasons(now)
        trend = self.isf_trend(now)
        if trend is not None and trend >= self.t["isf_rise_bands"] and self.isf_history[-1][1] >= 1:
            bits |= P.R_ISF_RISE
        return bits

    # ------------------------------------------------------------ main step
    def update(self, now, lfa=None, isf=None, vitals=None, action=None, sensor_age_s=None,
               sensor_life_s=None):
        """Advance the machine to time `now`. Returns a list of uplink msg types to send."""
        out = []
        new_positive, lfa_confirms = self._ingest(now, lfa, isf, vitals)
        if self.state_since is None:
            self.state_since = now

        if (sensor_life_s is not None and sensor_age_s is not None
                and sensor_age_s >= sensor_life_s and not self.sensor_expired):
            self.sensor_expired = True
            if self.state in (State.CONTACT, State.SYSTEMIC_WATCH, State.ESCALATED):
                out.append(P.SENSOR_EXPIRED)

        if action == "local_cancel" and self.state in (
                State.CONTACT, State.SYSTEMIC_WATCH, State.ESCALATED, State.SYSTEMIC_ONLY):
            self._set(now, State.RESOLVED, "cancelled by local team")
            out.append(P.CANCELLED_LOCAL)
            return out

        # Up to a few transitions in one step (e.g. IDLE -> CONTACT -> SYSTEMIC_WATCH).
        # New readings are consumed by the first pass; later passes only re-check signals.
        for _ in range(4):
            before = self.state
            self._step(now, new_positive, lfa_confirms, out)
            new_positive = lfa_confirms = False
            if self.state == before or self.state in (State.RESOLVED, State.STOOD_DOWN):
                break
        return out

    def _step(self, now, new_positive, lfa_confirms, out):
        t = self.t
        s = self.state
        if s in (State.IDLE, State.SYSTEMIC_ONLY):
            if new_positive:
                self.contact_since = now
                self.isf_pos_reads = [x for x in self.isf_pos_reads if x >= now - 1]
                self._set(now, State.CONTACT, "local positive")
                if lfa_confirms or self._isf_confirmed(now):
                    self._confirm(now, out)
                return
            if s == State.IDLE:
                bits = self.vitals_reasons(now)
                if bits:
                    self.reason = bits
                    self.systemic_clear_since = None
                    self._set(now, State.SYSTEMIC_ONLY, "systemic signs, no local signal")
                    out.append(P.SYSTEMIC_ONLY_INFO)
            else:
                # Clear on LEVELS back in range, not on the trend stopping: a plateau at a
                # low SpO2 is not "cleared".
                if self.vitals_reasons(now) or self.vitals_out_of_range():
                    self.systemic_clear_since = None
                else:
                    if self.systemic_clear_since is None:
                        self.systemic_clear_since = now
                    if now - self.systemic_clear_since >= t["systemic_only_clear_s"]:
                        self.reason = 0
                        self._set(now, State.IDLE, "systemic signs cleared")
            return

        if s == State.CONTACT:
            if lfa_confirms or self._isf_confirmed(now):
                self._confirm(now, out)
            elif now - self.contact_since > t["local_confirm_window_s"]:
                self._set(now, State.IDLE, "local signal not confirmed")
            return

        if s == State.SYSTEMIC_WATCH:
            bits = self.systemic_reasons(now)
            if bits:
                self.reason = bits
                self._escalate(now, "local confirmed + systemic: %s" % ",".join(
                    P.bits_to_names(bits, P.REASON_NAMES)), out)
                return
            if max(self.local_levels()) >= t["danger_level"]:
                if self.strong_since is None:
                    self.strong_since = now
                if now - self.strong_since >= t["danger_time_s"]:
                    self.reason = P.R_LOCAL_DANGER
                    self._escalate(now, "strong local signal past danger timer (R-01)", out)
                    return
            else:
                self.strong_since = None
            if not self.sensor_expired and now - self.confirmed_at >= t["standdown_s"]:
                self._set(now, State.STOOD_DOWN, "no systemic signal in watch window")
                out.append(P.STAND_DOWN)
            return

        if s == State.ESCALATED:
            bits = self.systemic_reasons(now)
            if bits & ~self.reason:
                self.reason |= bits
                self.last_alert_at = now
                out.append(P.ALERT)          # escalation picture changed: send now
                return
            repeat = t["alert_repeat_acked_s"] if self.alert_acked else t["alert_repeat_unacked_s"]
            if now - self.last_alert_at >= repeat:
                self.last_alert_at = now
                out.append(P.ALERT)

    def _isf_confirmed(self, now):
        reads = [x for x in self.isf_pos_reads if x >= self.contact_since]
        return (len(reads) >= self.t["isf_confirm_reads"]
                and reads[-1] - reads[0] >= self.t["isf_confirm_min_gap_s"]
                and reads[-1] - self.contact_since <= self.t["local_confirm_window_s"])

    def _confirm(self, now, out):
        self.confirmed_at = now
        self.strong_since = None
        self._set(now, State.SYSTEMIC_WATCH, "local signal confirmed")
        out.append(P.CONTACT_INFO)

    def _escalate(self, now, why, out):
        self._set(now, State.ESCALATED, why)
        self.last_alert_at = now
        out.append(P.ALERT)

    # ------------------------------------------------------------ downlink
    def on_downlink(self, now, dl):
        """Apply a decoded Downlink. Returns msg types to send."""
        if dl.msg_type == P.DL_ACK and self.state == State.ESCALATED:
            self.alert_acked = True
        if dl.msg_type == P.DL_RESPONDER_STATUS:
            self.responder = (dl.responder_status, None if dl.eta_min == P.NA_U8 else dl.eta_min, now)
            return []
        if dl.msg_type == P.DL_RESOLVE and self.state == State.ESCALATED:
            self._set(now, State.RESOLVED, "resolved from base")
            return [P.RESOLVED]
        return []

    # ------------------------------------------------------------ snapshot for packets
    def family_mask(self):
        m = 0
        for i, lvl in enumerate(self.local_levels()):
            if lvl >= 1:
                m |= 1 << i
        if self.lfa_unclassified:
            m |= P.FM_UNCLASSIFIED
        if self.test_invalid:
            m |= P.FM_TEST_INVALID
        return m

    def family_level_bytes(self):
        lfa_any = self.local_source == P.SRC_LATERAL_FLOW or any(self.lfa_levels)
        if not (lfa_any or self.isf_seen):
            return [P.NA_LEVEL] * 4
        return self.local_levels()
