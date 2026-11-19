# 02 — Trigger state machine

> **Research demonstrator — not a medical device.**

Status: **Approved at M0 (2026-11-18), amended by R-01. Implemented in `vrw/trigger.py` (M1).** This is safety logic: every threshold,
timer and branch below that is not fixed by the brief is a **RULING
NEEDED** item in [DECISIONS.md](../DECISIONS.md). Numbers shown are
**PLACEHOLDERS** chosen only so the simulator can run — they are not
clinical values and must be set by the product owner with toxinologist
input.

## 1. The rule in plain words

- A positive local test alone means **contact**. The band starts watching
  and logs. It never dispatches anyone on contact alone (about half of
  bites are dry).
- The band **escalates** only when it has **both** a confirmed local
  signal **and** a systemic signal.
- **Owner amendment (R-01):** a **strong** local signal (level ≥ moderate)
  that stays strong past a danger timer escalates even without a systemic
  signal, and the base assigns the **BROAD** (polyvalent, pre-made)
  payload class. Weak contact (trace/low) still never dispatches.
- The **local team can cancel** at any point in CONTACT, SYSTEMIC_WATCH,
  SYSTEMIC_ONLY or ESCALATED (solution on hand) — R-01.
- Once escalated, the band **stays escalated** until a person closes the
  alert (R-07). It never quietly downgrades itself.

## 2. States

| State | Meaning | Band transmits? |
|---|---|---|
| `IDLE` | Normal wear. Nothing detected. | Heartbeat only (R-15) |
| `CONTACT` | A local signal has been seen once, not yet confirmed. | No (proposed) |
| `SYSTEMIC_WATCH` ("SYSTEMIC?") | Local signal confirmed. Watching for a systemic signal. | One `CONTACT_INFO` on entry — **R-03** |
| `ESCALATED` | Local confirmed **and** systemic present. | `ALERT`, repeated (R-15) |
| `RESOLVED` | A person closed the alert (base) or the local team cancelled (band). | One `RESOLVED` or `CANCELLED_LOCAL` |
| `STOOD_DOWN` | Watch window ended with no systemic signal (the expected course after a dry bite; the band states no conclusion, R-21). | One `STAND_DOWN` |
| `SYSTEMIC_ONLY` | Systemic signal with **no** local positive (bite away from the band, or not a bite). | One `SYSTEMIC_ONLY_INFO`, never a dispatch (R-02) |

## 3. Diagram

```
                    local positive (1st read)
        ┌──────┐ ───────────────────────────► ┌─────────┐
        │ IDLE │                               │ CONTACT │
        └──────┘ ◄─────────────────────────── └─────────┘
          ▲  │     not confirmed within T_confirm    │
          │  │                                       │ local confirmed (R-04)
          │  │ systemic, no local (R-02)             ▼
          │  ▼                              ┌────────────────┐
   ┌───────────────┐                        │ SYSTEMIC_WATCH │
   │ SYSTEMIC_ONLY │                        │  ("SYSTEMIC?") │
   └───────────────┘                        └────────────────┘
                         systemic, or strong  │            │ no systemic signal
                         local held past      │            │ for T_standdown (R-06)
                         T_danger (R-05,R-01) ▼            ▼
                                     ┌───────────┐   ┌────────────┐
                                     │ ESCALATED │   │ STOOD_DOWN │──► IDLE
                                     └───────────┘   └────────────┘
                                          │  (latched — no automatic exit)
                                          │ base closes it (R-07), or local team
                                          │ cancels on the band (R-01; also from
                                          │ CONTACT / SYSTEMIC_WATCH / SYSTEMIC_ONLY)
                                          ▼
                                     ┌──────────┐
                                     │ RESOLVED │──► IDLE (after re-arm)
                                     └──────────┘
```

## 4. Transition table (the authoritative version)

| # | From | Condition | To | Sends | Ruling |
|---|---|---|---|---|---|
| T1 | IDLE | First local-positive reading | CONTACT | — | — |
| T2 | CONTACT | Local signal confirmed (placeholder: a lateral-flow read with valid control line, **or** 2 positive ISF reads ≥ 2 min apart, within T_confirm = 10 min) | SYSTEMIC_WATCH | `CONTACT_INFO` (if R-03 = transmit) | R-04, R-03 |
| T3 | CONTACT | Not confirmed within T_confirm | IDLE | — (logged) | R-04 |
| T4 | SYSTEMIC_WATCH | **Any** systemic condition true (§5) | ESCALATED (payload FAMILY_MATCHED) | `ALERT` | R-05 |
| T4b | SYSTEMIC_WATCH | Latest local level ≥ danger_level (placeholder 3 = moderate) for danger_time_s (placeholder 2 h), no systemic signal. Note: a cassette level stays at its last read, so one strong read is enough (see R-01 status) | ESCALATED (reason `local_danger`, payload BROAD) | `ALERT` | R-01 |
| T5 | SYSTEMIC_WATCH | No systemic condition for T_standdown (placeholder 12 h) | STOOD_DOWN | `STAND_DOWN` | R-06 |
| T6 | SYSTEMIC_WATCH | Sensor patch past its life | SYSTEMIC_WATCH (flag `sensor expired`) | `SENSOR_EXPIRED` | R-06 |
| T7 | ESCALATED | Dashboard sends RESOLVE | RESOLVED | `RESOLVED` | R-07 |
| T7b | CONTACT, SYSTEMIC_WATCH, SYSTEMIC_ONLY, ESCALATED | Local team cancels on the band | RESOLVED | `CANCELLED_LOCAL`; unsent ALERTs are removed from the queue | R-01, R-20 |
| T7c | ESCALATED | A new escalation reason appears (e.g. SpO2 starts falling) | ESCALATED | `ALERT` at once | R-15 |
| T8 | IDLE | Systemic condition true, no local positive | SYSTEMIC_ONLY | `SYSTEMIC_ONLY_INFO` | R-02 |
| T8b | SYSTEMIC_ONLY | SpO2 and RR back in range for systemic_only_clear_s (placeholder 30 min). Clears on levels, not on the trend stopping: a plateau at low SpO2 is not "cleared". | IDLE | — | R-02, D-10 |
| T9 | SYSTEMIC_ONLY | Local positive appears | CONTACT → (fast path) | — | R-02 |
| T10 | STOOD_DOWN / RESOLVED | Re-arm (new sensor patch or manual reset) | IDLE | — | — |

