# 03 — Milestones and gates

> **Research demonstrator — not a medical device.**

After each milestone the builder stops, reports what works / what doesn't /
what's next in STATUS.md, and waits for the owner's go-ahead.

| Milestone | Builds | Gate (how it's checked) |
|---|---|---|
| **M0 — Plan** | This docs folder, DECISIONS.md, README skeleton. | Owner approves the plan and rules on (or accepts defaults for) R-01 … R-15. |
| **M1 — Packet + simulator** | `vrw/packet.py`, `trigger.py`, `outbox.py`, `device.py`, `base.py`, `link/sim_sbd.py`, `scenario.py`, CLI, scenarios (the brief's 4 plus 5 more found necessary). | `python3 -m unittest` passes; `python3 -m vrw run-all` prints PASS for every scenario against the expected outcomes in [02 §6](02-TRIGGER-STATE-MACHINE.md); a test asserts every encoded message is ≤ 50 bytes and round-trips exactly. |
| **M2 — Dashboard** | `dashboard/server.py`, static page, `checklist.json` (placeholder content). | Run the elapid scenario with the dashboard open: alert, position, family code and checklist appear, and the simulated time from bite-escalation to dashboard display is < 60 s. A test checks the disclaimer is on every page. |
| **M3 — Sensor stand-ins** | `sensors/vitals.py` (CSV in), `sensors/lateral_flow.py` (image → family code), wired into the state machine. | Contact-only scenario fed by real stand-in inputs stays out of ESCALATED; systemic scenario escalates. Both as automated tests. |
| **M4 — Field hardening** | Hardened queue + retry policy, canopy failure-mode script, battery budget report, FIELD-RUNBOOK.md, optional real-modem driver. | Timed end-to-end field simulation (open field → forest edge) reaching a human responder; times recorded in STATUS.md. |
