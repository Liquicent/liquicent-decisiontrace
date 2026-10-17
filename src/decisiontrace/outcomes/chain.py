"""Signals inside the store: overrides, reversal/supersede links, failed actions, human redos."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from decisiontrace.model import DecisionTrace
from decisiontrace.outcomes.base import Signal

REDO_WINDOW = timedelta(hours=24)


def _business_refs(t: DecisionTrace) -> set[str]:
    """Refs that identify the thing decided about (tickets, orders…), not files."""
    refs = set()
    if t.context:
        for item in t.context.inputs or []:
            if item.type not in ("file", "user_prompt", "retrieved_doc", "doc") and ":" in item.ref:
                refs.add(item.ref)
    return refs


def detect(traces: list[DecisionTrace]) -> list[Signal]:
    out: list[Signal] = []
    by_id = {t.id: t for t in traces}
    for t in traces:
        end = t.actor_time.ended_at or t.actor_time.started_at
        for h in t.human_path or []:
            if h.type == "overrode" and h.actor.type == "human":
                who = h.actor.name or h.actor.id
                out.append(
                    Signal(
                        t.id,
                        "overridden",
                        "chain",
                        h.at,
                        f"{who} overrode it",
                        "human_path.overrode",
                    )
                )
        actions = [a for a in t.actions or [] if a.status != "proposed"]
        if actions and actions[-1].status == "failed":
            out.append(
                Signal(
                    t.id,
                    "failed",
                    "chain",
                    end,
                    f"Its last action failed: {actions[-1].name}",
                    f"actions[-1]={actions[-1].name}",
                )
            )
        for link in t.links or []:
            target = by_id.get(link.target_id)
            if target is None:
                continue
            if link.type == "reversal":
                out.append(
                    Signal(
                        target.id,
                        "reverted",
                        "chain",
                        t.actor_time.started_at,
                        f"Reversed by decision {t.id[-8:]}: {t.intent[:200]}",
                        f"link.reversal←{t.id}",
                    )
                )
            elif link.type == "supersedes":
                out.append(
                    Signal(
                        target.id,
                        "overridden",
                        "chain",
                        t.actor_time.started_at,
                        f"Superseded by decision {t.id[-8:]}: {t.intent[:200]}",
                        f"link.supersedes←{t.id}",
                    )
                )
    # A person redoing the same business item soon after an agent decided it = overridden.
    by_ref: dict[str, list[DecisionTrace]] = defaultdict(list)
    for t in traces:
        for ref in _business_refs(t):
            by_ref[ref].append(t)
    for ref, ts in by_ref.items():
        ts.sort(key=lambda x: x.actor_time.started_at)
        for i, agent_t in enumerate(ts):
            if agent_t.actor_time.actor.type == "human":
                continue
            for later in ts[i + 1 :]:
                gap = later.actor_time.started_at - agent_t.actor_time.started_at
                if gap > REDO_WINDOW:
                    break
                if (
                    later.actor_time.actor.type == "human"
                    and later.decision_kind == agent_t.decision_kind
                ):
                    who = later.actor_time.actor.name or later.actor_time.actor.id
                    out.append(
                        Signal(
                            agent_t.id,
                            "overridden",
                            "chain",
                            later.actor_time.started_at,
                            f"{who} redid {ref} within {gap.total_seconds() / 3600:.1f} h",
                            f"redo:{ref}←{later.id}",
                        )
                    )
                    break
    return out