**Things that never happen** (enforced by an allowed-transition table in
code and by tests): CONTACT → ESCALATED directly; any state → ESCALATED
without a confirmed local signal; ESCALATED → anything except RESOLVED.

## 5. Systemic conditions (all PLACEHOLDERS — R-05)

Any one of these, while in SYSTEMIC_WATCH, counts as "systemic":

| Code | Condition (placeholder) | Packet bit |
|---|---|---|
| S1 | ISF toxin level rises ≥ 1 band within 30 min, counting only reads at or after local confirmation (R-19) | `escalation_reason` b0 |
| S2 | SpO2 ≤ 92 % sustained 5 min **and** falling ≥ 2 % per 10 min | b1 |
| S3 | Respiratory rate ≥ 24/min sustained 5 min **and** rising | b2 |
| S4 | Heart-rate trend (off by default) | b3 |

"Sustained" also requires no gap longer than 3 min in the readings inside
the hold window, and readings outside a plausible range are dropped as
sensor artifacts before they get here (R-24).

These live in `vrw/thresholds.json`, each with `"status": "PLACEHOLDER"`
until ruled. The code reads them from that file; nothing is hard-coded.

## 6. Scenarios and their results (M1, M3, M4)

A power cycle is not a state transition. The band saves its watch or alert
facts to flash and **resumes** SYSTEMIC_WATCH or ESCALATED after a restart;
any other state restarts in IDLE (R-25). The log records "power cycle:
resumed …".

Run them all: `python3 -m vrw run-all`. Each prints its timeline and checks.

| Scenario | Final state | Dispatch? | What it shows |
|---|---|---|---|
| `dry_bite` | STOOD_DOWN | No | Trace 3FTx contact, no systemic signal; stands down after the 12 h watch. Uses a hypothetical 24 h sensor patch. |
| `dry_bite_sensor_expires` | SYSTEMIC_WATCH | No | Same bite with a 12 h patch: it expires before the watch ends, so the band reports `SENSOR_EXPIRED` and never stands itself down. **See R-16.** |
| `elapid_systemic` | RESOLVED | **Yes**, FAMILY_MATCHED (3FTx, PLA2), alert at base 23 s after escalation | Cassette confirms at 5 min; ISF rise at 40 min escalates; SpO2/RR reasons added later; base closes at 2.5 h. |
| `viper_local_only` | ESCALATED | **Yes**, BROAD | Strong SVMP/SVSP, no systemic signal (ISF reads 0 before the bite, then steady); escalates on the danger timer at 2 h 5 min (R-01). |
| `isf_only_zero_baseline` | SYSTEMIC_WATCH | No | ISF sensor alone going 0 → trace: confirms local but is not also counted as a systemic rise (R-19). |
| `canopy_cancel_before_send` | RESOLVED | No | ALERT stuck under canopy, local team cancels; base gets the cancel, never the alert (R-20). |
| `viper_local_cancelled` | RESOLVED | No | Same viper bite; the local team cancels at 1 h. |
| `canopy_link_loss` | ESCALATED | **Yes**, delayed ~50 min | ALERT raised under canopy, retried every minute, delivered when the sky opens, with its original event time. Out-of-order arrivals handled. |
| `systemic_only` | IDLE | No | Bad vitals with no toxin signal: one info message, back to IDLE once vitals recover. |
| `standin_contact_only` | STOOD_DOWN | No | **M3 gate.** Cassette *image* (faint 3FTx) and vitals *CSV* with a slipped probe, an SpO2 of 0, a 20-min gap and blank cells. Never escalates. |
| `standin_systemic_vitals` | RESOLVED | **Yes**, FAMILY_MATCHED (3FTx, PLA2), 23 s | **M3 gate.** Cassette image confirms local; ISF held flat, so the escalation at 1 h 14 min comes from the vitals CSV (SpO2 falling). |
| `canopy_power_cycle` | ESCALATED | **Yes**, delayed ~50 min | Power lost for 2 min under canopy with an ALERT queued. The queue, message numbers and the ESCALATED state come back from flash (R-25). |
| `field_open_to_forest` | RESOLVED | **Yes**, alert at base ~11 min after escalation | **M4 gate.** Open field → bite at the forest edge → canopy → carried back to the edge; responder drives and walks to the reported position; band confirms the close. |
| `standin_invalid_then_retest` | SYSTEMIC_WATCH | No | Cassette with strong 3FTx but no control line: INVALID, band stays idle. A valid retest at 20 min confirms. |
