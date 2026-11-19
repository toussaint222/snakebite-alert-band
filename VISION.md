# Vision — Venom-Response Wearable

> **Research demonstrator — not a medical device.** This is the builder's
> product vision and recommendation, written after v1 (M0–M4). It makes no
> medical claim. No patent is planned (DECISIONS R-29).
> It is not a draft of any funding application.

Written by the builder under the owner's instruction "take ownership of
vision" (2026-11-18). Every recommendation here is the builder's; the
owner can overrule any of it. Nothing here commits money, dates or
partners.

## 1. The one sentence

**Nobody should die of a snakebite because help didn't know, didn't know
where, or brought the wrong thing.**

## 2. The problem, honestly

- The WHO estimates about **5.4 million snakebites** a year, **1.8–2.7
  million envenomings**, about **81,000–138,000 deaths** and about **400,000
  permanent disabilities**, and lists snakebite envenoming as a priority
  neglected tropical disease (2017). Its strategy aims to **halve deaths
  and disability by 2030**. Official counts likely undercount: one India
  study estimated deaths at over 30 times the official figure.
- The killer is mostly **time and access**: reaching the right antivenom
  in time, with the right care. The project cannot fix antivenom supply,
  and should not pretend to.
- What it can shorten is the **information delay**: knowing that a bite
  is serious, how serious, which toxin family is involved, where the person
  is, and getting that to someone who can act, even from under canopy.

## 3. The fork, and my recommendation

v1 exposed a real choice.

| | **A. Dispatch layer first** | **B. Sensor first** |
|---|---|---|
| What it is | The two-signal triage logic, store-and-forward messaging, base dashboard and responder checklist, running on equipment that exists today: a satellite messenger or modem, a commercial pulse oximeter, and a test strip read by a person or a phone camera | A wearable that senses venom in the body continuously and calls for help by itself |
| Works today? | Mostly yes; it needs a family-level test strip and expert-written content | No; continuous in-body venom sensing has not been shown (X-01) |
| Who can use it | Field teams, remote clinics and expeditions running a dispatch desk | Eventually anyone in a snakebite region |
| Risk | Lower technical risk; the value has to be shown against "just press SOS" | High technical and regulatory risk; years of partner research |
| Time to something real | Months | Years |

**I recommend A, with B as the long-term research track it leads into.**

- A uses everything v1 already built. The trigger logic does not care
  whether a reading comes from a microneedle or from a person typing in
  a strip result.
- A gives the sensor research a real system to plug into, and real field
  data to aim at.
- For B, the sensor is the long pole, and partners own that science. The
  project's job is to be the best place to put a sensor once it exists.
- **No patent (owner's ruling R-29).** The system design (two-signal
  escalation with a toxin-family code, a fixed-size satellite message,
  store-and-forward with alert priority, family-matched dispatch, canopy
  behaviour and the local stuck-alert alarm) does not depend on the sensor
  technology. Without a patent it can be shared openly, which may make
  partners easier to find.

## 4. Assumptions, riskiest first, each with its cheapest test

| # | Assumption | Why it matters | Cheapest test |
|---|---|---|---|
| 1 | Knowing the toxin family before the responder leaves changes what they carry or do, in a way that saves time or harm | It is the core value over a plain SOS button | One conversation with a toxinologist about whether family and level change the response in a real setting. |
| 2 | A family-level test strip that a person or camera can read in the field can exist at a usable price | Track A needs it | A literature and supplier scan, plus the same toxinologist conversation |
| 3 | People in the target setting will wear and maintain a band | No wear, no system | Ask 5–10 people who work in snakebite regions (rangers, field researchers, farm co-ops) |
| 4 | Satellite works often enough near where bites happen | Canopy is the norm in some places | A bench and outdoor test with one real modem, timing sends under tree cover (needs the owner's go-ahead and spend) |
| 5 | Venom reaches the skin fluid early enough to give warning | Track B depends on it | Partner question only; not something to test ourselves |
| 6 | A responder can reach the person in time to matter | It caps the value of everything else | Real dispatch data from a partner programme to replace the R-28 assumptions |

## 5. Roadmap (recommendation, no dates)

Each phase says what it needs from the owner. I won't start any phase's
build work without the owner's yes.

**Phase 0 — v1 demonstrator (done).** Software running in simulation,
88 tests passing, a full system description. M4 approved and R-25 to
R-28 confirmed by the owner on 2026-11-19.

**Phase 1 — Validate (no hardware, no spend).**
- A one-page, plain-language brief for a toxinologist and a
  sensor researcher (the builder can draft it), and the conversations in
  §4 rows 1–3.
- Software, if wanted: a **manual entry mode**, where a companion types or
  photographs the strip result into a phone app or the band. This is the
  first real step of Track A and needs no new hardware.
- Needs from the owner: introductions and a yes to the brief.

**Phase 2 — Bench prototype (small spend, the owner's call).**
- One RockBLOCK-class modem, a trainer band and a commercial pulse
  oximeter: test the driver on real hardware (D-23), measure real power
  figures (D-22), and time sends under tree cover.
- The buzzer and light for the stuck-alert alarm (R-27).
- Needs from the owner: a budget decision and a safety lead for any
  outdoor test.

**Phase 3 — Partner research (partners own the science).**
- A family-level test strip and the microneedle sensor (X-01) with
  research partners. Any work with animals or people happens only under
  the partner's approvals, never in this project.
- Needs from the owner: partnership decisions and agreements.

**Phase 4 — Pilot with an existing programme (partners own the clinical side).**
- A dispatch-desk pilot with a snakebite programme or field organisation,
  under their ethics approvals, starting with Track A.
- Needs from the owner: everything about partners, regulation and money.

## 6. What this project will never do

- Make, design, mix or dose a drug, or tell anyone how to treat a bite.
- Use real venom or real patients, or do anything clinical, outside a
  partner's approved study.
- Send a drone down through canopy, or have a drone treat anyone.
- Claim it diagnoses, treats or saves lives before evidence says so.
- Replace a real emergency plan. It is an extra layer of information.

## 7. How decisions get made from here

- The builder makes product and engineering calls, logs each one with its
  reasoning in DECISIONS.md, and marks it pending the owner's confirmation.
- These stay with the owner: anything touching real people, venom, drugs
  or money; publishing or sharing the project; anything submitted under the
  owner's name; and turning any clinical PLACEHOLDER into a real value,
  which needs a named expert.

## Sources

Figures in §2 are from the WHO snakebite envenoming fact sheet
(https://www.who.int/en/news-room/fact-sheets/detail/snakebite-envenoming),
the WHO 2019 strategy news release
(https://www.who.int/news-room/detail/06-05-2019-snakebite-who-targets-50-reduction-in-deaths-and-disabilities),
and WHO EMRO (https://www.emro.who.int/media/news/better-snakebite-data-needed-to-save-lives-limbs.html),
checked 2026-11-18. Research-status points (X-01, X-02) are the builder's
general knowledge, not checked against current literature.
