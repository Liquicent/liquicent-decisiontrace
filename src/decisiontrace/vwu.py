"""Verified Work Units read back from the store (local recall only).

A VWU (the WorkRank paper's unit of work) is an *accepted* outcome record that carries a
``vwu`` block: one completed, accepted and reversible unit of work that met its quality
threshold. Its state is derived, never stored, so the store stays append-only:

* ``reverted`` -- a later outcome for the same decision cancelled it inside its reversal
  window (reverted, failed or overridden; a complaint or escalation does not undo delivery);
* ``final`` -- the window has ended with no cancel (a cancel after it does not reopen it);
* ``provisional`` -- still inside the window.

Who earns from a unit, and how much, is not decided here: no trust scores, routing or
settlement. Those need many people's records and belong to Liquicent.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from decisiontrace.model import Actor, CorrectionRecord, DecisionTrace, OutcomeRecord
from decisiontrace.store import Store

CANCELS = ("reverted", "failed", "overridden")
State = Literal["provisional", "final", "reverted"]
STATES: tuple[State, ...] = ("provisional", "final", "reverted")


@dataclass(frozen=True)
class Unit:
    trace_id: str
    outcome_id: str
    unit: str
    quantity: float
    executor: Actor | None  # the unit's executor, else the decision's actor
    method: str
    value_usd: float | None
    recorded_at: datetime
    window_ends_at: datetime
    state: State

    def to_json(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "outcome_id": self.outcome_id,
            "unit": self.unit,
            "quantity": self.quantity,
            "executor": (
                self.executor.model_dump(mode="json", exclude_none=True) if self.executor else None
            ),
            "method": self.method,
            "value_usd": self.value_usd,
            "recorded_at": _iso(self.recorded_at),
            "window_ends_at": _iso(self.window_ends_at),
            "state": self.state,
        }


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def state_of(
    record: OutcomeRecord,
    related: Iterable[OutcomeRecord | CorrectionRecord],
    now: datetime | None = None,
) -> State:
    """State of the unit on ``record`` given the other records linked to its decision."""
    if record.vwu is None:
        raise ValueError(f"outcome {record.id} carries no verified work unit")
    now = now or datetime.now(UTC)
    ends = record.vwu.reversal.window_ends_at
    for r in related:
        if (
            isinstance(r, OutcomeRecord)
            and r.id != record.id
            and r.status in CANCELS
            and record.recorded_at <= r.recorded_at <= ends
        ):
            return "reverted"
    return "final" if now >= ends else "provisional"


def units(store: Store, since: str | None = None, now: datetime | None = None) -> list[Unit]:
    """Every VWU in the store, oldest first. ``since`` filters on when it was recorded."""
    now = now or datetime.now(UTC)
    deciders: dict[str, Actor | None] = {}
    out: list[Unit] = []
    for r in store.records(record_type="outcome", since=since, newest_first=False):
        if not isinstance(r, OutcomeRecord) or r.vwu is None:
            continue
        v = r.vwu
        executor = v.executor
        if executor is None:
            if r.trace_id not in deciders:
                trace = store.get(r.trace_id)
                deciders[r.trace_id] = (
                    trace.actor_time.actor if isinstance(trace, DecisionTrace) else None
                )
            executor = deciders[r.trace_id]
        out.append(
            Unit(
                trace_id=r.trace_id,
                outcome_id=r.id,
                unit=v.unit,
                quantity=v.quantity if v.quantity is not None else 1.0,
                executor=executor,
                method=v.verification.method,
                value_usd=r.value_usd,
                recorded_at=r.recorded_at,
                window_ends_at=v.reversal.window_ends_at,
                state=state_of(r, store.related(r.trace_id), now),
            )
        )
    return out


def summary(found: Iterable[Unit]) -> dict[str, float]:
    """Units by state, and the share verified by something other than a person (the
    number to watch when checking becomes the bottleneck). Weighted by quantity."""
    totals: dict[str, float] = dict.fromkeys(STATES, 0.0)
    total = unattended = 0.0
    for u in found:
        totals[u.state] += u.quantity
        total += u.quantity
        if u.method != "human":
            unattended += u.quantity
    return {
        "units": total,
        **totals,
        "verified_without_a_person": unattended / total if total else 0.0,
    }
