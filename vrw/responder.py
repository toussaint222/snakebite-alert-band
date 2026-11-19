"""Simulated human responder for the M4 field simulation.

Research demonstrator — not a medical device.

A person at base decides to go (decision delay), drives to the nearest
trailhead, then walks to the wearer's most recently REPORTED position (from
the band's own messages, never the true position). If that fix is old or
poor, they also search. On arrival they are "on scene" and the base closes
the alert. The model stops there: it never models giving anything to anyone.

Drone doctrine (README, FIELD-RUNBOOK): a drone may carry the kit to a
clearing or to the responder; it never descends through canopy and never
treats anyone. v1 models no drone.

Every number here comes from the scenario's "responder" block and is a
PLACEHOLDER (R-28). Distances are straight lines times a winding factor.
"""
import math

from . import packet as P

EARTH_KM = 6371.0088


def km(a, b):
    """Great-circle distance between (lat, lon) pairs in km."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(h))


class Responder:
    STATUS = {"dispatched": 1, "en_route": 2, "on_scene": 3}

    def __init__(self, cfg, base_pos, start):
        self.cfg = cfg
        self.base_pos = (base_pos["lat"], base_pos["lon"])
        self.trailhead = (cfg["trailhead"]["lat"], cfg["trailhead"]["lon"])
        self.start = start
        self.phase = "waiting"        # waiting -> deciding -> driving -> on_foot -> on_scene
        self.times = {}               # milestone -> absolute time
        self.latest_fix = None        # (lat, lon, fix_age_s, hdop, send_time) from the band's messages
        self.cancelled = False
        self.target = None
        self.foot_km = self.drive_km = None
        self.search_s = 0
        self.t_next = None

    def observe(self, arrival, u):
        """Called with each uplink the base accepted."""
        # fix_age is counted back from send_time, so the newest SEND has the newest fix
        if u.lat_deg is not None and (u.flags & P.F_GPS_VALID) and \
                (self.latest_fix is None or u.send_time >= self.latest_fix[4]):
            fa = None if u.fix_age == P.NA_U16 else u.fix_age
            hd = None if u.hdop == P.NA_U8 else u.hdop / 10.0
            self.latest_fix = (u.lat_deg, u.lon_deg, fa, hd, u.send_time)
        if u.msg_type == P.CANCELLED_LOCAL and self.phase == "waiting":
            self.cancelled = True
        if u.msg_type == P.ALERT and self.phase == "waiting" and not self.cancelled:
            self.times["alert_at_base"] = arrival
            self.phase = "deciding"
            self.t_next = arrival + self.cfg["decision_delay_s"]

    def step(self, now):
        """Advance; returns a list of (milestone, eta_min or None) that just happened."""
        out = []
        if self.phase == "deciding" and now >= self.t_next:
            self.times["departed"] = now
            self.drive_km = km(self.base_pos, self.trailhead) * self.cfg.get("winding", 1.3)
            drive_s = self.drive_km / self.cfg["vehicle_kmh"] * 3600
            self.phase, self.t_next = "driving", now + drive_s
            out.append(("dispatched", self._eta(now)))
        if self.phase == "driving" and now >= self.t_next:
            self.times.setdefault("at_trailhead", now)
            if self.latest_fix is None:
                return out                # no position reported yet: wait at the trailhead
            lat, lon, age, hdop, sent = self.latest_fix
            self.target = (lat, lon)
            self.search_s = self._search(now)
            self.fix_used = {"lat": lat, "lon": lon, "fix_age_s": age, "hdop": hdop, "sent": sent,
                             "search_s": self.search_s}
            self.foot_km = km(self.trailhead, self.target) * self.cfg.get("winding", 1.3)
            walk_s = self.foot_km / self.cfg["foot_kmh"] * 3600 + self.search_s
            self.phase, self.t_next = "on_foot", now + walk_s
            out.append(("en_route", self._eta(now)))
        if self.phase == "on_foot" and now >= self.t_next:
            self.times["on_scene"] = now
            self.phase = "on_scene"
            out.append(("on_scene", 0))
        return out

    def _search(self, now):
        """Search time if the position the responder is going to is old or poor."""
        lat, lon, age, hdop, sent = self.latest_fix
        age_now = (age or 0) + (now - sent)       # age in the message + time since it was sent
        poor = hdop is None or hdop > self.cfg.get("hdop_poor", 5.0)
        return self.cfg["search_s"] if (age_now > self.cfg["fix_old_s"] or poor) else 0

    def _eta(self, now):
        if self.phase == "driving":
            if self.latest_fix is None:
                return None
            walk = km(self.trailhead, self.latest_fix[:2]) * self.cfg.get("winding", 1.3) / self.cfg["foot_kmh"] * 3600
            return int(round((self.t_next - now + walk + self._search(self.t_next)) / 60))
        return int(round((self.t_next - now) / 60))
