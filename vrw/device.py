"""The simulated band: trigger machine + context (GPS, battery, sensor) + outbox.

Research demonstrator — not a medical device.
"""
import json
import os

from . import packet as P
from .outbox import Outbox
from .trigger import TriggerMachine


class Device:
    def __init__(self, device_id, thresholds, wear_site=0, outbox_path=None):
        self.device_id = device_id
        self.t = thresholds
        self.machine = TriggerMachine(thresholds)
        self.outbox = Outbox(thresholds["retry_interval_s"], outbox_path,
                             backoff_max_s=thresholds["retry_backoff_max_s"],
                             min_signal=thresholds["link_min_signal"],
                             max_items=thresholds["queue_max"],
                             urgent_blind_s=thresholds["urgent_blind_attempt_s"])
        self.alarm_on = False           # R-27: local buzzer + light (simulated)
        self.alarms = []                # (time, "on"/"off")
        self.outbox.refresh = self.refresh
        # R-25: the trigger's watch/alert facts live next to the queue in flash
        self.state_path = None if outbox_path is None else \
            os.path.join(os.path.dirname(outbox_path), "trigger.json")
        self._saved = None
        self.restored = False
        if self.state_path and os.path.exists(self.state_path):
            try:
                with open(self.state_path) as f:
                    snap = json.load(f)
                self.pending_restore = snap
            except (OSError, ValueError):
                os.replace(self.state_path, self.state_path + ".damaged")
                self.pending_restore = None
        else:
            self.pending_restore = None
        self.wear_site = wear_site
        self.last_enqueued = None
        self.enqueued = []          # (time, Uplink) as first created
        self.superseded = []        # (time, Uplink) queued ALERTs dropped by a cancel/resolve
        # context
        self.fix = None             # (lat, lon, hdop)
        self.fix_time = None
        self.battery = None
        self.sensor_applied = None
        self.vitals_latest = {}

    def set_fix(self, now, lat, lon, hdop=1.0):
        self.fix, self.fix_time = (lat, lon, hdop), now

    def resume(self, now):
        """Apply a saved trigger snapshot after a power cycle (R-25)."""
        if self.pending_restore is not None:
            self.restored = self.machine.restore(self.pending_restore, now)
            self.pending_restore = None
            self._save_state()

    def _save_state(self):
        if not self.state_path:
            return
        snap = self.machine.snapshot()
        if snap == self._saved:
            return
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(snap, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.state_path)
        self._saved = snap

    def step(self, now, lfa=None, isf=None, vitals=None, action=None, sensor_life_s=None):
        if self.pending_restore is not None:
            self.resume(now)
        if vitals:
            self.vitals_latest = vitals
        if self.last_enqueued is None:
            self.last_enqueued = now
        age = None if self.sensor_applied is None else now - self.sensor_applied
        types = self.machine.update(now, lfa=lfa, isf=isf, vitals=vitals, action=action,
                                    sensor_age_s=age, sensor_life_s=sensor_life_s)
        if not types and now - self.last_enqueued >= self.t["heartbeat_s"]:
            types = [P.HEARTBEAT]
        for mt in types:
            if mt == P.ALERT and self.outbox.has_pending(P.ALERT) and \
                    not self._reason_changed():
                continue            # an ALERT is already waiting for the sky; don't pile up
            self._enqueue(now, mt)
        self._save_state()
        self._check_alarm(now)

    def _check_alarm(self, now):
        """R-27: an urgent message stuck in the queue sets off the local alarm, so the
        wearer's companions know to move to open sky. It stops once the queue has no
        urgent message left."""
        urgent = [i["uplink"] for i in self.outbox.items if i["uplink"].msg_type in self.outbox.URGENT]
        stuck = bool(urgent) and now - min(u.event_time for u in urgent) >= self.t["stuck_alarm_s"]
        if stuck != self.alarm_on:
            self.alarm_on = stuck
            self.alarms.append((now, "on" if stuck else "off"))

    def _reason_changed(self):
        last = next((u for _, u in reversed(self.enqueued) if u.msg_type == P.ALERT), None)
        return last is None or last.escalation_reason != self.machine.reason

    def on_downlink(self, now, data):
        dl = P.Downlink.from_bytes(data)
        if dl.device_id != self.device_id:
            return dl
        for mt in self.machine.on_downlink(now, dl):
            self._enqueue(now, mt)
        self._save_state()
        return dl

    def _enqueue(self, now, mt):
        if mt in (P.CANCELLED_LOCAL, P.RESOLVED):
            # R-20: an alert that never left the band must not reach the base after
            # it was cancelled/resolved. The cancel message still carries the
            # families and escalation reasons, so the base learns it had escalated.
            for u in self.outbox.drop(P.ALERT):
                self.superseded.append((now, u))
        u = self.build(now, mt, self.outbox.take_seq())
        self.outbox.put(u, now)
        self.enqueued.append((now, u))
        self.last_enqueued = now

    POSITION = ("lat", "lon", "fix_age", "hdop")
    VITALS = ("heart_rate", "spo2", "resp_rate", "spo2_slope", "rr_slope", "skin_temp", "isf_trend")

    def refresh(self, u, now):
        """D-21: a message that waited in the queue goes out with current readings.

        Each group is refreshed only if the band has a current reading for it
        (after a power cycle it may have none yet). Otherwise the queued values
        are kept, and fix_age is aged to the moment of sending. Type, seq,
        event_time, state, families, reasons and the other flags never change."""
        live = self.build(now, u.msg_type, u.seq)
        ch, flags = {}, u.flags
        if self.fix is not None:
            ch.update({f: getattr(live, f) for f in self.POSITION})
            flags = (flags & ~P.F_GPS_VALID) | (live.flags & P.F_GPS_VALID)
        elif u.fix_age != P.NA_U16:
            ch["fix_age"] = min(65534, u.fix_age + max(0, int(now - u.event_time)))
        if self.vitals_latest:
            ch.update({f: getattr(live, f) for f in self.VITALS})
        if self.battery is not None:
            ch["battery"] = live.battery
            flags = (flags & ~P.F_BATTERY_LOW) | (live.flags & P.F_BATTERY_LOW)
        if self.sensor_applied is not None:
            ch["sensor_age"] = live.sensor_age
        return u.copy(flags=flags, **ch)

    @property
    def seq(self):
        """Next sequence number; kept in the outbox file so it survives a power cycle (R-25)."""
        return self.outbox.next_seq

    def build(self, now, mt, seq=None):
        m = self.machine
        flags = P.F_SIMULATED | P.F_TRAINER_HARDWARE
        if m.local_positive():
            flags |= P.F_LOCAL_POSITIVE
        if m.reason & P.SYSTEMIC_REASONS:
            flags |= P.F_SYSTEMIC_POSITIVE
        if m.sensor_expired:
            flags |= P.F_SENSOR_EXPIRED
        if self.battery is not None and self.battery < self.t["battery_low_pct"]:
            flags |= P.F_BATTERY_LOW
        lat = lon = P.NA_LATLON
        fix_age, hdop = P.NA_U16, P.NA_U8
        if self.fix:
            flags |= P.F_GPS_VALID
            lat, lon = int(round(self.fix[0] * 1e7)), int(round(self.fix[1] * 1e7))
            fix_age = min(int(now - self.fix_time), 65534)
            hdop = min(int(round(self.fix[2] * 10)), 254)
        v = self.vitals_latest
        skin = v.get("skin_temp")
        return P.Uplink(
            msg_type=mt, device_id=self.device_id, seq=self.seq if seq is None else seq,
            event_time=int(now), send_time=int(now), state=int(m.state), flags=flags,
            family_mask=m.family_mask(), family_level=m.family_level_bytes(),
            local_source=m.local_source, escalation_reason=m.reason,
            lat=lat, lon=lon, fix_age=fix_age, hdop=hdop,
            heart_rate=int(round(v.get("hr") or 0)), spo2=int(round(v.get("spo2") or 0)),
            resp_rate=int(round(v.get("rr") or 0)),
            spo2_slope=P.clamp_i8(m.spo2_slope(now)), rr_slope=P.clamp_i8(m.rr_slope(now)),
            skin_temp=P.NA_I16 if skin is None else int(round(skin * 100)),
            isf_trend=P.clamp_i8(m.isf_trend(now)),
            battery=P.NA_U8 if self.battery is None else max(0, min(100, int(self.battery))),
            sensor_age=P.NA_U16 if self.sensor_applied is None
            else min(int((now - self.sensor_applied) // 60), 65534),
            wear_site=self.wear_site,
        )
