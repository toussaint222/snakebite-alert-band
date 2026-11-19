"""Responder checklist: payload class + families -> what to carry and reminders.

Research demonstrator — not a medical device. All wording comes from
checklist.json (PLACEHOLDER until a toxinologist supplies it, R-08); this
module only selects and orders it.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, "checklist.json")


def load(path=DEFAULT):
    with open(path) as f:
        return json.load(f)


def build(cfg, payload_class, families):
    """Returns {class, label, carry: [..], reminders: [..], status, region}."""
    carry, reminders = [], []
    if payload_class == "BROAD" or not families:
        b = cfg["broad"]
        label = b["label"]
        carry.append(b["carry"])
        reminders += b["reminders"]
    else:
        label = "Family-matched: " + ", ".join(families)
        for f in families:
            entry = cfg["families"].get(f)
            if entry:
                carry.append(entry["carry"])
                reminders += entry["reminders"]
    reminders += cfg["always"]
    seen, uniq = set(), []
    for r in reminders:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return {"payload_class": payload_class, "label": label, "carry": carry,
            "reminders": uniq, "status": cfg.get("status"), "region": cfg.get("region")}
