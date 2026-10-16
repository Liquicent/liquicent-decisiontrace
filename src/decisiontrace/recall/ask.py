"""``dt ask``: natural-language questions over the store.

Without an API key it answers from structured filters parsed out of the question (time
window, outcome, exceptions, denials, approvals, failed rules, cost) plus full-text search.
With ``--llm`` and Anthropic credentials, Claude writes the answer from the matching,
already-redacted decisions -- nothing else leaves the machine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from decisiontrace.model import DecisionTrace
from decisiontrace.recall.precedent import precedent_view, search
from decisiontrace.recall.text import tokens
from decisiontrace.store import Store
from decisiontrace.views import current_outcome

FILTER_WORDS = {
    "today",
    "yesterday",
    "week",
    "month",
    "days",
    "reverted",
    "undone",
    "denied",
    "rejected",
    "blocked",
    "exception",
    "exceptions",
    "waived",
    "override",
    "overridden",
    "approved",
    "approval",
    "approvals",
    "failed",
    "fail",
    "cost",
    "expensive",
    "tokens",
    "many",
    "count",
    "number",
    "decisions",
    "recent",
    "latest",
    "list",
    "show",
    "all",
    "any",
    "need",
    "needed",
    "needs",
    "required",
    "got",
    "get",
    "were",
    "made",
}


@dataclass
class Filters:
    since: datetime | None = None
    until: datetime | None = None
    outcome: str | None = None
    needs_exception: bool = False
    needs_rejection: bool = False
    needs_approval: bool = False
    needs_failed_rule: bool = False
    by_cost: bool = False
    count_only: bool = False
    words: list[str] = field(default_factory=list)

    def describe(self) -> str:
        parts = []
        if self.since:
            parts.append(f"since {self.since:%Y-%m-%d}")
        if self.until:
            parts.append(f"before {self.until:%Y-%m-%d}")
        for flag, label in (
            (self.outcome, f"outcome {self.outcome}"),
            (self.needs_exception, "with an exception"),
            (self.needs_rejection, "with a rejected option"),
            (self.needs_approval, "with a human approval"),
            (self.needs_failed_rule, "with a failed rule"),
        ):
            if flag:
                parts.append(label)
        if self.words:
            parts.append("matching " + " ".join(self.words))
        return ", ".join(parts) or "all decisions"


def parse(question: str, now: datetime | None = None) -> Filters:
    q = question.lower()
    now = now or datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    f = Filters()
    if "yesterday" in q:
        f.since, f.until = today - timedelta(days=1), today
    elif "today" in q:
        f.since = today
    elif m := re.search(r"last (\d+) days", q):
        f.since = now - timedelta(days=int(m.group(1)))
    elif "last week" in q:
        f.since, f.until = (
            today - timedelta(days=today.weekday() + 7),
            today - timedelta(days=today.weekday()),
        )
    elif "this week" in q:
        f.since = today - timedelta(days=today.weekday())
    elif "last month" in q:
        first = today.replace(day=1)
        f.since, f.until = (first - timedelta(days=1)).replace(day=1), first
    elif "this month" in q:
        f.since = today.replace(day=1)
    if re.search(r"\b(reverted|undone|rolled back)\b", q):
        f.outcome = "reverted"
    elif re.search(r"\bcomplain", q):
        f.outcome = "complained"
    f.needs_exception = bool(re.search(r"\b(exception|waiv|override)", q))
    f.needs_rejection = bool(re.search(r"\b(denied|rejected|blocked|refused)\b", q))
    f.needs_approval = bool(re.search(r"\b(approv|sign.?off)", q))
    f.needs_failed_rule = bool(
        re.search(r"\b(failed|broke|violat|over the limit|above the limit)", q)
    )
    f.by_cost = bool(re.search(r"\b(cost|expensive|tokens|spend)\b", q))
    f.count_only = bool(re.search(r"\bhow many\b|\bcount\b|\bnumber of\b", q))
    f.words = [w for w in tokens(question) if w not in FILTER_WORDS and not w.isdigit()]
    return f


def _matches(t: DecisionTrace, f: Filters, outcome: str) -> bool:
    started = t.actor_time.started_at
    if f.since and started < f.since:
        return False
    if f.until and started >= f.until:
        return False
    if f.outcome and outcome != f.outcome:
        return False
    if f.needs_exception and not t.exceptions:
        return False
    if f.needs_rejection and not t.alternatives:
        return False
    if f.needs_approval and not any(h.type == "approved" for h in t.human_path or []):
        return False
    return not (f.needs_failed_rule and not any(p.result == "fail" for p in t.policies or []))


def _cost(t: DecisionTrace) -> float:
    c = t.actor_time.cost
    if not c:
        return 0.0
    return c.usd if c.usd is not None else float((c.input_tokens or 0) + 5 * (c.output_tokens or 0))


def find(store: Store, question: str, limit: int = 10) -> tuple[Filters, list[DecisionTrace]]:
    f = parse(question)
    if f.words:
        pool = [h.trace for h in search(store, " ".join(f.words), limit=500)]
    else:
        since = f.since.strftime("%Y-%m-%dT%H:%M:%SZ") if f.since else None
        pool = [
            r
            for r in store.records(record_type="decision", since=since, limit=5000)
            if isinstance(r, DecisionTrace)
        ]
    picked = [t for t in pool if _matches(t, f, current_outcome(t, store.related(t.id)))]
    if f.by_cost:
        picked.sort(key=_cost, reverse=True)
    elif not f.words:
        picked.sort(key=lambda t: t.actor_time.started_at, reverse=True)
    return f, picked if f.count_only else picked[:limit]


def answer_offline(store: Store, question: str, limit: int = 10) -> str:
    f, picked = find(store, question, limit)
    if f.count_only:
        noun = "decision" if len(picked) == 1 else "decisions"
        return f"{len(picked)} {noun} ({f.describe()})."
    if not picked:
        return f"No decisions found ({f.describe()})."
    lines = [f"{len(picked)} decision{'s' if len(picked) != 1 else ''} ({f.describe()}):"]
    for t in picked:
        bits = []
        failed = [p.policy_id for p in t.policies or [] if p.result == "fail"]
        if failed:
            bits.append("failed " + ", ".join(failed))
        for e in t.exceptions or []:
            bits.append(f"waived by {e.granted_by.name or e.granted_by.id}")
        if t.alternatives:
            bits.append(f"{len(t.alternatives)} rejected")
        approvals = [h.actor.name or h.actor.id for h in t.human_path or [] if h.type == "approved"]
        if approvals:
            bits.append("approved by " + ", ".join(approvals))
        bits.append(current_outcome(t, store.related(t.id)))
        when = t.actor_time.started_at.strftime("%Y-%m-%d")
        lines.append(f"  {when}  {t.id[:10]}  {t.intent[:70]}  [{'; '.join(bits)}]")
    lines.append("Run `dt why <id>` for the full account.")
    return "\n".join(lines)


SYSTEM = """You answer questions about an organisation's recorded decisions.
Use only the decision records provided. Cite decision ids (first 10 characters) for every
claim. If the records don't answer the question, say so plainly. Be brief."""


def answer_llm(store: Store, question: str, limit: int = 15) -> str:
    """Answer with Claude from the matching (already redacted) decision records."""
    import json

    import anthropic

    _, picked = find(store, question, limit)
    if not picked:
        picked = [h.trace for h in search(store, question, limit=limit)]
    records: list[dict[str, Any]] = [precedent_view(store, t) for t in picked[:limit]]
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model="claude-opus-5-5",
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[
            {
                "role": "user",
                "content": f"Decision records:\n{json.dumps(records, indent=1)}\n\nQuestion: {question}",
            }
        ],
    )
    if response.stop_reason == "refusal":
        return "The model declined to answer. Run without --llm for the offline answer."
    return "".join(block.text for block in response.content if block.type == "text").strip()
