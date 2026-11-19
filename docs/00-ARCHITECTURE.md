# 00 — Architecture (Milestone 0 plan)

> **Research demonstrator — not a medical device.**

Status: **Approved at M0 (2026-11-18).** M1–M3 approved; M4 built. Rulings are in
[DECISIONS.md](../DECISIONS.md).

## 1. What the system does, in one paragraph

A band on the ankle (or wrist) watches for two kinds of evidence of a
possible snakebite envenomation: a **local signal** (a toxin-family test
at the bite site comes back positive) and a **systemic signal** (toxin
level in the skin fluid is rising, or breathing/oxygen readings are
trending the wrong way). Only when **both** are present does the band
escalate. Escalation means sending a small fixed-size message (50 bytes)
over a satellite short-burst link. A dashboard at a base receives it,
shows where the wearer is and which toxin family was detected, and gives
the responder a checklist of which **pre-made** payload class to carry.
The band never makes, mixes or delivers a drug. If the satellite link is
down (dense canopy), the band keeps the message in a queue and retries
until it gets through.

## 2. The loop, end to end

```
 ┌──────────── WEARABLE (simulated in v1) ────────────┐
 │                                                     │
 │  Sensor stand-ins              Trigger logic        │
 │  ─────────────────             ─────────────        │
 │  lateral-flow image ─┐                              │
 │  (local, family code)├──► state machine ──► packet  │
 │  ISF toxin level ────┤    (two-signal rule)  encoder│
 │  vitals (SpO2,RR,HR)─┘          │              │    │
 │                                 ▼              ▼    │
 │                          on-device log   outbound   │
 │                                          queue      │
 │                                     (store & fwd)   │
 └──────────────────────────────────────────┬──────────┘
                                            │ 50-byte message
                         ┌──────────────────▼─────────────────┐
                         │ LINK                                │
                         │  • simulated SBD (latency, loss,    │
                         │    canopy blackout profiles)        │
                         │  • real RockBLOCK-class modem       │
                         │    (optional, only if present)      │
                         └──────────────────┬─────────────────┘
                                            │
                         ┌──────────────────▼─────────────────┐
                         │ BASE / DASHBOARD (local web page)   │
                         │  decode → dedupe → alert state      │
                         │  offline position plot              │
                         │  family code + level                │
                         │  responder checklist (from config)  │
                         │  ACK / "responder on scene" → down  │
                         └──────────────────┬─────────────────┘
                                            │
                                     human responder
                               (carries pre-made payload;
                               trainer auto-injector only in v1)
```

## 3. Components

| Component | What it is in v1 | Milestone |
|---|---|---|
| **Packet codec** | Encode/decode the 50-byte alert message and the small downlink ACK. Spec: [01-PACKET-SPEC.md](01-PACKET-SPEC.md). | M1 |
| **Trigger state machine** | Applies the two-signal rule. Spec: [02-TRIGGER-STATE-MACHINE.md](02-TRIGGER-STATE-MACHINE.md). | M1 (simple inputs), M3 (real stand-in inputs) |
| **Scenario simulator** | Plays scripted timelines (dry bite, elapid systemic, viper local-only, canopy link loss) against the state machine using a **simulated clock**, so a 12-hour scenario runs in seconds. | M1 |
| **CLI** | `python3 -m vrw run scenarios/<name>.json` — runs a scenario end to end and prints a timeline + pass/fail. | M1 |
| **Simulated satellite link** | Adds latency (10–60 s), drops messages, supports total-blackout windows (canopy) and zones over time (open field → forest edge → canopy) with a 0–5 bar signal reading. | M1, M4 |
| **Outbox** | Store-and-forward: every message is queued (and saved to flash with the next message number) before any send attempt and removed only when the link confirms it. Urgent first; one retry schedule; routine back-off and signal check; bounded size (R-25, R-26). Refreshes live readings at send (D-21). | M1, M4 |
| **Dashboard** | A local web page served by Python's built-in web server. Shows alert state, offline position plot, family code, responder checklist. | M2 |
| **Responder checklist config** | A plain JSON file mapping family code → payload class + reminders. Content comes from a toxinologist, not from code. | M2 |
| **Vitals stand-in** | Reads a CSV of SpO2/RR/HR/skin-temp (simulated or exported from a wearable-class device). Drops impossible values as artifacts; never fills gaps (R-24). | M3 (built) |
| **Lateral-flow reader** | Reads an image of a test cassette (stdlib PNG reader): finds the result window, checks the control line, measures each family line against it, outputs family + band 0–4. Anything unexpected = INVALID (R-23). Synthetic images only in v1. | M3 (built) |
| **Real modem driver** | `vrw/link/rockblock.py`: AT-command driver for a RockBLOCK 9603-class modem. Tested only against a fake modem; refuses a real port without an explicit flag (D-23). | M4 (optional, built) |
| **Responder model** | `vrw/responder.py`: decision delay, drive to trailhead, walk to the reported position, search if the fix is old. Reports progress to the base and band (RESPONDER_STATUS). PLACEHOLDER numbers (R-28). | M4 |
| **Field tools** | `python3 -m vrw field` (timed run), `canopy` (failure modes), `battery` (energy and credits; `vrw/power.json`), [FIELD-RUNBOOK.md](FIELD-RUNBOOK.md), [BATTERY-BUDGET.md](BATTERY-BUDGET.md). | M4 (built) |

