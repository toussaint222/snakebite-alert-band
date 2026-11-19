# 01 — Packet specification

> **Research demonstrator — not a medical device.**

Status: **Approved at M0 (2026-11-18); implemented in `vrw/packet.py` (M1); M4 notes on duplicates, live readings and RESPONDER_STATUS.** Version 1 of the wire format (unchanged by M4).

## 1. Link assumptions

| Item | Value used in design | Source / confidence |
|---|---|---|
| Max uplink (device → base) message | 340 bytes | RockBLOCK 9603 documentation, checked 2026-11-18 (D-08). |
| Max downlink (base → device) message | 270 bytes | Same, checked 2026-11-18. |
| Billing unit | 1 credit per 50 bytes or part of 50, sent or received; an empty mailbox check also costs 1 credit | RockBLOCK documentation, checked 2026-11-18. Prices change; check the current price list. |
| Downlink delivery | A message from base reaches the band only during a session the band starts (any send, or a mailbox check) or after a ring alert | Modem behaviour (D-23). **The simulator is optimistic here:** it delivers downlinks whenever the band has sky. |
| Latency, open sky | 10–60 s | From the brief. |
| Canopy | Total loss of link, any duration | From the brief. Treated as normal, not an error. |

**Design target: one alert = 50 bytes = one credit.** That leaves 290 bytes
of headroom under the hard limit for future versions without changing the
modem.

## 2. Encoding rules

- Fixed layout, every field at a fixed offset. No variable-length fields,
  no text, no compression — easy to decode by hand from a hex dump.
- Multi-byte integers are **big-endian** (network byte order).
- "Not available" is an explicit value for every field (listed below), so
  a missing reading is never confused with a zero reading.
- Integrity: **CRC-16/CCITT-FALSE** over bytes 0–47, stored in bytes 48–49.
  (Iridium already checks the link; this catches bugs in our own storage
  and relaying.)
- Times are **UTC seconds since 1970-01-01** (uint32, good until 2106).

## 3. Uplink message — 50 bytes

| Offset | Size | Field | Type | Meaning / units | "Not available" |
|---:|---:|---|---|---|---|
| 0 | 1 | `version` | uint8 | Format version. This spec = `1`. | — |
| 1 | 1 | `msg_type` | uint8 | See §5. | — |
| 2 | 4 | `device_id` | uint32 | Band serial number. | — |
| 6 | 2 | `seq` | uint16 | Increments per *new* message; a retry keeps the same `seq`. Wraps at 65535. | — |
| 8 | 4 | `event_time` | uint32 | When the band decided to send (the state change). Never changes on a retry. | — |
| 12 | 4 | `send_time` | uint32 | When this transmission attempt started. Differs from `event_time` after queuing under canopy. | — |
| 16 | 1 | `state` | uint8 | Trigger state, see [02](02-TRIGGER-STATE-MACHINE.md): 0 IDLE, 1 CONTACT, 2 SYSTEMIC_WATCH, 3 ESCALATED, 4 RESOLVED, 5 STOOD_DOWN, 6 SYSTEMIC_ONLY (R-02). | — |
| 17 | 1 | `flags` | bitmask | b0 local positive · b1 systemic positive · b2 **simulated** · b3 **trainer hardware** · b4 retransmission · b5 GPS fix valid · b6 battery low · b7 sensor expired | — |
| 18 | 1 | `family_mask` | bitmask | b0 3FTx · b1 PLA2 · b2 SVMP · b3 SVSP · b4 positive but unclassified · b5 test invalid (control line failed) · b6–b7 reserved (0) | 0 = none detected |
| 19 | 4 | `family_level[4]` | 4 × uint8 | Semi-quantitative band for 3FTx, PLA2, SVMP, SVSP in that order: 0 none · 1 trace · 2 low · 3 moderate · 4 high | 255 = not measured |
| 23 | 1 | `local_source` | uint8 | Where the local signal came from: 0 none · 1 lateral-flow image · 2 ISF sensor · 3 manual entry (demo) | — |
| 24 | 1 | `escalation_reason` | bitmask | Why it escalated: b0 ISF level rising · b1 SpO2 falling · b2 respiratory-rate rising · b3 heart-rate trend (b0–b3 = systemic) · b4 **local danger timer** (R-01, not systemic) · b5–b7 reserved | 0 = none |
| 25 | 4 | `lat` | int32 | Latitude × 10⁷ (≈1 cm resolution) | 0x7FFFFFFF |
| 29 | 4 | `lon` | int32 | Longitude × 10⁷ | 0x7FFFFFFF |
| 33 | 2 | `fix_age` | uint16 | Seconds from the last GPS fix to `send_time` | 65535 |
| 35 | 1 | `hdop` | uint8 | GPS horizontal dilution × 10 | 255 |
| 36 | 1 | `heart_rate` | uint8 | beats/min | 0 |
| 37 | 1 | `spo2` | uint8 | % | 0 |
| 38 | 1 | `resp_rate` | uint8 | breaths/min | 0 |
| 39 | 1 | `spo2_slope` | int8 | Change in SpO2, % per 10 min | −128 |
| 40 | 1 | `rr_slope` | int8 | Change in resp. rate, breaths/min per 10 min | −128 |
| 41 | 2 | `skin_temp` | int16 | °C × 100 | −32768 |
| 43 | 1 | `isf_trend` | int8 | Change in highest family level, bands per 30 min | −128 |
| 44 | 1 | `battery` | uint8 | % | 255 |
| 45 | 2 | `sensor_age` | uint16 | Minutes since the sensor patch was applied | 65535 |
| 47 | 1 | `wear_site` | uint8 | 0 left ankle · 1 right ankle · 2 left wrist · 3 right wrist | 255 |
| 48 | 2 | `crc16` | uint16 | CRC-16/CCITT-FALSE of bytes 0–47 | — |
| | **50** | **total** | | | |

