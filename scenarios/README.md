# Scenario files

> **Research demonstrator — not a medical device.** All values are invented
> for simulation. Nothing here is clinical data.

Each `.json` file is one scripted timeline. Times (`t`) are seconds from the start.

| Key | Meaning |
|---|---|
| `name`, `description` | Shown by the CLI. |
| `device_id`, `wear_site` | Band identity; wear site 0 = left ankle. |
| `start_utc` | Simulated start time (default 2026-11-18T08:00:00Z). |
| `duration_s`, `step_s` | Length of the run; simulation step (default 10 s). |
| `position` | `{lat, lon, hdop}` GPS fix at start. |
| `battery` | `{start, drain_per_hour}` in %. |
| `sensor` | `{applied_t, life_s}` sensor patch applied at `applied_t`, expires after `life_s`. |
| `link` | `{latency_s: [min,max], drop_prob, blackouts: [[from,to],...], seed}`; blackout = canopy, no link at all. |
| `isf_reads` | List of `{from, to, every_s, levels: {family: band}}`; families not listed read 0. |
| `vitals_sample_s` | How often vitals are sampled (default 60 s). |
| `vitals_csv` | M3: path (relative to this folder) to a vitals CSV in `data/`, used instead of `vitals` keyframes. Each row is delivered once at its time; gaps stay gaps. |
| `timeline` | Events: `vitals` keyframes (interpolated), `lfa` cassette reads `{control_ok, levels, unclassified}`, `lfa_image` (M3: a cassette image in `data/`, read by the image reader), `action: "local_cancel"`, `base: "resolve"`, `gps`. |
| `link.profile` | M4: zones over time `[{from, to, drop_prob, label}]` or `{from, to, blackout: true}`; also drives the signal reading. |
| `power_cycle` | M4: `[{at, off_s}]`: the band loses power and restarts from what it saved (queue + message number). |
| `bite_t` | M4: when the bite happens (for the field timing table only). |
| `responder` | M4: responder model `{decision_delay_s, trailhead: {lat, lon}, vehicle_kmh, foot_kmh, winding, search_s, fix_old_s, hdop_poor}` (R-28). |
| `threshold_overrides` | Optional per-scenario changes to `vrw/thresholds.json`. |
| `expect` | What must be true at the end (M3 adds `cassette_reads`, `local_levels`, `reasons_exclude`, `first_state_change_after_s`); checked by `python3 -m vrw run` and the test suite. |

Bands: 0 none, 1 trace, 2 low, 3 moderate, 4 high.
