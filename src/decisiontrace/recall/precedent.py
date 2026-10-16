"""Find precedents and present them with their rule / exception / approval path."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from decisiontrace.model import CorrectionRecord, DecisionTrace
from decisiontrace.recall.similarity import Score, Weights, policy_ids, similarity
from decisiontrace.store import Store
from decisiontrace.views import apply_corrections, current_outcome


@dataclass
class Hit:
    trace: DecisionTrace
    score: float
    strength: str = "match"
    components: dict[str, float] = field(default_factory=dict)


def search(store: Store, text: str, limit: int = 5, kind: str | None = None) -> list[Hit]:
    """Free-text recall: BM25 relevance, with a small preference for recent decisions."""
    raw = store.search(text, limit=max(limit * 4, 20), decision_kind=kind)
    if not raw:
        return []
    best = max(-rank for _, rank in raw) or 1.0
    now = datetime.now(UTC)
    hits = []
    for trace, rank in raw:
        relevance = max(0.0, -rank) / best
        days = max(0.0, (now - trace.actor_time.started_at).total_seconds() / 86400)
        recency = math.exp(-days / 90)
        hits.append(Hit(trace=trace, score=round(0.85 * relevance + 0.15 * recency, 4)))
    hits.sort(key=lambda h: (h.score, h.trace.actor_time.started_at), reverse=True)
    return hits[:limit]


def candidates(store: Store, query: DecisionTrace, cap: int = 2000) -> list[DecisionTrace]:
    """Paper's filter (shared policy), falling back to same kind family, then text match."""
    pool: dict[str, DecisionTrace] = {}
    wanted = policy_ids(query)
    family = query.decision_kind.split(".")[0]
    for rec in store.records(record_type="decision", limit=cap):
        if not isinstance(rec, DecisionTrace) or rec.id == query.id:
            continue
        if wanted and policy_ids(rec) & wanted:
            pool[rec.id] = rec
    if not pool:
        for rec in store.records(record_type="decision", decision_kind=family, limit=cap):
            if isinstance(rec, DecisionTrace) and rec.id != query.id:
                pool[rec.id] = rec
    if not pool:
        for rec, _ in store.search(query.intent, limit=200):
            if rec.id != query.id:
                pool[rec.id] = rec
    return list(pool.values())


def similar(
    store: Store, query: DecisionTrace, limit: int = 5, weights: Weights | None = None
) -> list[Hit]:
    weights = weights or Weights.from_config(store.config.home)
    scored: list[tuple[DecisionTrace, Score]] = [
        (c, similarity(query, c, weights)) for c in candidates(store, query)
    ]
    scored.sort(key=lambda p: p[1].total, reverse=True)
    return [
        Hit(trace=t, score=s.total, strength=s.strength, components=s.components)
        for t, s in scored[:limit]
    ]


def precedent_view(store: Store, trace: DecisionTrace) -> dict[str, Any]:
    """Compact, model-friendly account of a past decision (corrections applied)."""
    related = store.related(trace.id)
    t = apply_corrections(trace, [r for r in related if isinstance(r, CorrectionRecord)])
    who = t.actor_time.actor.name or t.actor_time.actor.id
    view: dict[str, Any] = {
        "id": t.id,
        "when": t.actor_time.started_at.isoformat(),
        "kind": t.decision_kind,
        "intent": t.intent,
        "decided_by": who,
        "outcome": current_outcome(t, related),
    }
    if t.policies:
        view["rules"] = [
            {"rule": p.policy_id, "result": p.result, **({"detail": p.detail} if p.detail else {})}
            for p in t.policies
        ]
    if t.exceptions:
        view["exceptions"] = [
            {
                "rule": e.policy_id,
                "waived_by": e.granted_by.name or e.granted_by.id,
                **({"role": e.granted_by.role} if e.granted_by.role else {}),
                "reason": e.reason,
            }
            for e in t.exceptions
        ]
    if t.human_path:
        view["approval_path"] = [
            {
                "step": h.type,
                "by": h.actor.name or h.actor.id,
                **({"note": h.detail} if h.detail else {}),
            }
            for h in t.human_path
        ]
    if t.actions:
        view["actions"] = [a.summary or a.name for a in t.actions]
    if t.alternatives:
        view["rejected"] = [
            {
                "option": x.action.summary or x.action.name,
                "by": x.rejected_by,
                **({"why": x.reason} if x.reason else {}),
            }
            for x in t.alternatives
        ]
    notes = [r.note for r in related if r.record_type == "outcome" and getattr(r, "note", None)]
    if notes:
        view["outcome_notes"] = notes
    return view
