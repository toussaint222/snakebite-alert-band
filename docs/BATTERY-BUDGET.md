# Battery and credit budget — v1

> **Research demonstrator — not a medical device.** Every power figure here
> is a **PLACEHOLDER assumption** (`vrw/power.json`, D-22) of roughly the
> right size for a small wearable with an Iridium 9603-class modem. None
> is measured. Read the tables as a **comparison between retry policies**,
> never as a battery-life promise.

Regenerate both tables:

```bash
cd ~/Documents/VenomResponse && python3 -m vrw battery
```

```bash
cd ~/Documents/VenomResponse && python3 -m vrw canopy
```

## 1. Where the energy goes

| Item | Assumed cost |
|---|---|
| Always on (processor mostly asleep, vitals sensing, ISF reader) | 1.0 mA average |
| One GPS fix attempt | 30 mA for about 15 s |
| Signal check (wake modem, read bars) | 40 mA for about 10 s |
| One send session, success or failure | 150 mA for about 30 s |
| Battery | 1200 mAh |

A send session costs about as much as **75 minutes of everything else**.
Under canopy, failed sessions are what drain the battery.

## 2. Fixed vs hardened retry (R-26)

"fixed" = the M1–M3 behaviour (retry every 60 s, never look at the signal).
"hardened" = M4 as ruled: urgent messages retry every 60 s, but at 0 bars
each retry is a cheap signal check with a full send forced at least every
5 min; routine messages wait for signal and back off up to 15 min.

```
Battery and credit budget. Simulated runs; energy from vrw/power.json (every value a
PLACEHOLDER assumption, battery 1200 mAh). 'fixed' = retry every 60 s regardless (M1-M3);
'hardened' = R-26 (urgent: 60 s, cheap check at 0 bars, full send at least every 5 min;
routine: waits for signal and backs off).
------------------------------------------------------------------------------------------------
  case                                     policy    attempts  checks  radio mAh  total mAh  battery up credits
  Elapid bite, open sky (3 h)              fixed            8       0       10.0       35.6     3.0%        8
                                           hardened         8       8       10.9       36.5     3.0%        8
  Elapid bite, 1 h canopy (3 h)            fixed           57       0       71.2       92.6     7.7%        6
                                           hardened        16      57       26.3       47.7     4.0%        6
  Dry bite, open sky (13 h)                fixed            3       0        3.8      114.4     9.5%        3
                                           hardened         3       3        4.1      114.7     9.6%        3
  Dry bite, 10 h under canopy (13 h)       fixed          268       0      335.0      445.6    37.1%        3
                                           hardened         3      24        6.4      117.0     9.8%        3
  Field run, open field to forest (4 h)    fixed           19       0       23.8       57.9     4.8%        5
                                           hardened        11      19       15.9       50.0     4.2%        5
------------------------------------------------------------------------------------------------
Read as a comparison only. 'up credits' counts band -> base messages only (each 50 bytes = 1).
Same dispatch outcome under both policies is checked by the tests.
```

What it shows:

- In open sky the two policies cost the same (a few signal checks extra).
- Under canopy the hardened policy spends far less on failed sends: 26
  instead of 71 mAh for a 1 h canopy alert, and 6 instead of 335 mAh for
  10 h of canopy after a dry bite. The same messages get through.
- The dispatch outcome is the same under both policies in every case
  (checked by `tests/test_m4.py`).
- **Caveat:** in this simulator the signal reading comes from the same loss
  rate as the link, so it is never wrong. A real modem's reading can be
  wrong; the worst case is a 5-minute delay to an urgent send that would
  have worked (tested).

## 3. ALERTs under canopy

```
Canopy failure modes: the elapid bite (ALERT raised at T+40 min) with canopy
from T+30 min. Simulated; 8 h run; no base close. Radio energy uses PLACEHOLDER
power figures (vrw/power.json).
--------------------------------------------------------------------------------------------
  case                                       delivered   ALERT delay    fix age  attempts  radio mAh
  no canopy                                  yes               1 min      0 min        18       24.5
  10 min canopy                              yes               1 min      0 min        18       24.5
  30 min canopy                              yes              21 min      0 min        21       30.4
  60 min canopy                              yes              51 min      0 min        27       41.3
  2 h canopy                                 yes             111 min      0 min        37       60.2
  4 h canopy                                 yes             231 min      0 min        57       98.1
  60 min canopy, then patchy sky (50% loss)  yes              52 min      0 min        36       53.6
  60 min canopy, then poor sky (90% loss)    yes              66 min      0 min       125      185.0
  canopy never clears                        NO                    -          -        89      160.4
--------------------------------------------------------------------------------------------
ALERT delay = escalation to base. fix age = how old the position in the delivered ALERT
was when sent (canopy blocks GPS too). If the canopy never clears the ALERT never
arrives; after 5 min the band's local alarm tells the people with the wearer to move
to open sky (R-27). In this simulator the signal reading follows the link's loss rate,
so it is never wrong; a real reading can be, costing up to 5 min (R-26).
```

What it shows:

- The ALERT always arrives once the sky opens. It arrives late by roughly
  the canopy time, keeps its original event time, and carries a fresh
  position (D-21).
- An ALERT that can never get out now costs about 160 mAh of radio in 8 h
  (it was about 550 before the R-26 ruling). After 5 min the band's local
  alarm tells the people with the wearer to move to open sky (R-27).

## 4. Credits

1 credit per 50 bytes or part of 50, sent or received; an empty mailbox
check also costs 1 credit (D-08, checked 2026-11-18). Every uplink is
exactly 50 bytes, so one message costs one credit. A typical escalated
3-hour run uses 5–8 uplink credits. Downlinks (16 bytes) cost 1 credit each
on the receiving side.
