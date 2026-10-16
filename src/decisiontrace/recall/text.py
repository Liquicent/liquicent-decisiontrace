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


def refs_for(trace: DecisionTrace) -> set[tuple[str, str]]:
    """(kind, ref) pairs a decision can be looked up by: files touched/read and commits."""
    out: set[tuple[str, str]] = set()
    for a in trace.actions or []:
        if a.target and a.type in ("file_write", "memory_write"):
            out.add(("file", a.target))
    if trace.context:
        for item in trace.context.inputs or []:
            if item.type == "file":
                out.add(("file_read", item.ref))
        if trace.context.state_before and trace.context.state_before.type == "git.commit":
            out.add(("commit_before", trace.context.state_before.ref.lower()))
    if trace.state_after and trace.state_after.type == "git.commit":
        out.add(("commit", trace.state_after.ref.lower()))
    return out
