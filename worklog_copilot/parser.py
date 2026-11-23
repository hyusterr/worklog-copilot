"""Tolerant parser for the CFDA intern work-log template.

The template is:

    ## 2026.7.1
    ### Stage of my work
    ### Things done today
    - [1 hr] ...
    ### TODOs
    ### Need to discuss

Real logs drift from it in many ways (date ranges, 'X' placeholders, extra
sections, missing sections, padded or unpadded numbers). The parser never
drops an entry: anything it cannot interpret is kept and recorded in
`Entry.issues` so a human can review it.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from .models import Entry, SourceRef, Task

DATE_HEADER = re.compile(r"^##(?!#)\s*(.*)$")
SECTION_HEADER = re.compile(r"^###\s*(.*?)\s*$")
SEPARATOR = re.compile(r"^\s*-{3,}\s*$")
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
HOURS = re.compile(r"^\[\s*([\d.]+)\s*(?:hr|hrs|h|hours?)\s*\]\s*(.*)$", re.I)

# y.m.d with '.', '/', or '-' separators
_YMD = r"(\d{4})[./-](\d{1,2})[./-](\d{1,2}|[xX?])"
FULL = re.compile(rf"^{_YMD}")
# second half of a range: either a full y.m.d, an m.d, or a bare day
RANGE_TAIL = re.compile(
    r"^\s*(?:-|–|~|to|&|,)\s*(?:(\d{4})[./-])?(?:(\d{1,2})[./-])?(\d{1,2})\b")

SECTION_ALIASES = {
    "stage": ("stage",),
    "done": ("things done", "done today", "done"),
    "todos": ("todo", "to do", "next"),
    "discuss": ("need to discuss", "discuss", "question", "blocker"),
}


def classify_section(title: str) -> str:
    t = title.lower()
    for key, needles in SECTION_ALIASES.items():
        if any(n in t for n in needles):
            return key
    return "other"


def _mk(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(raw: str, default_year: Optional[int] = None):
    """Return (start, end, note, issues) for a '## ...' header."""
    issues: list[str] = []
    s = raw.strip()
    m = FULL.match(s)
    if not m:
        issues.append(f"unparseable date header: {raw!r}")
        return None, None, s, issues
    y, mo, d = int(m.group(1)), int(m.group(2)), m.group(3)
    rest = s[m.end():]
    if d in "xX?":
        issues.append(f"placeholder day in date: {raw!r}")
        return None, None, rest.strip(" ()"), issues
    start = _mk(y, mo, int(d))
    if start is None:
        issues.append(f"invalid calendar date: {raw!r}")
        return None, None, rest.strip(" ()"), issues
    end = start
    t = RANGE_TAIL.match(rest)
    if t:
        ty = int(t.group(1)) if t.group(1) else y
        tm = int(t.group(2)) if t.group(2) else mo
        td = int(t.group(3))
        cand = _mk(ty, tm, td)
        if cand and cand >= start and (cand - start).days <= 14:
            end = cand
            rest = rest[t.end():]
        else:
            issues.append(f"suspicious date range: {raw!r}")
    note = rest.strip().strip("()").strip()
    return start, end, note, issues


def parse_log(text: str, author: str, repo: str, branch: str, path: str) -> list[Entry]:
    entries: list[Entry] = []
    cur: Optional[Entry] = None
    section = None
    last: Optional[list] = None   # list that received the previous line (for wrapped lines)
    prev_blank = True
    for lineno, line in enumerate(text.splitlines(), start=1):
        if SEPARATOR.match(line):
            continue
        h = DATE_HEADER.match(line)
        if h:
            start, end, note, issues = parse_date(h.group(1))
            cur = Entry(author=author, raw_date=h.group(1).strip(), date_start=start,
                        date_end=end, source=SourceRef(repo, branch, path, lineno),
                        note=note, issues=list(issues))
            entries.append(cur)
            section, last, prev_blank = None, None, True
            continue
        if cur is None:
            continue  # preamble before the first date
        sh = SECTION_HEADER.match(line)
        if sh:
            section = classify_section(sh.group(1))
            if section == "other":
                section = "other:" + sh.group(1).strip()
            last, prev_blank = None, True
            continue
        content = line.strip()
        if not content:
            prev_blank = True
            continue
        b = BULLET.match(line)
        item = b.group(1).strip() if b else content
        if not b and not prev_blank and last:
            # a wrapped line continues the previous item
            if isinstance(last[-1], Task):
                last[-1].text += " " + item
            else:
                last[-1] = last[-1] + " " + item
            continue
        prev_blank = False
        if section is None:
            cur.issues.append(f"text outside any section at line {lineno}")
            last = cur.other.setdefault("unsectioned", [])
            last.append(item)
        elif section == "done":
            hm = HOURS.match(item)
            try:
                task = Task(hm.group(2).strip(), float(hm.group(1))) if hm else Task(item)
            except ValueError:
                task = Task(item)
            last = cur.done
            last.append(task)
        else:
            last = {"stage": cur.stage, "todos": cur.todos, "discuss": cur.discuss}.get(section)
            if last is None:
                last = cur.other.setdefault(section.split(":", 1)[1], [])
            last.append(item)
    for e in entries:
        if not e.done and not e.stage:
            e.issues.append("entry has no 'Stage' and no 'Things done'")
    return entries
