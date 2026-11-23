"""Question answering over all past work logs, with citations.

Retrieval is a small BM25 index (no external service, works offline). The
answer step sends only the retrieved entries to Claude and rejects any answer
that cites an entry it was not given. When retrieval finds nothing relevant
the tool says so instead of asking the model to guess.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from pydantic import BaseModel, Field

from . import llm
from .models import Entry

TOKEN = re.compile(r"[a-z0-9][a-z0-9_\-.]*|[一-鿿]", re.I)
STOP = set("a an the and or of to in on for with is are was were be i my we our it this that "
           "today did do done have has had by at as from".split())


def tokenize(text: str) -> list[str]:
    toks = [t.lower().strip(".-") for t in TOKEN.findall(text)]
    return [t for t in toks if t and t not in STOP]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(tokenize(d)) for d in docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = sum(self.len) / max(len(self.len), 1)
        df = Counter(t for c in self.tf for t in c)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, dl in zip(self.tf, self.len):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
            out.append(s)
        return out


class Answer(BaseModel):
    answer: str = Field(description="Answer in Traditional Chinese; say clearly if the logs do not contain it")
    found: bool = Field(description="False when the provided entries do not answer the question")
    source_ids: list[str] = Field(description="ids of entries the answer is based on")


SYSTEM = """You answer questions about past intern work logs of a financial NLP lab.
Use only the entries provided. Cite the ids you used. If the entries do not
contain the answer, set found=false and say what is missing; never fill gaps
from general knowledge."""


class Index:
    def __init__(self, entries: list[Entry]):
        self.entries = entries
        self.bm25 = BM25([e.as_text() for e in entries])

    def search(self, query: str, k: int = 6, min_score: float = 1.0) -> list[tuple[Entry, float]]:
        s = self.bm25.scores(query)
        ranked = sorted(range(len(s)), key=lambda i: -s[i])[:k]
        return [(self.entries[i], s[i]) for i in ranked if s[i] >= min_score]

    def ask(self, question: str, k: int = 6) -> Answer:
        hits = self.search(question, k)
        if not hits:
            return Answer(answer="日誌裡找不到相關紀錄。", found=False, source_ids=[])
        if not llm.available():
            return Answer(answer="（未設定 ANTHROPIC_API_KEY，只列出最相關的紀錄）\n" +
                          "\n".join(f"- {e.author} {e.raw_date}" for e, _ in hits),
                          found=True, source_ids=[e.id for e, _ in hits])
        ctx = "\n\n".join(e.as_text() for e, _ in hits)
        return llm.ask(SYSTEM, f"Entries:\n{ctx}\n\nQuestion: {question}", Answer,
                       {e.id for e, _ in hits}, lambda a: a.source_ids, effort="low")
