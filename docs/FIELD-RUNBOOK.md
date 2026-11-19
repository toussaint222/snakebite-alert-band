# Field runbook — v1 demonstrator

> **Research demonstrator — not a medical device.** This runbook is for
> demonstrating the system in simulation and with drug-free trainer
> hardware only. It is not guidance for treating a snakebite. Nothing here
> replaces evacuation, local medical services or a toxinologist's advice.

## 1. What a field demo is

A laptop runs the base dashboard and plays a scripted bite. Every message
in v1 travels over the **simulated** satellite link. A driver for a real
RockBLOCK-class modem exists (`vrw/link/rockblock.py`), but no command
uses it yet and it has never been tested on hardware (D-23).
Nobody is bitten, nothing is injected, and no real venom or drug is used.
Any auto-injector in the demo is a **trainer** with no needle and no drug.

## 2. Roles

| Role | Does |
|---|---|
| **Wearer** (actor) | Wears the trainer band, walks the route, follows the companion's instructions. |
| **Companion** | Stays with the wearer and carries them to open sky when the band escalates (§5). |
| **Base operator** | Watches the dashboard, decides to dispatch, records times, closes the alert when the responder is on scene. |
| **Responder** | Carries the payload kit for the class the dashboard shows (trainer kit only) to the reported position. |
| **Safety lead** | Can stop the demo at any time. Holds the real emergency plan for the people taking part (§7). |

## 3. Before going out

1. On the base laptop: `cd ~/Documents/VenomResponse` then `python3 -m unittest`. Every test must pass.
2. `python3 -m vrw run-all`: every scenario PASS.
3. Start the dashboard (`python3 -m dashboard`) and open http://127.0.0.1:8765. Check that the yellow
   "Research demonstrator — not a medical device" banner shows.
4. Charge everything. Read `docs/BATTERY-BUDGET.md`: under canopy the radio dominates.
5. A real modem is not part of a v1 demo. Before it ever is: test the driver on the bench, and confirm
   line rental and credits (1 credit per 50 bytes; an empty mailbox check also costs 1).
6. Brief everyone on §5 and §7.

## 4. Running the demo

Rehearse indoors first, entirely simulated:

```bash
cd ~/Documents/VenomResponse && python3 -m vrw field scenarios/field_open_to_forest.json
```

Live on the dashboard (you are the base and close the alert yourself):

```bash
cd ~/Documents/VenomResponse && python3 -m vrw demo scenarios/field_open_to_forest.json
```

Record for every run: bite time, escalation, ALERT shown at base, responder departure, trailhead,
on scene, close confirmed by the band. The `field` command prints these.

## 5. Canopy rule (the most important habit)

Dense canopy blocks both the satellite link and GPS. The band keeps every
message and retries. If an alert has not got out after 5 minutes, the
band's **local alarm** (buzzer and light) comes on (R-27; simulated in v1,
shown as "LOCAL ALARM ON" in the timeline). It goes off once the alert is
sent.

- If the local alarm is on, the band has escalated, or anyone suspects a
  bite: **move the wearer to open sky**: a clearing, riverbank, ridge or road. Stay there.
- In open sky, an ALERT usually reaches base within about a minute
  (simulated: 10–60 s latency plus retries).
- The base sees how old the event is and how old the position is. A
  position over 15 minutes old means the responder plans to search.

## 6. Responder and drone doctrine

- A **ground responder is the default.** They carry the pre-made payload
  class the dashboard names. The dashboard checklist is placeholder content
  until a toxinologist writes it.
- A **drone**, if used at all, carries the kit **to a clearing or to the
  responder.** It never descends through canopy and never treats anyone.
- **A human administers** anything that is administered. In v1, that means
  only a **trainer** device on a dummy or a willing actor's clothing.
- If the local team cancels after a dispatch, the dashboard says so. Recall
  is the base operator's decision (R-18).

## 7. Real emergency plan (separate from the demo)

The demo system must never be anyone's real safety net. For every outing,
the safety lead holds a real plan: an independent satellite messenger or
phone, the nearest hospital that stocks antivenom and the route there,
evacuation contacts, and first-aid training. Stop the demo for any real
incident.

## 8. After the run

- Copy the dashboard message log and the `field` timing table into your notes.
- Note the canopy durations and where the link dropped.
- Any surprise in behaviour goes into DECISIONS.md as a new R-item.
