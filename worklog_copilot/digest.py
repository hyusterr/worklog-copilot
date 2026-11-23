"""Weekly digest: rule-based signals + an LLM summary, rendered as Markdown."""
from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field

from . import llm
from .models import Entry
from .signals import PersonWeek, weekly_signals


class Cited(BaseModel):
    text: str = Field(description="One short sentence, in Traditional Chinese")
    source_ids: list[str] = Field(description="ids of the log entries that support this sentence")


class PersonDigest(BaseModel):
    author: str
    progress: list[Cited] = Field(description="What moved forward this week")
    blockers: list[Cited] = Field(description="Problems, open questions, things the mentor should act on")
    next_steps: list[Cited]
    mentor_action: str = Field(description="One concrete suggestion for the mentor, or empty")


class WeeklyDigest(BaseModel):
    people: list[PersonDigest]


SYSTEM = """You write a weekly digest of intern work logs for their research mentor.
Rules:
- Use only the log entries provided. Every sentence must cite the entry ids it is based on.
- If an intern has no entries, give empty lists. Do not guess what they did.
- Blockers include failures or limits mentioned inside 'Done' items, not only 'Discuss'.
- Write in Traditional Chinese, short and concrete; keep technical terms in English."""


def _cited(d: WeeklyDigest):
    for p in d.people:
        for c in p.progress + p.blockers + p.next_steps:
            yield from c.source_ids


def build_prompt(signals: dict[str, PersonWeek], week_start: date) -> tuple[str, set[str]]:
    ids: set[str] = set()
    parts = [f"Week: {week_start} to {week_start + timedelta(6)}"]
    for a, pw in signals.items():
        parts.append(f"\n### Intern: {a} (logged days: {pw.logged_days}, "
                     f"hours: {pw.hours if pw.hours is not None else 'not recorded'})")
        if not pw.entries:
            parts.append("(no entries this week)")
        for e in pw.entries:
            ids.add(e.id)
            parts.append(e.as_text())
    return "\n".join(parts), ids


def generate(entries: list[Entry], week_start: date, roster: list[str],
             use_llm: bool | None = None) -> tuple[str, dict[str, PersonWeek], list[str]]:
    """Return (markdown, signals, warnings)."""
    signals = weekly_signals(entries, week_start, roster)
    warnings: list[str] = []
    digest: WeeklyDigest | None = None
    if use_llm is None:
        use_llm = llm.available()
    if use_llm and any(pw.entries for pw in signals.values()):
        prompt, ids = build_prompt(signals, week_start)
        try:
            digest = llm.ask(SYSTEM, prompt, WeeklyDigest, ids, _cited)
        except llm.LLMError as e:
            warnings.append(f"LLM 摘要失敗，改用規則版週報：{e}")
    return render(signals, digest, week_start, warnings), signals, warnings


def render(signals: dict[str, PersonWeek], digest: WeeklyDigest | None,
           week_start: date, warnings: list[str]) -> str:
    by_author = {p.author: p for p in digest.people} if digest else {}
    lines = [f"# 實習生週報 {week_start} ~ {week_start + timedelta(6)}", ""]
    for w in warnings:
        lines.append(f"> ⚠️ {w}")
    if warnings:
        lines.append("")
    lines += ["| 實習生 | 有寫日誌天數 | 工時 | 警示 |", "|---|---|---|---|"]
    for a, pw in signals.items():
        h = f"{pw.hours:g}" if pw.hours is not None else "未記錄"
        lines.append(f"| {a} | {pw.logged_days} | {h} | {'；'.join(pw.alerts) or '無'} |")
    for a, pw in signals.items():
        lines += ["", f"## {a}"]
        p = by_author.get(a)
        if p:
            for title, items in (("進度", p.progress), ("卡關", p.blockers), ("下一步", p.next_steps)):
                if items:
                    lines.append(f"**{title}**")
                    lines += [f"- {c.text} <sub>{', '.join(_short(i) for i in c.source_ids)}</sub>"
                              for c in items]
            if p.mentor_action:
                lines.append(f"**建議 mentor**：{p.mentor_action}")
        else:
            if not pw.entries:
                lines.append("本週沒有日誌。")
            for e in pw.entries:
                lines.append(f"- {e.raw_date}：" + "；".join(t.text for t in e.done[:4]))
            if pw.blockers:
                lines.append("**可能的卡關（規則偵測）**")
                lines += [f"- {t} <sub>{_short(i)}</sub>" for t, i in pw.blockers]
    return "\n".join(lines) + "\n"


def _short(entry_id: str) -> str:
    """'repo@branch:path#L12' -> 'path#L12'"""
    return entry_id.split(":", 1)[-1]
