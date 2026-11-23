"""Rule-based signals computed before any LLM call.

These are deterministic so they can be tested exactly and so the digest still
has the important warnings if the LLM call fails.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .models import Entry

# Blockers are often written inside "Things done" rather than "Need to discuss".
BLOCKER_PATTERNS = re.compile(
    r"\b(fail(ed|s|ing)?|stuck|blocked|error|bug|crash|can(no|')t|unable|"
    r"limit(s)? (hit|reached)|hit .{0,30}limit|budget|OOM|out of memory|timeout|"
    r"not (sure|work(ing)?)|confus\w*|haven't done)\b|卡|失敗|錯誤|不確定|不會",
    re.I)


@dataclass
class PersonWeek:
    author: str
    entries: list[Entry] = field(default_factory=list)
    logged_days: int = 0
    hours: float | None = None
    blockers: list[tuple[str, str]] = field(default_factory=list)   # (text, entry id)
    alerts: list[str] = field(default_factory=list)


def covered_days(e: Entry) -> set[date]:
    if not e.date_start:
        return set()
    end = e.date_end or e.date_start
    return {e.date_start + timedelta(d) for d in range((end - e.date_start).days + 1)}


def weekly_signals(entries: list[Entry], week_start: date, roster: list[str],
                   gap_days: int = 3, stall_entries: int = 3) -> dict[str, PersonWeek]:
    """Signals for the 7 days starting at week_start (normally a Monday)."""
    week_end = week_start + timedelta(days=6)
    out = {a: PersonWeek(a) for a in roster}
    by_author: dict[str, list[Entry]] = {}
    for e in entries:
        by_author.setdefault(e.author, []).append(e)
    for a in roster:
        pw = out[a]
        mine = sorted((e for e in by_author.get(a, []) if e.date_start),
                      key=lambda e: e.date_start)
        pw.entries = [e for e in mine if e.date_start <= week_end and
                      (e.date_end or e.date_start) >= week_start]
        days = set().union(*(covered_days(e) for e in pw.entries)) if pw.entries else set()
        days = {d for d in days if week_start <= d <= week_end}
        pw.logged_days = len(days)
        hs = [e.hours for e in pw.entries if e.hours is not None]
        pw.hours = sum(hs) if hs else None

        for e in pw.entries:
            for q in e.open_questions:
                pw.blockers.append((q, e.id))
            for t in e.done:
                if BLOCKER_PATTERNS.search(t.text):
                    pw.blockers.append((t.text, e.id))

        # alerts
        if not pw.entries:
            last = [e for e in mine if e.date_start < week_start]
            since = f"，最後一筆是 {last[-1].raw_date}" if last else ""
            pw.alerts.append(f"本週沒有任何日誌{since}")
        else:
            workdays = sorted(d for d in (week_start + timedelta(i) for i in range(5)))
            run, worst = 0, 0
            for d in workdays:
                run = 0 if d in days else run + 1
                worst = max(worst, run)
            if worst >= gap_days:
                pw.alerts.append(f"平日連續 {worst} 天沒有日誌")
        recent = [e for e in mine if (e.date_end or e.date_start) <= week_end][-stall_entries:]
        if len(recent) == stall_entries:
            stages = {" ".join(e.stage).strip().lower() for e in recent}
            if len(stages) == 1 and all(not e.done or all(BLOCKER_PATTERNS.search(t.text)
                                                          for t in e.done) for e in recent):
                pw.alerts.append(f"最近 {stall_entries} 筆停在同一階段且沒有完成項目")
    return out
