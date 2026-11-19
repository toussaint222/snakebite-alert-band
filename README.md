# Venom-Response Wearable — v1 Demonstrator

> **Research demonstrator — not a medical device.** Simulation and
> drug-free trainer hardware only. No diagnostic or treatment claims.
> Nothing in this repository has been tested on, or is for use on, a
> person who has been bitten.

**Status: v1 complete — Milestones 0–4 built and approved by the owner (2026-11-19).**
All four build milestones are done. Every safety number is still a
PLACEHOLDER until ruled by the owner with expert input (see
[DECISIONS.md](DECISIONS.md)). Progress and known gaps:
[STATUS.md](STATUS.md). Where it goes next: [VISION.md](VISION.md).

> Note for the builder: the "System description" below doubles as the
> technical backbone of a patent provisional filing. It aims to be
> complete and precise. Keep it private (no remote, nothing published)
> until the owner says the provisional is filed (DECISIONS R-13).

## Contents

1. What this is, in plain words
2. Start here
3. Run it
4. System description (1–10)
5. Appendix A: every message field, state and threshold

## 1. What this is, in plain words

A band worn on the ankle or wrist watches for signs that a snakebite has
put venom into the body. It looks for two different kinds of evidence:

- **A local signal.** A small toxin test at the bite site, like a
  pregnancy-test strip with one line per toxin family. It shows venom is
  present on or in the skin, and which family it belongs to.
- **A body-wide (systemic) signal.** The venom level in the fluid just
  under the skin rising, or breathing and blood oxygen moving the wrong
  way.

Many bites deliver little or no venom ("dry bites"). So the band **never
calls for help on the local signal alone**. It starts watching, and it
calls for help only when **both** kinds of evidence are present. One
exception was ruled by the owner: a strong local signal that stays strong
for two hours also calls for help, with a broad, all-purpose kit.

Calling for help means sending one **50-byte message by satellite**. It
works far from any phone signal. If the wearer is under dense forest canopy
and the satellite can't be reached, the band keeps the message and keeps
trying until it gets through.

At the **base**, a dashboard shows where the wearer is, which toxin family
was detected and how strongly, why the band called, and a checklist of
which **pre-made** kit the responder should carry. A person decides and
sends the responder. When the responder is on scene, the base closes the
alert and the band is told.

The band **senses and calls; it never makes, mixes or gives a drug.** A
drone, if ever used, only drops a kit at a clearing or to the responder.
A human gives anything that is given. In this version everything is
simulated or a drug-free trainer.

## 2. Start here

| If you are… | Look at first | The open problem you could help with |
|---|---|---|
| **A toxinologist** | The checklist text in `dashboard/checklist.json` (placeholder) and the rulings R-01, R-05, R-08, R-17, R-22 in [DECISIONS.md](DECISIONS.md) | Which kit each toxin family and level should trigger; the systemic thresholds; what "danger" level and time justify a broad dispatch |
| **A microneedle or biosensor researcher** | §4.2 below and X-01 in DECISIONS.md | **The in-body toxin sensor.** Continuous, family-specific venom sensing in skin fluid has not been shown. Leading candidate: electrochemical aptamer or nanobody sensors on a microneedle patch. Also sensor life past about 12 hours (R-16) |
| **A lateral-flow test developer** | `vrw/sensors/lateral_flow.py`, R-23 | A cassette with one line per toxin family and a layout the band can read; real cut-offs from real tests |
| **A satellite / field engineer** | `vrw/outbox.py`, `vrw/link/`, [docs/FIELD-RUNBOOK.md](docs/FIELD-RUNBOOK.md), [docs/BATTERY-BUDGET.md](docs/BATTERY-BUDGET.md) | Canopy: the band can't tell anyone its alert is stuck (R-27); real modem testing (D-23); measured power figures |
| **A funder or reviewer** | This section, §4, and [STATUS.md](STATUS.md) | What is built (software, simulation) versus what is research (the sensor, the treatments the responder carries) |

