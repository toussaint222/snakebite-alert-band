# Stand-in sensor data (M3)

> **Research demonstrator — not a medical device.** Every file in this folder
> is **synthetic**: invented by `vrw/sensors/synth.py` for simulation. None of
> it is a photo of a real test, a reading from a real person, or clinical data.

Rebuild every file exactly (fixed random seeds):

```bash
cd ~/Documents/VenomResponse && python3 -m vrw make-data
```

| File | What it stands in for |
|---|---|
| `cassette_contact_trace_3ftx.png` | Cassette with a faint 3FTx line (trace). Used by the contact-only scenario. |
| `cassette_elapid_3ftx2_pla2_1.png` | 3FTx low + PLA2 trace, photo slightly off-centre and darker. |
| `cassette_viper_svmp3_svsp2.png` | SVMP moderate + SVSP low. |
| `cassette_invalid_no_control.png` | Strong 3FTx line but **no control line**: an invalid test that must count for nothing. |
| `cassette_blank_control_only.png` | Valid test, no family lines (negative). |
| `vitals_contact_only.csv` | 13 h of normal vitals after a bite, with a slipped probe, an impossible SpO2 of 0, a 20-minute gap and blank cells. |
| `vitals_systemic.csv` | 3 h in which SpO2 falls and breathing rate climbs. |

Cassette layout and how it is read: `vrw/sensors/lateral_flow.py`.
CSV columns and rules: `vrw/sensors/vitals.py`. Read any image yourself:

```bash
cd ~/Documents/VenomResponse && python3 -m vrw cassette scenarios/data/cassette_elapid_3ftx2_pla2_1.png
```
