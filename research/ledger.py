"""The experiment ledger — permanent, append-only, and it records retractions.

Three findings in this project have already been overturned. A ledger that showed only
confirmations would have hidden all three, so `superseded_by` and `retracted` are first-class
fields rather than an afterthought.

Stored as JSON next to the research code so it travels with the repository.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

LEDGER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "experiments.json")

FIELDS = ("id", "date", "hypothesis", "baseline", "variable", "control", "treatment",
          "dataset", "n", "result", "confidence", "decision", "next", "retracted",
          "superseded_by", "commit")


def load(path: str = LEDGER_PATH) -> List[Dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save(entries: List[Dict], path: str = LEDGER_PATH) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp, path)


def upsert(entry: Dict, path: str = LEDGER_PATH) -> List[Dict]:
    """Append or update by id. Never deletes: a superseded entry stays, marked."""
    entries = load(path)
    entry = {k: entry.get(k) for k in FIELDS}
    for i, e in enumerate(entries):
        if e.get("id") == entry["id"]:
            entries[i] = {**e, **{k: v for k, v in entry.items() if v is not None}}
            break
    else:
        entries.append(entry)
    entries.sort(key=lambda e: str(e.get("id")))
    save(entries, path)
    return entries


def get(exp_id: str, path: str = LEDGER_PATH) -> Optional[Dict]:
    for e in load(path):
        if str(e.get("id", "")).upper() == exp_id.upper():
            return e
    return None
