"""Wire format v1 — see docs/01-PACKET-SPEC.md.

Research demonstrator — not a medical device.

Fixed 50-byte uplink (band -> base) and 16-byte downlink (base -> band),
big-endian, CRC-16/CCITT-FALSE trailer.
"""
import binascii
import struct
from dataclasses import dataclass, field, fields, replace
from typing import List

VERSION = 1

# --- uplink message types (docs/01 §5) ---
ALERT = 0x01
CONTACT_INFO = 0x02
STAND_DOWN = 0x03
RESOLVED = 0x04
HEARTBEAT = 0x05
SYSTEMIC_ONLY_INFO = 0x06
SENSOR_EXPIRED = 0x07
CANCELLED_LOCAL = 0x08

UPLINK_NAMES = {
    ALERT: "ALERT", CONTACT_INFO: "CONTACT_INFO", STAND_DOWN: "STAND_DOWN",
    RESOLVED: "RESOLVED", HEARTBEAT: "HEARTBEAT",
    SYSTEMIC_ONLY_INFO: "SYSTEMIC_ONLY_INFO", SENSOR_EXPIRED: "SENSOR_EXPIRED",
    CANCELLED_LOCAL: "CANCELLED_LOCAL",
}

# --- downlink message types ---
DL_ACK = 0x80
DL_RESPONDER_STATUS = 0x81
DL_RESOLVE = 0x82
DOWNLINK_NAMES = {DL_ACK: "ACK", DL_RESPONDER_STATUS: "RESPONDER_STATUS", DL_RESOLVE: "RESOLVE"}

# --- flags (byte 17) ---
F_LOCAL_POSITIVE = 1 << 0
F_SYSTEMIC_POSITIVE = 1 << 1
F_SIMULATED = 1 << 2
F_TRAINER_HARDWARE = 1 << 3
F_RETRANSMISSION = 1 << 4
F_GPS_VALID = 1 << 5
F_BATTERY_LOW = 1 << 6
F_SENSOR_EXPIRED = 1 << 7

# --- family mask (byte 18) ---
FAMILIES = ("3FTx", "PLA2", "SVMP", "SVSP")
FM_3FTX, FM_PLA2, FM_SVMP, FM_SVSP = 1, 2, 4, 8
FM_UNCLASSIFIED = 1 << 4
FM_TEST_INVALID = 1 << 5

LEVEL_NAMES = {0: "none", 1: "trace", 2: "low", 3: "moderate", 4: "high", 255: "not measured"}

# --- local source (byte 23) ---
SRC_NONE, SRC_LATERAL_FLOW, SRC_ISF, SRC_MANUAL = 0, 1, 2, 3

# --- escalation reason (byte 24) ---
R_ISF_RISE = 1 << 0
R_SPO2_FALL = 1 << 1
R_RR_RISE = 1 << 2
R_HR_TREND = 1 << 3
R_LOCAL_DANGER = 1 << 4      # R-01: strong local signal held past the danger timer
SYSTEMIC_REASONS = R_ISF_RISE | R_SPO2_FALL | R_RR_RISE | R_HR_TREND
REASON_NAMES = {R_ISF_RISE: "isf_rise", R_SPO2_FALL: "spo2_fall", R_RR_RISE: "rr_rise",
                R_HR_TREND: "hr_trend", R_LOCAL_DANGER: "local_danger"}

# --- "not available" sentinels ---
NA_LATLON = 0x7FFFFFFF
NA_U16 = 0xFFFF
NA_U8 = 0xFF
NA_I8 = -128
NA_I16 = -32768
NA_LEVEL = 255

_UPLINK_BODY = struct.Struct(">BBIHIIBBB4BBBiiHBBBBbbhbBHB")   # 48 bytes
_DOWNLINK_BODY = struct.Struct(">BBIHIBB")                    # 14 bytes
_CRC = struct.Struct(">H")
UPLINK_SIZE = _UPLINK_BODY.size + _CRC.size                   # 50
DOWNLINK_SIZE = _DOWNLINK_BODY.size + _CRC.size               # 16


