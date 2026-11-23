"""Command line entry point.

  python -m worklog_copilot digest  --dir demo/logs --week 2026-07-13 --no-llm
  python -m worklog_copilot parse   --local ../.. [--json out.json]
  python -m worklog_copilot digest  --repo owner/name --week 2026-07-20 [--out digest.md] [--issue] [--email] [--sheet]
  python -m worklog_copilot ask     --local ../.. "去年誰做過 highlighter 的 baseline？"
  python -m worklog_copilot backtest --local ../.. --gold eval/gold.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

from . import deliver
from .digest import generate
from .ingest import DirSource, GitHubSource, LocalGitSource
from .rag import Index


def load(args):
    sources = [LocalGitSource(p) for p in (args.local or [])] + \
              [GitHubSource(r) for r in (args.repo or [])] + \
              [DirSource(p) for p in (args.dir or [])]
    if not sources:
        sys.exit("give --dir <folder>, --local <clone> or --repo <owner/name>")
    entries, errors = [], []
    for s in sources:
        res = s.collect()
        errors += res.errors
        mentor = tuple(args.mentor or ())
        entries += res.entries(mentor_branches=mentor,
                               mentor_files=tuple(f"{m}.work.log" for m in mentor))
    for e in errors:
        print(f"[ingest warning] {e}", file=sys.stderr)
    return entries


def last_monday(today: date | None = None) -> date:
    today = today or date.today()
    return today - timedelta(days=today.weekday() + 7)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="worklog_copilot")
    ap.add_argument("cmd", choices=["parse", "digest", "ask", "backtest"])
    ap.add_argument("question", nargs="?")
    ap.add_argument("--local", action="append", help="path to a local clone (repeatable)")
    ap.add_argument("--repo", action="append", help="owner/name on GitHub (repeatable)")
    ap.add_argument("--mentor", action="append",
                    help="mentor's branch name; their log (copied into intern branches) is excluded")
    ap.add_argument("--dir", action="append", help="folder with one log file per intern (repeatable)")
    ap.add_argument("--week", help="Monday of the week to summarise (default: last week)")
    ap.add_argument("--out", default="out/digest.md")
    ap.add_argument("--json")
    ap.add_argument("--gold", default="eval/gold.jsonl")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--issue", action="store_true")
    ap.add_argument("--email", action="store_true")
    ap.add_argument("--sheet", action="store_true")
    a = ap.parse_args(argv)
    entries = load(a)

    if a.cmd == "parse":
        flagged = [e for e in entries if e.issues]
        print(f"{len(entries)} entries, {len(flagged)} need review")
        for e in flagged:
            print(f"  {e.id}: {'; '.join(e.issues)}")
        if a.json:
            with open(a.json, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in entries], f, ensure_ascii=False, indent=1)
    elif a.cmd == "digest":
        week = date.fromisoformat(a.week) if a.week else last_monday()
        roster = sorted({e.author for e in entries})
        md, signals, warnings = generate(entries, week, roster, use_llm=False if a.no_llm else None)
        print(deliver.to_file(md, a.out))
        title = f"實習生週報 {week}"
        jobs = []
        if a.issue:
            jobs.append(lambda: deliver.to_github_issue(md, title))
        if a.email:
            jobs.append(lambda: deliver.to_email(md, title))
        if a.sheet:
            rows = [{"week": str(week), "intern": k, "logged_days": v.logged_days,
                     "hours": v.hours, "alerts": "；".join(v.alerts)} for k, v in signals.items()]
            jobs.append(lambda: deliver.to_sheet_webhook(rows))
        failed = 0
        for job in jobs:
            try:
                print(job())
            except Exception as e:  # one channel failing must not hide the others
                failed += 1
                print(f"[deliver error] {e}", file=sys.stderr)
        return 1 if failed else 0
    elif a.cmd == "ask":
        if not a.question:
            sys.exit("ask needs a question")
        ans = Index(entries).ask(a.question)
        print(ans.answer)
        for i in ans.source_ids:
            print("  source:", i)
    elif a.cmd == "backtest":
        from .backtest import run
        print(json.dumps(run(entries, a.gold, use_llm=not a.no_llm), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
