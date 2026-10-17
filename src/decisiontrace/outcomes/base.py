"""Signals, the rules for turning them into outcome records, and writing them."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from decisiontrace.ids import new_ulid
from decisiontrace.model import SCHEMA_VERSION, DecisionTrace, OutcomeRecord
from decisiontrace.store import Store

NEGATIVE = ("reverted", "failed", "complained", "overridden", "escalated")
# When several signals hit one decision in a run, the most serious wins.
SEVERITY = {
    "accepted": 0,
    "escalated": 1,
    "overridden": 2,
    "complained": 3,
    "failed": 4,
    "reverted": 5,
}
DETECTOR_PREFIX = "decisiontrace:detect:"


@dataclass(frozen=True)
class Signal:
    trace_id: str
    status: str
    source: str  # chain | git | events:<preset> | silence
    at: datetime  # when the signal happened (= when the outcome became knowable)
    note: str
    evidence: str = ""
    value_usd: float | None = None


@dataclass
class Existing:
    human: bool = False
    detected: dict[str, set[str]] = field(default_factory=dict)  # source → statuses written
    latest_status: str | None = None


def _existing(store: Store, trace_id: str) -> Existing:
    ex = Existing()
    for r in store.related(trace_id):
        if not isinstance(r, OutcomeRecord):
            continue
        ex.latest_status = r.status
        if r.recorded_by.id.startswith(DETECTOR_PREFIX):
            ex.detected.setdefault(r.recorded_by.id.removeprefix(DETECTOR_PREFIX), set()).add(
                r.status
            )
        else:
            ex.human = True
    return ex


def plan(store: Store, signals: Iterable[Signal]) -> list[Signal]:
    """The signals worth writing: one per decision, most serious first; never over a human's
    outcome, never twice, and never a weaker status over a stronger detected one."""
    best: dict[str, Signal] = {}
    for s in signals:
        cur = best.get(s.trace_id)
        if cur is None or (SEVERITY.get(s.status, 0), s.at) > (SEVERITY.get(cur.status, 0), cur.at):
            best[s.trace_id] = s
    out = []
    for s in best.values():
        ex = _existing(store, s.trace_id)
        if ex.human:
            continue
        trace = store.get(s.trace_id)
        if (
            isinstance(trace, DecisionTrace)
            and trace.outcome
            and trace.outcome.status not in ("pending", "other")
        ):
            continue  # the outcome recorded with the decision stands
        if s.status in ex.detected.get(s.source, set()):
            continue
        if (
            ex.latest_status
            and SEVERITY.get(ex.latest_status, 0) >= SEVERITY.get(s.status, 0)
            and ex.detected
        ):
            continue
        out.append(s)
    return sorted(out, key=lambda s: (s.at, s.trace_id))


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply(store: Store, signals: list[Signal], now: datetime | None = None) -> int:
    """Append one outcome record per planned signal. Returns how many were written."""
    now = now or datetime.now(UTC)
    records: list[dict[str, Any]] = []
    for s in signals:
        trace = store.get(s.trace_id)
        assert isinstance(trace, DecisionTrace)
        attrs: dict[str, Any] = {"decisiontrace.detector": s.source}
        if s.evidence:
            attrs["decisiontrace.evidence"] = s.evidence[:500]
        rec: dict[str, Any] = {
            "record_type": "outcome",
            "schema_version": SCHEMA_VERSION,
            "id": new_ulid(int(min(s.at, now).timestamp() * 1000)),
            "namespace": trace.namespace,
            "trace_id": s.trace_id,
            "status": s.status,
            "note": s.note[:2000],
            "recorded_by": {
                "type": "system",
                "id": DETECTOR_PREFIX + s.source,
                "name": "DecisionTrace outcome detection",
            },
            "recorded_at": _iso(min(s.at, now)),
            "attributes": attrs,
        }
        if s.value_usd is not None:
            rec["value_usd"] = s.value_usd
        records.append(rec)
    if records:
        store.append_many(records)
    return len(records)


def decisions(store: Store, since: str | None = None) -> list[DecisionTrace]:
    out = [
        r
        for r in store.records(record_type="decision", since=since, newest_first=False)
        if isinstance(r, DecisionTrace)
    ]
    return out
