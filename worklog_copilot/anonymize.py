"""Replace intern names and personal notes before anything leaves the lab.

Used for public demos and portfolio material. Real logs stay in the private repo.
"""
from __future__ import annotations

import copy
import re

from .models import Entry


def anonymize(entries: list[Entry], extra_names: dict[str, str] | None = None,
              drop_notes: bool = True) -> list[Entry]:
    authors = sorted({e.author for e in entries})
    alias = {a: f"Intern {chr(ord('A') + i)}" for i, a in enumerate(authors)}
    alias.update(extra_names or {})
    pat = re.compile("|".join(re.escape(k) for k in sorted(alias, key=len, reverse=True)), re.I) \
        if alias else None

    lower = {k.lower(): v for k, v in alias.items()}

    def scrub(s: str) -> str:
        return pat.sub(lambda m: lower[m.group(0).lower()], s) if pat else s

    out = []
    for e in entries:
        e2 = copy.deepcopy(e)
        e2.author = alias.get(e.author, e.author)
        e2.source.branch = scrub(e.source.branch)
        e2.source.path = scrub(e.source.path)
        e2.source.repo = "lab/worklogs"
        if drop_notes:
            e2.note = ""
            e2.raw_date = (e.date_start.isoformat() if e.date_start else "unknown-date")
        e2.stage = [scrub(x) for x in e.stage]
        e2.todos = [scrub(x) for x in e.todos]
        e2.discuss = [scrub(x) for x in e.discuss]
        for t in e2.done:
            t.text = scrub(t.text)
        e2.other = {k: [scrub(x) for x in v] for k, v in e.other.items()}
        out.append(e2)
    return out
