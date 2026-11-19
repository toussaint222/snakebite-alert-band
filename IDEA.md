# Snakebite alert band — an idea, shared openly

> **Research demonstrator — not a medical device.** This is an idea and a
> software simulation. It has never been used on a person, makes no
> medical claim, and is not a substitute for real emergency care.

## The problem

Snakebite is one of the world's most neglected emergencies. The WHO
estimates about **5.4 million bites a year**, **81,000–138,000 deaths** and
about **400,000 people left with lasting disability**, mostly in rural
areas far from help. What often kills is delay: nobody knows the bite is
serious, nobody knows where the person is, or help arrives with the wrong
thing.

## The idea

A band worn by people who work in snakebite country (rangers, field
researchers, farm workers) that:

1. **Notices** a likely serious bite using two independent signs, never one
   alone: a toxin test result, and body-wide warning signs such as falling
   oxygen or breathing changes.
2. **Guesses the toxin family** (for example nerve-acting or
   blood-acting venom) from the test, as a short code.
3. **Calls for help by satellite** with a tiny fixed-size message (50 bytes:
   who, where, how serious, which family), so it works with no phone
   signal.
4. **Keeps trying** under forest canopy, putting the alert ahead of
   everything else, and **buzzes the wearer** to move to open sky if the
   alert can't get out.
5. Shows a **base station** where help is coming from, what family to
   prepare for, and a checklist written by experts (still to be written).

## What's real and what's sci-fi

| Part | Status |
|---|---|
| Satellite messaging, GPS, pulse oximeter | Exists today and is cheap |
| Alert logic, message format, canopy retries, base dashboard | Built as software and tested in simulation (this repo) |
| A field test strip that tells venom families apart | Research stage |
| A sensor that reads venom through the skin continuously | Sci-fi for now; years of lab research |

So a first version could use a test strip read by a person or a phone
camera, with the sensor as a long-term research goal.

## What's in this repo

A working simulation in plain Python (no installs): the band's decision
logic, the satellite message, a simulated satellite link with canopy
dropouts, a base dashboard in the browser, and 14 example scenarios. Start
with the [README](README.md). Every clinical number in it is a placeholder,
not a medical value.

## Open questions, if you know the field

- Would knowing the venom family before leaving change what a responder
  carries or does?
- Does a family-level field test strip exist, or could it?
- Would people actually wear and charge a band like this?

Ideas, criticism and pointers to people working on this are welcome.

## Sources

WHO snakebite envenoming fact sheet:
https://www.who.int/en/news-room/fact-sheets/detail/snakebite-envenoming