**Honest status.** The satellite messaging, queueing, dashboard and
vitals monitoring use technology that exists today. Family-level venom
test strips are an active research area. A continuous in-body venom
sensor is the hardest, unsolved piece. Antivenom is normally given by drip
in a clinic, so the field-carried "kit" is a research question in its own
right (X-02). These research-status points are the builder's general
knowledge, not checked against current literature (X-01, X-02).

## 3. Run it

Needs only the Python 3 that ships with macOS. Nothing to install.

```bash
cd ~/Documents/VenomResponse && python3 -m unittest
```

```bash
cd ~/Documents/VenomResponse && python3 -m vrw run-all
```

Watch one bite live on the dashboard. Start the dashboard in one Terminal window,
then open http://127.0.0.1:8765:

```bash
cd ~/Documents/VenomResponse && python3 -m dashboard
```

In a second window (120× real time; you are the base and close the alert):

```bash
cd ~/Documents/VenomResponse && python3 -m vrw demo scenarios/elapid_systemic.json
```

The field run (open field → forest edge → responder on scene), as a timing table:

```bash
cd ~/Documents/VenomResponse && python3 -m vrw field scenarios/field_open_to_forest.json
```

Other commands: `python3 -m vrw canopy` (alerts under canopy),
`battery` (energy and credits), `cassette <image>` (read a test
cassette), `vitals <csv>`, `make-data`, `example`, `decode <hex>`.
Scenario files are explained in [scenarios/README.md](scenarios/README.md).

## 4. System description

Each part says what is **built** in v1 and what is **contemplated** for
later versions. "Built" means software running in simulation.

### 4.1 Problem and timing

- The time that matters is **minutes, not milliseconds**. Envenomation
  develops over minutes to hours. The design budget is: the band confirms
  a local signal within about 10 minutes of a positive test and escalates
  as soon as a systemic sign appears, the message reaches base within
  about a minute of open sky, and a person decides.
- **Dry bites** (little or no venom) are common, so contact alone must
  not dispatch a responder. A watch window follows every confirmed contact.
- **Identification is by toxin family**, not species: three-finger toxins
  (**3FTx**, neurotoxic, typical of elapids), phospholipase A2 (**PLA2**),
  snake-venom metalloproteinases (**SVMP**) and serine proteases
  (**SVSP**), the last two typical of vipers. Each comes with a
  semi-quantitative level 0–4 (none, trace, low, moderate, high).

### 4.2 Sensing

**Local signal (built as a stand-in).** A lateral-flow cassette with a
control line and one test line per family. The band reads a picture of
the result window (`vrw/sensors/lateral_flow.py`):

1. It averages the middle rows into a brightness profile and finds the
   window's dark frame, so every position is measured from the frame, not
   from the edge of the picture.
2. It finds the control line in a narrow zone (8–16 % of the
   window width). If the line is missing or faint, the test is
   **INVALID** and counts for nothing.
3. It measures each family line against the strip beside it and divides
   by the control line's darkness, so a brighter or darker picture reads
   the same. The ratio maps to a level through cut-offs (R-23).
4. A dark line where the layout has none makes the read **INVALID**. The
   layout is deliberately lopsided (control at 12 % of the window), so a
   mirrored or upside-down picture can never read as a different family.

A valid positive read confirms the local signal on its own (R-04).
Built: synthetic images and a standard-library PNG reader. Contemplated:
real cassettes, photographed and straightened, with real cut-offs.

**Systemic signal (part built, part contemplated).**

- *Vitals (built as a stand-in):* SpO2, breathing rate, heart rate, skin
  temperature, read from a CSV file (`vrw/sensors/vitals.py`). Impossible
  values are dropped as sensor artifacts; gaps are never filled in (R-24).
- *Skin-fluid (ISF) toxin level (simulated only):* scripted in the
  scenario files (D-20). Contemplated: a microneedle patch with
  family-specific binders such as aptamers or nanobodies (a research
  direction, unverified, X-01), worn anywhere on
  the body, reporting a level per family (X-01). The ISF sensor can also
  supply a local signal (two positive reads at least 2 min apart, R-04).
  It is never allowed to supply both signals from one change: an ISF
  rise counts as systemic only if it is measured from reads taken at or
  after local confirmation (R-19).