## 4. Downlink message (base → band) — 16 bytes

Used to acknowledge receipt, to report the responder's progress
(RESPONDER_STATUS with `eta_min`, M4) and to close an alert. Fits easily
under 270.

| Offset | Size | Field | Meaning |
|---:|---:|---|---|
| 0 | 1 | `version` | `1` |
| 1 | 1 | `msg_type` | 0x80 ACK · 0x81 RESPONDER_STATUS · 0x82 RESOLVE (R-07) |
| 2 | 4 | `device_id` | Which band |
| 6 | 2 | `ack_seq` | Highest uplink `seq` received |
| 8 | 4 | `base_time` | Base clock, UTC seconds |
| 12 | 1 | `responder_status` | 0 none · 1 dispatched · 2 en route · 3 on scene |
| 13 | 1 | `eta_min` | Minutes, 255 = unknown |
| 14 | 2 | `crc16` | Over bytes 0–13 |

## 5. Uplink message types

| `msg_type` | Name | Sent when | Dispatches a responder? |
|---:|---|---|---|
| 0x01 | `ALERT` | State enters ESCALATED; again at once if the escalation reasons change; and periodically while ESCALATED (R-15) | **Yes — the only type that does** |
| 0x02 | `CONTACT_INFO` | State enters CONTACT/SYSTEMIC_WATCH (only if R-03 says the band transmits) | No |
| 0x03 | `STAND_DOWN` | Watch window ended with no systemic signal | No |
| 0x04 | `RESOLVED` | Alert closed (R-07) | No |
| 0x05 | `HEARTBEAT` | Periodic "alive" (interval: R-15) | No |
| 0x06 | `SYSTEMIC_ONLY_INFO` | Systemic signal with no local positive (R-02) | No (proposed) |
| 0x07 | `SENSOR_EXPIRED` | Sensor patch past its life during a watch (R-06) | No |
| 0x08 | `CANCELLED_LOCAL` | Local team cancelled on the band — solution on hand (R-01) | No — and stands down any dispatch |

## 6. How the base handles late, repeated and out-of-order messages

Store-and-forward means messages arrive late, twice, or out of order.

- **Duplicates:** a message is identified by (`device_id`, `seq`,
  `event_time`). A retry keeps all three, so the base keeps the first copy
  and ignores the rest (but logs that a retry arrived). Including
  `event_time` means a new message is never thrown away as a repeat when
  `seq` restarts or wraps (M4, D-03). The band also saves `seq` with its
  queue, so a power cycle does not restart it (R-25).
- **Ordering:** the dashboard orders by `event_time`, not arrival time,
  and shows both ("happened 14:02, received 14:39 — delayed 37 min").
- **State wins by time:** the dashboard's current state for a band is the
  state in the message with the newest `event_time`. An `ALERT` is never
  hidden by an older `CONTACT_INFO` arriving late.
- **Cancel wins (R-20):** an `ALERT` whose `event_time` is older than a
  `CANCELLED_LOCAL`/`RESOLVED` already received for that band does not
  dispatch. A cancel that arrives *after* a dispatch is recorded for a
  human to decide on recall (R-18).
- **Staleness:** if `send_time − event_time` is large, the dashboard shows
  the delay prominently: the *event* is that old.
- **Live readings (D-21, M4):** when a queued message is finally sent, the
  band refreshes its context fields to the moment of sending: `lat`, `lon`,
  `fix_age`, `hdop`, `heart_rate`, `spo2`, `resp_rate`, `spo2_slope`,
  `rr_slope`, `skin_temp`, `isf_trend`, `battery`, `sensor_age` and the
  GPS-valid and battery-low flags. Everything that says *what happened*
  stays as recorded: `msg_type`, `seq`, `event_time`, `state`, the other
  flags, `family_mask`, `family_level`, `local_source` and
  `escalation_reason`. So a responder walks to where the wearer was when
  the alert finally got out, not to where they were when it was raised
  under canopy.

## 7. Worked example

Generated by `python3 -m vrw example` (the codec, not by hand). An ALERT
from band 1001: 3FTx moderate + PLA2 trace from the cassette, escalated on
ISF rise + SpO2 fall, left ankle, 88 % battery.

```
50 bytes:
  0000  01 01 00 00 03 e9 00 03 6a fe ac 80 6a fe ac 8c
  0010  03 2f 03 03 01 00 00 01 03 fd ef 3c b8 da ea 9b
  0020  68 00 2a 0c 70 5a 1a fc 05 0d 54 01 58 00 5f 00
  0030  ec 71
```

Decode any message with `python3 -m vrw decode <hex>`.

## 8. Payload class (base side)

The base derives the payload class from an `ALERT`:

- **FAMILY_MATCHED**: at least one systemic reason bit (b0–b3) and at
  least one named family.
- **BROAD** (polyvalent, pre-made): escalated only on the local danger
  timer (b4), or no named family.

What each class means for the responder lives in the M2 checklist config
(R-08). It is never decided in code.