## 4. Technology choices (engineering, logged as D-items)

- **Language: Python 3.9, standard library only** for M1–M2. This Mac has
  Python 3.9.6 and nothing else (no Node, no package manager). The
  standard library covers binary packing (`struct`), checksums
  (`binascii`), the web server (`http.server`), JSON, and tests
  (`unittest`). Nothing to install for M1–M2.
- **Dashboard: plain HTML + JavaScript, no framework, no internet.** No
  CDN scripts and no online map tiles — the demo must work in a field with
  no connection. Position is drawn as an offline plot. (R-10)
- **Possible later dependencies, each one pinned and optional:**
  `pyserial` for a real modem (R-12); maybe `Pillow` for reading real
  phone photos of cassettes (R-11). Installed into a local `.venv` only
  when that milestone needs them.
- **Simulated time everywhere.** Every component is handed the current
  time as a number (`now`) and never reads the wall clock, so scenarios are
  repeatable and fast and the M2 "under 60 seconds of simulated latency"
  gate is measurable.
- **Tests:** `python3 -m unittest` — no test framework to install.

## 5. Repository layout (planned)

```
VenomResponse/
├── README.md                  plain-language system description + "Start here"
├── DECISIONS.md               every ruling, open and closed
├── STATUS.md                  milestone status, what works / what doesn't
├── docs/
│   ├── 00-ARCHITECTURE.md     this file
│   ├── 01-PACKET-SPEC.md      byte-level message layout
│   ├── 02-TRIGGER-STATE-MACHINE.md
│   ├── 03-MILESTONES.md       gates and how each is checked
│   ├── FIELD-RUNBOOK.md       how to run a field demo safely
│   └── BATTERY-BUDGET.md      energy and credits, fixed vs hardened retry
├── vrw/                       Python package ("venom-response wearable")
│   ├── __main__.py            CLI entry: python3 -m vrw ...
│   ├── packet.py              encode/decode, CRC
│   ├── trigger.py             state machine (thresholds in thresholds.json)
│   ├── thresholds.json        every safety threshold, each tagged PLACEHOLDER
│   ├── outbox.py              store-and-forward queue (optional file mirror)
│   ├── device.py              the simulated band: machine + GPS/battery/sensor + outbox
│   ├── base.py                base logic: decode, dedupe, payload class, ACK/RESOLVE
│   ├── remote.py              talks to the dashboard over local HTTP (demo, tests)
│   ├── link/
│   │   ├── sim_sbd.py         simulated satellite link + canopy profiles
│   │   └── rockblock.py       optional real-modem driver (untested on hardware)
│   ├── sensors/
│   │   ├── vitals.py          vitals CSV reader (artifacts dropped, no gap filling)
│   │   ├── lateral_flow.py    cassette image → family code + band
│   │   ├── png.py             standard-library PNG reader/writer
│   │   └── synth.py           makes the synthetic images and CSVs
│   ├── responder.py           simulated responder (field runs)
│   ├── fieldtools.py          canopy and battery reports
│   ├── power.json             power/cost assumptions (PLACEHOLDER)
│   └── scenario.py            scenario runner
├── scenarios/                 scripted timelines (JSON)
│   ├── data/                  synthetic cassette images + vitals CSVs (M3)
│   ├── dry_bite.json
│   ├── elapid_systemic.json
│   ├── viper_local_only.json
│   └── canopy_link_loss.json
├── dashboard/                 the base station (python3 -m dashboard)
│   ├── server.py              local web server: receives uplinks, queues downlinks
│   ├── checklist.py           picks checklist lines for a payload class
│   ├── checklist.json         family → what to carry + reminders (content: toxinologist)
│   └── static/  index.html, app.js, style.css
└── tests/                     unittest suite; one test per gate criterion
```

## 6. Safety boundaries built into the design

- **Senses and triggers only.** No code path designs, synthesises, mixes
  or doses anything. The checklist names a payload *class* the responder
  already carries.
- **Two signals or no dispatch.** Enforced in one place
  (`trigger.py`) and covered by a test per scenario.
- **Trainer hardware only.** Every packet carries a `simulated` flag and a
  `trainer_hardware` flag; the dashboard refuses to show a packet without
  them in v1.
- **No real drug, venom or patient** anywhere in the system.
- **Every threshold lives in one file** (`thresholds.json`), each marked
  `PLACEHOLDER` until ruled. Changing a threshold is a DECISIONS.md entry.
- **Disclaimer on every screen and document:** "Research demonstrator — not
  a medical device."

## 7. Out of scope for v1

Anything other than snakebite; real drone flight; any actuation of a real
drug; in-vivo toxin sensing (simulated only); cloud hosting; mobile app.