Systemic conditions (§4.3, any one is enough): S1 ISF level rises by at
least 1 band within 30 min; S2 SpO2 ≤ 92 % held 5 min and falling at
least 2 % per 10 min; S3 breathing rate ≥ 24/min held 5 min and rising
at least 2/min per 10 min; S4 heart-rate trend (off by default). "Held"
also requires no gap in readings longer than 3 min (R-24). All are
PLACEHOLDERS.

### 4.3 Trigger logic: the two-signal rule

The band runs a state machine (`vrw/trigger.py`). Every state change is
logged with its reason. An allowed-transition table makes any other
change raise an error.

| State | Meaning | Message sent |
|---|---|---|
| IDLE | Normal wear | HEARTBEAT every 6 h |
| CONTACT | Local signal seen once, not confirmed | none |
| SYSTEMIC_WATCH | Local signal confirmed; watching for a systemic signal | CONTACT_INFO once |
| ESCALATED | Local confirmed **and** systemic (or the danger timer) | ALERT, repeated |
| RESOLVED | A person closed it at base, or the local team cancelled | RESOLVED or CANCELLED_LOCAL |
| STOOD_DOWN | Watch ended with no systemic signal | STAND_DOWN |
| SYSTEMIC_ONLY | Systemic signs with no local signal | SYSTEMIC_ONLY_INFO, never a dispatch |

Transitions (full table in
[docs/02-TRIGGER-STATE-MACHINE.md](docs/02-TRIGGER-STATE-MACHINE.md)):

- **T1–T3:** IDLE → CONTACT on the first local positive. CONTACT →
  SYSTEMIC_WATCH when confirmed within 10 min (one valid cassette read,
  or 2 ISF reads at least 2 min apart). Otherwise back to IDLE.
- **T4:** SYSTEMIC_WATCH → ESCALATED when any systemic condition holds.
- **T4b (owner ruling R-01):** SYSTEMIC_WATCH → ESCALATED with reason
  "local danger" when the local level is ≥ 3 (moderate) for 2 h with no
  systemic sign.
- **T5:** SYSTEMIC_WATCH → STOOD_DOWN after 12 h with no systemic sign,
  but never on an expired sensor patch (R-06, R-16).
- **T6:** a sensor patch past its life sends SENSOR_EXPIRED and keeps
  watching.
- **T7:** ESCALATED is **latched**. It ends only when a person closes it
  (RESOLVE from base). **T7b:** the local team may cancel from any watch
  or alert state ("solution on hand"); queued, unsent ALERTs are removed
  so a cancel can never be overtaken by an older alert (R-20). **T7c:** a
  new reason while escalated sends a new ALERT at once.
- **T8, T8b, T9:** systemic signs without a local signal → SYSTEMIC_ONLY;
  back to IDLE after 30 min with SpO2 and breathing back in range; a local
  positive moves it to CONTACT.
- **T10:** STOOD_DOWN or RESOLVED → IDLE on re-arm.

Never possible: CONTACT → ESCALATED directly, any state → ESCALATED
without a confirmed local signal, ESCALATED → anything except RESOLVED.

**Power cycles (R-25).** The band writes to flash, after every change,
its message queue, its next sequence number and, while watching or
escalated, the facts the watch or alert depends on: state, when the
contact began and was confirmed, the cassette result, the danger-timer
start, the escalation reasons, whether the alert was acknowledged, and
when the last ALERT went. After a restart it **resumes** SYSTEMIC_WATCH or
ESCALATED (the latch, the timers and the alert repeats carry on, and a
close from base still works). Rolling sensor history is not kept; it is
measured again. Any other state restarts in IDLE.

### 4.4 Message format and byte budget

- **Uplink (band → base):** fixed 50 bytes, big-endian, every field at a
  fixed offset, an explicit "not available" value for every field, and a
  CRC-16/CCITT-FALSE check over bytes 0–47. 50 bytes = one satellite
  credit; the modem allows 340 (D-08).
