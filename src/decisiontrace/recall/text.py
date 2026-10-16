"""Searchable text for a decision: everything that explains *why*, nothing that's an id."""

from __future__ import annotations

import re

from decisiontrace.model import DecisionTrace

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "last",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "should",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "did",
        "done",
        "handle",
        "handled",
        "deal",
        "dealt",
        "time",
        "times",
        "before",
        "previous",
        "previously",
        "decided",
        "decision",
        "decisions",
    ]
)
_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


def index_text(trace: DecisionTrace) -> str:
    parts: list[str] = [trace.intent, trace.decision_kind.replace(".", " ")]
    parts += [c.replace(".", " ") for c in trace.capabilities or []]
    if trace.context:
        if trace.context.workflow:
            parts.append(trace.context.workflow.replace(".", " "))
        for item in trace.context.inputs or []:
            parts += [item.type, item.summary or ""]
    for p in trace.policies or []:
        parts += [_split_id(p.policy_id), p.result, p.detail or ""]
    for e in trace.exceptions or []:
        parts += ["exception waived override", _split_id(e.policy_id), e.reason]
    for a in trace.actions or []:
        parts += [a.name, a.summary or "", a.target or ""]
    for x in trace.alternatives or []:
        parts += ["rejected", x.action.summary or x.action.name, x.reason or ""]
    for h in trace.human_path or []:
        parts += [h.type, h.actor.role or "", h.detail or ""]
    if trace.outcome:
        parts.append(trace.outcome.status)
    return " ".join(p for p in parts if p)


def _split_id(policy_id: str) -> str:
    return re.sub(r"[._:()*/\-]+", " ", policy_id)


def fts_query(text: str) -> str | None:
    """OR-query of the meaningful words (prefix-matched) for SQLite FTS5."""
    words = list(dict.fromkeys(tokens(text)))
    if not words:
        return None
    return " OR ".join(f'"{w}"*' for w in words[:24])