class PacketError(ValueError):
    pass


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF). Check value for b'123456789' is 0x29B1."""
    return binascii.crc_hqx(data, 0xFFFF)


def clamp_i8(v):
    """Clamp to int8 range, keeping -128 reserved for 'not available'."""
    if v is None:
        return NA_I8
    return max(-127, min(127, int(round(v))))


def bits_to_names(mask: int, names: dict) -> List[str]:
    return [n for b, n in names.items() if mask & b]


@dataclass
class Uplink:
    msg_type: int
    device_id: int
    seq: int
    event_time: int
    send_time: int
    state: int
    flags: int = F_SIMULATED | F_TRAINER_HARDWARE
    family_mask: int = 0
    family_level: List[int] = field(default_factory=lambda: [NA_LEVEL] * 4)
    local_source: int = SRC_NONE
    escalation_reason: int = 0
    lat: int = NA_LATLON
    lon: int = NA_LATLON
    fix_age: int = NA_U16
    hdop: int = NA_U8
    heart_rate: int = 0
    spo2: int = 0
    resp_rate: int = 0
    spo2_slope: int = NA_I8
    rr_slope: int = NA_I8
    skin_temp: int = NA_I16
    isf_trend: int = NA_I8
    battery: int = NA_U8
    sensor_age: int = NA_U16
    wear_site: int = NA_U8
    version: int = VERSION

    def to_bytes(self) -> bytes:
        if len(self.family_level) != 4:
            raise PacketError("family_level must have 4 entries")
        try:
            body = _UPLINK_BODY.pack(
                self.version, self.msg_type, self.device_id, self.seq,
                self.event_time, self.send_time, self.state, self.flags,
                self.family_mask, *self.family_level, self.local_source,
                self.escalation_reason, self.lat, self.lon, self.fix_age,
                self.hdop, self.heart_rate, self.spo2, self.resp_rate,
                self.spo2_slope, self.rr_slope, self.skin_temp, self.isf_trend,
                self.battery, self.sensor_age, self.wear_site)
        except struct.error as e:
            raise PacketError("field out of range: %s" % e)
        return body + _CRC.pack(crc16(body))

    @classmethod
    def from_bytes(cls, data: bytes) -> "Uplink":
        if len(data) != UPLINK_SIZE:
            raise PacketError("uplink must be %d bytes, got %d" % (UPLINK_SIZE, len(data)))
        body, (crc,) = data[:-2], _CRC.unpack(data[-2:])
        if crc16(body) != crc:
            raise PacketError("CRC mismatch")
        v = _UPLINK_BODY.unpack(body)
        if v[0] != VERSION:
            raise PacketError("unsupported version %d" % v[0])
        return cls(version=v[0], msg_type=v[1], device_id=v[2], seq=v[3],
                   event_time=v[4], send_time=v[5], state=v[6], flags=v[7],
                   family_mask=v[8], family_level=list(v[9:13]), local_source=v[13],
                   escalation_reason=v[14], lat=v[15], lon=v[16], fix_age=v[17],
                   hdop=v[18], heart_rate=v[19], spo2=v[20], resp_rate=v[21],
                   spo2_slope=v[22], rr_slope=v[23], skin_temp=v[24], isf_trend=v[25],
                   battery=v[26], sensor_age=v[27], wear_site=v[28])

    def copy(self, **changes) -> "Uplink":
        return replace(self, family_level=list(self.family_level), **changes)

    # --- readable helpers (used by CLI and dashboard) ---
    @property
    def type_name(self):
        return UPLINK_NAMES.get(self.msg_type, "0x%02X" % self.msg_type)

    @property
    def families(self):
        return [f for i, f in enumerate(FAMILIES) if self.family_mask & (1 << i)]

    @property
    def reasons(self):
        return bits_to_names(self.escalation_reason, REASON_NAMES)

    @property
    def lat_deg(self):
        return None if self.lat == NA_LATLON else self.lat / 1e7

    @property
    def lon_deg(self):
        return None if self.lon == NA_LATLON else self.lon / 1e7

    def as_dict(self):
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d.update(type_name=self.type_name, families=self.families, reasons=self.reasons,
                 lat_deg=self.lat_deg, lon_deg=self.lon_deg)
        return d


@dataclass
class Downlink:
    msg_type: int
    device_id: int
    ack_seq: int
    base_time: int
    responder_status: int = 0
    eta_min: int = NA_U8
    version: int = VERSION

    def to_bytes(self) -> bytes:
        try:
            body = _DOWNLINK_BODY.pack(self.version, self.msg_type, self.device_id,
                                       self.ack_seq, self.base_time,
                                       self.responder_status, self.eta_min)
        except struct.error as e:
            raise PacketError("field out of range: %s" % e)
        return body + _CRC.pack(crc16(body))

    @classmethod
    def from_bytes(cls, data: bytes) -> "Downlink":
        if len(data) != DOWNLINK_SIZE:
            raise PacketError("downlink must be %d bytes, got %d" % (DOWNLINK_SIZE, len(data)))
        body, (crc,) = data[:-2], _CRC.unpack(data[-2:])
        if crc16(body) != crc:
            raise PacketError("CRC mismatch")
        v = _DOWNLINK_BODY.unpack(body)
        if v[0] != VERSION:
            raise PacketError("unsupported version %d" % v[0])
        return cls(version=v[0], msg_type=v[1], device_id=v[2], ack_seq=v[3],
                   base_time=v[4], responder_status=v[5], eta_min=v[6])

    @property
    def type_name(self):
        return DOWNLINK_NAMES.get(self.msg_type, "0x%02X" % self.msg_type)
