"""Opt-in: a decision that acted, with no negative signal after N days, is taken as accepted.

Off unless asked for (``--assume-accepted-after N``): silence is evidence only where problems
would have been reported. The note says it is an assumption.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from decisiontrace.model import DecisionTrace
from decisiontrace.outcomes.base import Signal


def detect(traces: list[DecisionTrace], days: float, now: datetime | None = None) -> list[Signal]:
    now = now or datetime.now(UTC)
    out = []
    for t in traces:
        acted = [a for a in t.actions or [] if a.status in (None, "executed")]
        if not acted:
            continue
        at = t.actor_time.started_at + timedelta(days=days)
        if at <= now:
            out.append(
                Signal(
                    t.id,
                    "accepted",
                    "silence",
                    at,
                    f"Assumed accepted: no negative signal within {days:g} days",
                )
            )
    return out
