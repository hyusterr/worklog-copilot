"""Data structures shared by every stage of the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


@dataclass
class SourceRef:
    """Where an entry came from. Every claim in a digest or answer must point to one."""
    repo: str
    branch: str
    path: str
    line: int

    def key(self) -> str:
        return f"{self.repo}@{self.branch}:{self.path}#L{self.line}"


@dataclass
class Task:
    text: str
    hours: Optional[float] = None


@dataclass
class Entry:
    """One dated section of a work log (one '## <date>' block)."""
    author: str
    raw_date: str
    date_start: Optional[date]
    date_end: Optional[date]
    source: SourceRef
    stage: list[str] = field(default_factory=list)
    done: list[Task] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)
    discuss: list[str] = field(default_factory=list)
    other: dict[str, list[str]] = field(default_factory=dict)
    note: str = ""
    issues: list[str] = field(default_factory=list)  # parse problems, kept for human review

    @property
    def id(self) -> str:
        return self.source.key()

    @property
    def hours(self) -> Optional[float]:
        hs = [t.hours for t in self.done if t.hours is not None]
        return sum(hs) if hs else None

    @property
    def open_questions(self) -> list[str]:
        return [d for d in self.discuss if not is_empty_marker(d)]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        d["date_start"] = self.date_start.isoformat() if self.date_start else None
        d["date_end"] = self.date_end.isoformat() if self.date_end else None
        return d

    def as_text(self) -> str:
        """Compact plain-text rendering used for prompts and the search index."""
        parts = [f"[{self.id}] {self.author} {self.raw_date}"]
        if self.stage:
            parts.append("Stage: " + "; ".join(self.stage))
        if self.done:
            parts.append("Done: " + "; ".join(
                (f"[{t.hours}h] " if t.hours is not None else "") + t.text for t in self.done))
        if self.todos:
            parts.append("TODO: " + "; ".join(self.todos))
        if self.open_questions:
            parts.append("Discuss: " + "; ".join(self.open_questions))
        for k, v in self.other.items():
            parts.append(f"{k}: " + "; ".join(v))
        return "\n".join(parts)


EMPTY_MARKERS = {"none", "n/a", "na", "nothing", "no", "-", "無", "沒有", "暫無"}


def is_empty_marker(s: str) -> bool:
    return s.strip().strip(".").lower() in EMPTY_MARKERS or not s.strip()
