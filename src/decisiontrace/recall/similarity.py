"""Deterministic precedent similarity, as defined in *DecisionTrace and Context Graphs* §5.

Candidates share at least one policy with the query decision (``Pi ∩ Pj ≠ ∅``); when the
query has no policies (common for coding agents) we fall back to decisions of the same
kind family, then to full-text matches. Each candidate is scored::

    Sim = αP + βX + γC + δA + εT − λΔt

with every component in [0, 1]:

* P -- policy overlap, weighted by whether shared rules had the same result
* X -- overlap of rejected alternatives (what was ruled out, and by whom)
* C -- context: word overlap of intent and context summaries
* A -- the chosen actions (type and tool), plus capability overlap
* T -- actor: same actor, same actor type, same model
* Δt -- age gap in years, capped at 1

When *neither* decision has policies (or alternatives), that term carries no information and
its weight is dropped from the denominator instead of silently capping the score -- so two
identical coding decisions with no rules still score 1.0.

Weights and thresholds live in ``config.toml`` under ``[recall]``. Scores at or above
``strong`` are strong precedent, at or above ``weak`` weak precedent.
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from decisiontrace.model import DecisionTrace
from decisiontrace.recall.text import tokens


@dataclass(frozen=True)
class Weights:
    alpha: float = 0.30  # P policies
    beta: float = 0.10  # X alternatives
    gamma: float = 0.30  # C context
    delta: float = 0.20  # A actions
    epsilon: float = 0.10  # T actor
    lam: float = 0.10  # Δt penalty per year (capped at one year)
    strong: float = 0.75
    weak: float = 0.60

    @classmethod
    def from_config(cls, home: Path) -> Weights:
        path = home / "config.toml"
        if not path.exists():
            return cls()
        section = tomllib.loads(path.read_text(encoding="utf-8")).get("recall", {})
        names = {"alpha", "beta", "gamma", "delta", "epsilon", "lambda", "strong", "weak"}
        values = {
            ("lam" if k == "lambda" else k): float(v) for k, v in section.items() if k in names
        }
        return cls(**values)


@dataclass
class Score:
    total: float
    components: dict[str, float] = field(default_factory=dict)
    strength: str = "none"  # strong | weak | none


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def policy_ids(trace: DecisionTrace) -> set[str]:
    return {p.policy_id for p in trace.policies or []}


def p_component(a: DecisionTrace, b: DecisionTrace) -> float:
    pa = {p.policy_id: p.result for p in a.policies or []}
    pb = {p.policy_id: p.result for p in b.policies or []}
    union = set(pa) | set(pb)
    if not union:
        return 0.0
    shared = set(pa) & set(pb)
    agreement = sum(1.0 if pa[k] == pb[k] else 0.5 for k in shared)
    exceptions_a = {e.policy_id for e in a.exceptions or []}
    exceptions_b = {e.policy_id for e in b.exceptions or []}
    score = agreement / len(union)
    if exceptions_a or exceptions_b:  # an exception on the same rule is strong evidence
        score = 0.7 * score + 0.3 * _jaccard(exceptions_a, exceptions_b)
    return score


def x_component(a: DecisionTrace, b: DecisionTrace) -> float:
    def sig(t: DecisionTrace) -> set[str]:
        return {f"{x.action.type}:{x.action.name}:{x.rejected_by}" for x in t.alternatives or []}

    return _jaccard(sig(a), sig(b))


def context_words(t: DecisionTrace) -> set[str]:
    words = tokens(t.intent)
    if t.context:
        for item in t.context.inputs or []:
            words += [*tokens(item.summary or ""), item.type]
    return set(words)


def c_component(a: DecisionTrace, b: DecisionTrace) -> float:
    wa, wb = context_words(a), context_words(b)
    if not wa or not wb:
        return 0.0
    return float(len(wa & wb) / math.sqrt(len(wa) * len(wb)))  # cosine on word sets


def a_component(a: DecisionTrace, b: DecisionTrace) -> float:
    def acts(t: DecisionTrace) -> set[str]:
        return {f"{x.type}:{x.name}" for x in t.actions or []}

    caps = _jaccard(set(a.capabilities or []), set(b.capabilities or []))
    same_kind = 1.0 if a.decision_kind == b.decision_kind else 0.0
    return 0.5 * _jaccard(acts(a), acts(b)) + 0.25 * caps + 0.25 * same_kind


def t_component(a: DecisionTrace, b: DecisionTrace) -> float:
    ta, tb = a.actor_time, b.actor_time
    score = 0.0
    if ta.actor.id == tb.actor.id:
        score += 0.6
    elif ta.actor.type == tb.actor.type:
        score += 0.3
    if ta.model and tb.model and ta.model.name == tb.model.name:
        score += 0.2
    if ta.on_behalf_of and tb.on_behalf_of and ta.on_behalf_of.id == tb.on_behalf_of.id:
        score += 0.2
    return min(score, 1.0)


def age_gap_years(a: DecisionTrace, b: DecisionTrace) -> float:
    seconds = abs((a.actor_time.started_at - b.actor_time.started_at).total_seconds())
    return min(seconds / (365 * 24 * 3600), 1.0)


def similarity(
    a: DecisionTrace, b: DecisionTrace, w: Weights | None = None, semantic: float | None = None
) -> Score:
    """``semantic`` (cosine of embeddings, if enabled) is blended into the C component."""
    w = w or Weights()
    context = c_component(a, b)
    if semantic is not None:
        context = 0.5 * context + 0.5 * max(0.0, semantic)
    comps = {
        "P": p_component(a, b),
        "X": x_component(a, b),
        "C": context,
        "A": a_component(a, b),
        "T": t_component(a, b),
        "dt": age_gap_years(a, b),
    }
    terms = [
        (w.alpha, comps["P"], bool(a.policies or b.policies)),
        (w.beta, comps["X"], bool(a.alternatives or b.alternatives)),
        (w.gamma, comps["C"], True),
        (w.delta, comps["A"], True),
        (w.epsilon, comps["T"], True),
    ]
    weight = sum(wt for wt, _, used in terms if used) or 1.0
    total = sum(wt * c for wt, c, used in terms if used) / weight - w.lam * comps["dt"]
    total = max(0.0, min(1.0, total))
    strength = "strong" if total >= w.strong else "weak" if total >= w.weak else "none"
    return Score(
        total=round(total, 4),
        components={k: round(v, 4) for k, v in comps.items()},
        strength=strength,
    )