- **Downlink (base → band):** fixed 16 bytes: ACK, RESPONDER_STATUS (with
  minutes to arrival), RESOLVE.
- **Duplicates and order:** a message is identified by device, sequence
  number and event time. Retries keep all three; the base keeps the first
  copy. The base orders by event time, so a late, older message never
  hides a newer one.
- **Live readings (D-21):** when a queued message is finally sent, its
  position, vitals and battery are refreshed to the moment of sending;
  what it reports (type, sequence, event time, state, families, reasons)
  never changes.

Byte-by-byte layout and a worked example:
[docs/01-PACKET-SPEC.md](docs/01-PACKET-SPEC.md); every field is also in
Appendix A.

### 4.5 Satellite link, store-and-forward and canopy

- Iridium short-burst data: 10–60 s latency in open sky, **total loss
  under dense canopy**, which is treated as normal, not as an error.
- **Store-and-forward (built, `vrw/outbox.py`).** Every message is saved
  before any send attempt and removed only when the modem confirms it.
  The queue and the next sequence number are written to flash after every
  change (temp file, flush, rename); a damaged file is set aside.
- **Retry policy (R-26).** ALERT, cancel and resolved messages go first,
  oldest first. They retry every 60 s; while the signal reads 0 bars, each
  retry is a cheap signal check, with a full send attempt forced at least
  every 5 min, so an alert is never held back by the reading alone and
  goes out within about a minute of the sky opening. Routine
  messages wait until the signal shows at least 2 bars and back off
  (60 s, 2, 4, 8 min, up to 15 min). One schedule covers the whole queue,
  so a heartbeat can never get out ahead of a waiting alert. The queue
  holds at most 24 messages; only the newest heartbeat is kept, and an
  urgent message is never dropped.
- **Built:** a simulated link with latency, loss, canopy blackouts, zones
  that change as the wearer moves, and a 0–5 bar signal reading.
  Contemplated: the RockBLOCK-class driver in `vrw/link/rockblock.py`,
  written and tested against a fake modem only (D-23).
- **Measured in simulation** (`python3 -m vrw canopy`): an ALERT is late
  by about the length of the canopy and then arrives with a fresh
  position. If the canopy never clears, it never arrives. After 5 min
  with an urgent message unsent, the band's **local alarm** (buzzer and
  light; simulated in v1) tells the people with the wearer to move to
  open sky, and stops when the message is sent (R-27).

### 4.6 Base dashboard and responder checklist

A local web page served from the base laptop (`python3 -m dashboard`),
with no internet needed. It shows each band's state in plain words, the
detected families and levels, why it escalated, vitals, battery, sensor
age, how old the message and the position are, an offline position plot
with distance and bearing from base, and a log of every message with
delays and retries.

On an ALERT it shows **DISPATCH RESPONDER** and the checklist for the
**payload class**:

- **FAMILY_MATCHED:** escalated on a systemic sign with at least one named
  family.
- **BROAD:** escalated on the local danger timer only, or no family named.

The class is fixed at the first alert (R-22); reasons that appear later
are shown as "since dispatch". The checklist text (what to carry, and
reminders such as ventilation support for 3FTx) is a configuration file
for a toxinologist to write. Today it is placeholder and contains no
treatment instructions (R-08).

A person presses "Responder on scene — close alert". The alert shows as
closed only when the band confirms. If the local team cancels after a
dispatch, a banner asks the person whether to recall the responder (R-18).
Responder progress (dispatched, walking in, on scene, minutes to go)
appears on the page and is sent to the band.

### 4.7 Companion-unit and responder doctrine

- A **ground responder** is the default and carries a **pre-made** kit of
  the class named.
- A **drone** may carry a kit **to a clearing or to the responder**. It
  never descends through canopy and never treats anyone.
- **A human administers** anything that is administered. Any auto-injector
  in v1 is a drug-free **trainer**.
