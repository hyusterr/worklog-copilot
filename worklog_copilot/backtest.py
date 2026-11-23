"""Backtest the weekly digest against hand-labelled past weeks.

Gold file (JSON lines), one object per intern-week:

  {"author": "amber", "week": "2026-07-13",
   "blockers": [["rate limit", "quota"], ["tokenizer"]],   # each = keywords, any one must match
   "alerts":   ["沒有任何日誌"],                          # substrings expected in the alerts
   "no_alerts": false}                                     # true = expect no alert at all

Error types reported (the three the Garena spec asks to test for):
  missed     - a labelled blocker that no digest blocker mentions
  misread    - a digest item that cites an entry from a different intern or week
  fabricated - a digest item that cites nothing, or cites ids that were not provided,
               or shares almost no words with the entries it cites
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from . import llm
from .digest import WeeklyDigest, build_prompt, SYSTEM, _cited
from .models import Entry
from .rag import tokenize
from .signals import weekly_signals


def _match(keywords: list[str], text: str) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def run(entries: list[Entry], gold_path: str, use_llm: bool = True) -> dict:
    gold = [json.loads(l) for l in open(gold_path, encoding="utf-8") if l.strip()]
    by_id = {e.id: e for e in entries}
    use_llm = use_llm and llm.available()
    totals = {"cases": 0, "gold_blockers": 0, "missed": 0, "digest_items": 0,
              "misread": 0, "fabricated": 0, "alert_checks": 0, "alert_errors": 0}
    cases = []
    for g in gold:
        week = date.fromisoformat(g["week"])
        sig = weekly_signals(entries, week, [g["author"]])[g["author"]]
        case = {"author": g["author"], "week": g["week"], "missed": [], "misread": [],
                "fabricated": [], "alert_errors": []}
        # blockers the system reports, with the text of what they cite
        reported: list[tuple[str, list[str]]] = [(t, [i]) for t, i in sig.blockers]
        items: list[tuple[str, list[str]]] = []
        if use_llm and sig.entries:
            prompt, ids = build_prompt({g["author"]: sig}, week)
            try:
                d: WeeklyDigest = llm.ask(SYSTEM, prompt, WeeklyDigest, ids, _cited)
                reported = []
                for p in d.people:
                    reported += [(c.text, c.source_ids) for c in p.blockers]
                    items += [(c.text, c.source_ids) for c in p.progress + p.blockers + p.next_steps]
            except llm.LLMError as e:
                case["llm_error"] = str(e)
        else:
            items = reported
        # missed
        for kw in g.get("blockers", []):
            totals["gold_blockers"] += 1
            hay = " ".join(t + " " + " ".join(by_id[i].as_text() for i in ids if i in by_id)
                           for t, ids in reported)
            if not _match(kw, hay):
                case["missed"].append(kw)
        # misread / fabricated
        wk_end = week + timedelta(6)
        for text, ids in items:
            totals["digest_items"] += 1
            cited = [by_id.get(i) for i in ids]
            if not ids or any(c is None for c in cited):
                case["fabricated"].append(text)
                continue
            if any(c.author != g["author"] or not c.date_start or c.date_start > wk_end
                   or (c.date_end or c.date_start) < week for c in cited):
                case["misread"].append(text)
                continue
            src = set(tokenize(" ".join(c.as_text() for c in cited)))
            words = [w for w in tokenize(text) if len(w) > 1 and not w.isdigit()]
            if words and sum(w in src for w in words) / len(words) < 0.2:
                case["fabricated"].append(text)
        # alerts
        alerts = " ".join(sig.alerts)
        for a in g.get("alerts", []):
            totals["alert_checks"] += 1
            if a not in alerts:
                case["alert_errors"].append(f"expected alert containing {a!r}")
        if g.get("no_alerts"):
            totals["alert_checks"] += 1
            if sig.alerts:
                case["alert_errors"].append(f"unexpected alerts: {sig.alerts}")
        for k in ("missed", "misread", "fabricated", "alert_errors"):
            totals[k] += len(case[k])
        case["passed"] = not any(case[k] for k in ("missed", "misread", "fabricated", "alert_errors"))
        totals["cases"] += 1
        cases.append(case)
    totals["passed"] = sum(c["passed"] for c in cases)
    totals["mode"] = "llm" if use_llm else "rules-only"
    totals["recall"] = round(1 - totals["missed"] / max(totals["gold_blockers"], 1), 3)
    return {"summary": totals, "cases": cases}
