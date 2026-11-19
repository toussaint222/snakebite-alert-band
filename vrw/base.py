"""Base-station logic. The M2 dashboard server runs one of these.

Research demonstrator — not a medical device.

Decodes uplinks, rejects anything not flagged simulated + trainer hardware
(D-07), de-duplicates by (device_id, seq), keeps the newest-by-event-time
message per band, decides the payload class for an ALERT, and queues
downlinks (ACK on every ALERT, RESOLVE when a person closes an alert).
Downlinks are collected with take_downlinks(); whoever owns the radio
(the simulator, or later a real modem) sends them.

Payload class (R-01, R-08, R-17):
  FAMILY_MATCHED - escalated with a systemic reason and at least one named family
  BROAD          - escalated on the local danger timer only, or no named family
What each class means for the responder lives in dashboard/checklist.json,
supplied by a toxinologist.
"""
from . import packet as P

TERMINAL = (P.CANCELLED_LOCAL, P.RESOLVED)


def payload_class(u):
    if not (u.escalation_reason & P.SYSTEMIC_REASONS) or not u.families:
        return "BROAD"
    return "FAMILY_MATCHED"


class Base:
    def __init__(self):
        self.received = []        # (arrival_time, Uplink) in arrival order, first copies only
        self.duplicates = 0
        self.rejected = []        # (arrival_time, reason)
        self.seen = set()
        self.bands = {}           # device_id -> newest-by-event-time Uplink
        self.dispatches = []      # (arrival_time, Uplink, payload_class)
        self.stale_alerts = []    # ALERTs that arrived after a newer cancel/resolve (R-20)
        self.cancelled_after_dispatch = []   # (arrival_time, Uplink) (R-18)
        self.resolved_by_base = {}           # device_id -> time a person closed it
        self.outgoing = []        # (time, downlink bytes)
        self.responders = {}      # device_id -> {"status", "eta_min", "time", "lat", "lon"} (M4)

    def receive(self, arrival, data):
        try:
            u = P.Uplink.from_bytes(data)
        except P.PacketError as e:
            self.rejected.append((arrival, str(e)))
            return None
        need = P.F_SIMULATED | P.F_TRAINER_HARDWARE
        if u.flags & need != need:
            self.rejected.append((arrival, "not flagged simulated + trainer (D-07)"))
            return None
        # D-03 (M4): event_time is part of the key. A retry keeps both seq and
        # event_time, so retries still collapse; a band whose seq restarted or
        # wrapped past 65535 does not have new messages thrown away as repeats.
        key = (u.device_id, u.seq, u.event_time)
        if key in self.seen:
            self.duplicates += 1
            return None
        self.seen.add(key)
        self.received.append((arrival, u))
        cur = self.bands.get(u.device_id)
        if cur is None or u.event_time >= cur.event_time:
            self.bands[u.device_id] = u
        if u.msg_type == P.CANCELLED_LOCAL and self.dispatch_for(u.device_id):
            # R-18: only a LOCAL cancel raises the recall question; the band's RESOLVED
            # is just its confirmation of a close the base sent.
            self.cancelled_after_dispatch.append((arrival, u))
        if u.msg_type == P.ALERT:
            closed = any(x.device_id == u.device_id and x.msg_type in TERMINAL
                         and x.event_time >= u.event_time for _, x in self.received[:-1])
            if closed:
                self.stale_alerts.append((arrival, u))
            elif not self.dispatch_for(u.device_id):
                self.dispatches.append((arrival, u, payload_class(u)))
            self.outgoing.append((arrival, P.Downlink(
                P.DL_ACK, u.device_id, u.seq, int(arrival), responder_status=1).to_bytes()))
        return u

    def dispatch_for(self, device_id):
        return next((d for d in self.dispatches if d[1].device_id == device_id), None)

    def resolve(self, now, device_id):
        last = max((u.seq for _, u in self.received if u.device_id == device_id), default=0)
        self.resolved_by_base[device_id] = now
        self.outgoing.append((now, P.Downlink(
            P.DL_RESOLVE, device_id, last, int(now), responder_status=3).to_bytes()))

    def responder_update(self, now, device_id, status, eta_min=None, lat=None, lon=None):
        """A person at base reports the responder's progress; the band is told (RESPONDER_STATUS)."""
        code = {"dispatched": 1, "en_route": 2, "on_scene": 3}[status]
        self.responders[device_id] = {"status": status, "eta_min": eta_min, "time": now,
                                      "lat": lat, "lon": lon}
        last = max((u.seq for _, u in self.received if u.device_id == device_id), default=0)
        eta = P.NA_U8 if eta_min is None else max(0, min(254, int(eta_min)))
        self.outgoing.append((now, P.Downlink(P.DL_RESPONDER_STATUS, device_id, last, int(now),
                                              responder_status=code, eta_min=eta).to_bytes()))

    def take_downlinks(self):
        out, self.outgoing = self.outgoing, []
        return out