- Built: a simulated responder (`vrw/responder.py`) who decides, drives to
  a trailhead and walks to the band's **reported** position, adding
  search time if that position is old or poor (R-28). No drone is modelled.

### 4.8 Safety boundaries (all built in)

- Senses and calls only. No code designs, makes, mixes or doses anything.
- Two signals or no dispatch, apart from the owner's danger-timer ruling.
  This is enforced in one place and covered by tests.
- Every message carries "simulated" and "trainer hardware" flags. The
  base refuses any message without them.
- Every safety number lives in `vrw/thresholds.json`, marked PLACEHOLDER
  with the ruling it belongs to. Power assumptions live in `vrw/power.json`.
- Every screen and document carries "Research demonstrator — not a
  medical device." (tested).
- No real drug, venom or patient anywhere. Synthetic data only.

### 4.9 What has been measured (simulation)

From `python3 -m vrw field scenarios/field_open_to_forest.json`: the bite
happens at the forest edge, the wearer goes under canopy, and is carried
back to the edge.

| Milestone | After the bite | Kind |
|---|---|---|
| Local signal confirmed | 5 min | measured (software) |
| Band escalates (under canopy) | 40 min | measured |
| ALERT shown on the dashboard | 51 min | measured |
| Responder on scene | 1 h 52 min | **assumed** responder numbers (R-28) |
| Band confirms the close | 1 h 53 min | measured |

In open sky (the `elapid_systemic` scenario) the ALERT reaches the dashboard
23 s after the band escalates. These are simulated times. They are not
real-world claims.

### 4.10 Variations and extensions (contemplated, not built)

- Other wear sites (wrist, upper arm, chest patch). The wear site is
  already in every message.
- Other toxin families or other envenomations (scorpion, spider, marine).
  The family mask has two spare bits, and the message has 290 bytes of
  headroom.
- Other hostile environments where phones fail: deserts, mountains, sea,
  disaster zones. Other carriers for the message: other satellite
  networks, mesh radio, a companion phone.
- A wearer SOS button (R-09). The stuck-alert alarm (R-27) is built in
  simulation; the buzzer and light themselves are hardware for later.
- Kits matched to toxin family carried by the responder, including
  investigational small-molecule inhibitors, subject to clinical evidence
  and regulation (X-02).

## 5. Appendix A: every message field, state and threshold

**Uplink fields (50 bytes):** `version`, `msg_type`, `device_id`, `seq`,
`event_time`, `send_time`, `state`, `flags`, `family_mask`,
`family_level`, `local_source`, `escalation_reason`, `lat`, `lon`,
`fix_age`, `hdop`, `heart_rate`, `spo2`, `resp_rate`, `spo2_slope`,
`rr_slope`, `skin_temp`, `isf_trend`, `battery`, `sensor_age`,
`wear_site`, `crc16`. Meanings, units and offsets:
[docs/01-PACKET-SPEC.md](docs/01-PACKET-SPEC.md).

**Uplink message types:** ALERT (0x01), CONTACT_INFO (0x02), STAND_DOWN
(0x03), RESOLVED (0x04), HEARTBEAT (0x05), SYSTEMIC_ONLY_INFO (0x06),
SENSOR_EXPIRED (0x07), CANCELLED_LOCAL (0x08).

**Downlink message types:** ACK (0x80), RESPONDER_STATUS (0x81), RESOLVE
(0x82). Downlink fields: `version`, `msg_type`, `device_id`, `ack_seq`,
`base_time`, `responder_status`, `eta_min`, `crc16`.

**States:** IDLE, CONTACT, SYSTEMIC_WATCH, ESCALATED, RESOLVED,
STOOD_DOWN, SYSTEMIC_ONLY.

**Thresholds** (`vrw/thresholds.json`; every one PLACEHOLDER until ruled):

| Key | Value | Ruling | Meaning |
|---|---|---|---|
| `local_confirm_window_s` | 600 s | R-04 | CONTACT must be confirmed within this time or returns to IDLE |
| `isf_confirm_reads` | 2 reads | R-04 | positive ISF reads needed to confirm (a valid lateral-flow positive confirms on its own) |
| `isf_confirm_min_gap_s` | 120 s | R-04 | minimum gap between first and last confirming ISF reads |
| `isf_rise_bands` | 1 bands | R-05 | S1: ISF level rise counted as systemic |
| `isf_rise_window_s` | 1800 s | R-05 | S1 window |
| `spo2_low_pct` | 92 % | R-05 | S2 level |
| `spo2_sustain_s` | 300 s | R-05 | S2 must hold this long |
| `spo2_fall_per_10min` | 2 % / 10 min | R-05 | S2 trend: falling at least this fast |
| `rr_high` | 24 breaths/min | R-05 | S3 level |
| `rr_sustain_s` | 300 s | R-05 | S3 must hold this long |
| `rr_rise_per_10min` | 2 /min / 10 min | R-05 | S3 trend: rising at least this fast |
| `hr_enabled` | false  | R-05 | S4 heart-rate trend; off by default |
| `standdown_s` | 43200 s | R-06 | dry-bite stand-down after this long with no systemic signal; never on an expired sensor |
| `danger_level` | 3 band | R-01 | local level (moderate) that starts the danger timer |
| `danger_time_s` | 7200 s | R-01 | strong local signal held this long escalates with BROAD payload class |
| `systemic_only_clear_s` | 1800 s | R-02 | SYSTEMIC_ONLY returns to IDLE after systemic signs clear for this long |
| `alert_repeat_unacked_s` | 600 s | R-15 | resend ALERT while not acknowledged |
| `alert_repeat_acked_s` | 1800 s | R-15 | resend ALERT after acknowledgement |
| `heartbeat_s` | 21600 s | R-15 | HEARTBEAT after this long with nothing sent |
| `retry_interval_s` | 60 s | R-26 | retry interval while an urgent message (ALERT, cancel, resolved) waits; also the first routine retry |
| `retry_backoff_max_s` | 900 s | R-26 | routine messages only: wait doubles after each failure up to this |
| `link_min_signal` | 2 bars 0-5 | R-26 | routine messages only: don't power up a send unless the signal shows this many bars. Never applied to urgent messages |
| `urgent_blind_attempt_s` | 300 s | R-26 | urgent messages while the signal reads 0 bars: a cheap signal check every retry_interval_s, but a full send attempt at least this often anyway (the reading can be wrong) |
| `stuck_alarm_s` | 300 s | R-27 | an urgent message unsent this long sets off the band's local alarm (buzzer + light): move to open sky |
| `queue_max` | 24 messages | R-26 | queue limit; oldest routine message dropped first; urgent messages never dropped; only the newest HEARTBEAT kept |
| `battery_low_pct` | 20 % | M4 | sets battery-low flag |
| `lfa_control_min_contrast` | 40 grey levels | R-23 | control line must be at least this much darker than the strip beside it, or the test is INVALID |
| `lfa_band_ratios` | [0.1, 0.3, 0.55, 0.8] x control | R-23 | test-line darkness as a fraction of the control line's: at or above each cut-off = band 1 trace, 2 low, 3 moderate, 4 high. Band 3 starts the R-01 danger timer, so these are dispatch logic |
| `lfa_control_search` | [0.08, 0.16] x window | R-23 | where inside the result window the control line may be (nominal 0.12); kept narrow so a missing control can never be confused with the 3FTx line at 0.29, nor a flipped image's SVSP line at 0.20 |
| `vitals_plausible` | {"spo2": [50, 100], "rr": [3, 70], "hr": [25, 250], "skin_temp": [20, 42]}  | R-24 | a reading outside these is treated as a sensor artifact and dropped (not carried forward) |
| `vitals_max_gap_s` | 180 s | R-24 | a 'sustained' SpO2/breathing condition only counts if there is no gap in readings longer than this inside the hold window |

**Power assumptions** (`vrw/power.json`, D-22): `battery_mah`,
`baseline_ma`, `gps_fix_mas`, `signal_check_mas`, `send_attempt_mas`,
`credit_bytes`.
