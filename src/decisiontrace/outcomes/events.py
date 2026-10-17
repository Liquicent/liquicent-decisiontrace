"""Signals from business systems: each event names a thing (a ticket, a charge, a PR) and what
happened to it; it is matched to the decisions that acted on that thing.

Input is JSON Lines: one event per line, either the native webhook payload of a preset
(``stripe``, ``zendesk``, ``jira``, ``github``, ``pagerduty``) or the generic shape::

    {"ref": "zendesk:88412", "event": "reopened", "at": "2026-10-14T09:00:00Z", "value_usd": -40}

``trace_id`` may replace ``ref`` to point at a decision directly, and an accepted event may
name the work ``unit`` it delivered (for ``--vwu``; otherwise the preset's unit is used).

A ref matches a decision when it equals one of the decision's refs (context inputs, action
targets, state refs), or when its id part (after the last ``:``/``#``/``/``, at least 4
characters) equals theirs. Only decisions made before the event are matched.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from decisiontrace.model import DecisionTrace
from decisiontrace.outcomes.base import Signal, UnitHint

# Generic event words → outcome status. Lower-case; "." and "-" are treated as "_".
STATUS_WORDS: dict[str, str] = {}
for status, words in {
    "accepted": "accepted delivered resolved solved merged paid succeeded completed closed_solved approved_by_customer positive_csat",
    "reverted": "reverted rolled_back rollback cancelled canceled voided refund_reversed undone closed_unmerged",
    "failed": "failed error errored incident payment_failed bounced timed_out",
    "complained": "complained reopened dispute disputed chargeback negative_csat bad_rating escalated_by_customer",
    "overridden": "overridden manual_override edited_by_human corrected",
    "escalated": "escalated",
}.items():
    for w in words.split():
        STATUS_WORDS[w] = status


@dataclass(frozen=True)
class Event:
    refs: tuple[str, ...]
    status: str
    at: datetime
    label: str
    value_usd: float | None = None
    trace_id: str | None = None
    unit: str | None = None  # the work unit an accepted event delivers; else the preset's


# The unit of work an accepted event delivers, per preset (for ``--vwu``).
UNITS: dict[str, str] = {
    "generic": "work.item",
    "stripe": "stripe.payment",
    "zendesk": "zendesk.ticket",
    "jira": "jira.issue",
    "github": "github.pull_request",
    "pagerduty": "pagerduty.incident",
}
_LABEL = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")


def _norm(word: str) -> str:
    return re.sub(r"[.\-\s]+", "_", word.strip().lower())


def status_of(word: str) -> str | None:
    w = _norm(word)
    if w in STATUS_WORDS:
        return STATUS_WORDS[w]
    for part in reversed(w.split("_")):  # "ticket_reopened" → "reopened"
        if part in STATUS_WORDS:
            return STATUS_WORDS[part]
    tail2 = "_".join(w.split("_")[-2:])
    return STATUS_WORDS.get(tail2)


def _time(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, int | float):
        return datetime.fromtimestamp(float(v), UTC)
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _generic(e: dict[str, Any]) -> Event | None:
    word = e.get("event") or e.get("status") or e.get("type")
    status = (
        e.get("outcome")
        if e.get("outcome") in STATUS_WORDS.values()
        else (status_of(str(word)) if word else None)
    )
    at = _time(e.get("at") or e.get("timestamp") or e.get("created_at") or e.get("time"))
    refs = e.get("refs") or ([e["ref"]] if e.get("ref") else [])
    if not status or at is None or not (refs or e.get("trace_id")):
        return None
    value = e.get("value_usd")
    unit = e.get("unit")
    return Event(
        tuple(str(r) for r in refs),
        status,
        at,
        str(word or status),
        float(value) if isinstance(value, int | float) else None,
        e.get("trace_id"),
        unit if isinstance(unit, str) and _LABEL.fullmatch(unit) else None,
    )


STRIPE = {
    "charge.dispute.created": "complained",
    "charge.dispute.funds_withdrawn": "complained",
    "charge.refund.updated:failed": "failed",
    "refund.failed": "failed",
    "refund.updated:failed": "failed",
    "refund.updated:canceled": "reverted",
    "payment_intent.payment_failed": "failed",
    "payment_intent.canceled": "reverted",
    "charge.refunded": "accepted",
    "payment_intent.succeeded": "accepted",
    "invoice.voided": "reverted",
}


def _stripe(e: dict[str, Any]) -> Event | None:
    obj = (e.get("data") or {}).get("object") or {}
    kind = str(e.get("type", ""))
    status = STRIPE.get(f"{kind}:{obj.get('status')}") or STRIPE.get(kind)
    at = _time(e.get("created"))
    if not status or at is None:
        return None
    ids = [obj.get(k) for k in ("id", "charge", "payment_intent", "invoice", "refund")]
    ids += list((obj.get("metadata") or {}).values())
    refs = tuple(f"stripe:{i}" for i in ids if isinstance(i, str) and i)
    amount = obj.get("amount")
    value = (
        -float(amount) / 100
        if status in ("complained", "failed") and isinstance(amount, int | float)
        else None
    )
    unit = "stripe.refund" if kind == "charge.refunded" else None
    return Event(refs, status, at, kind, value, unit=unit)


def _zendesk(e: dict[str, Any]) -> Event | None:
    ticket = e.get("ticket") or (e.get("detail") or {})
    tid = ticket.get("id") or e.get("ticket_id")
    word = str(e.get("event") or e.get("type") or ticket.get("status") or "")
    if (ticket.get("satisfaction_rating") or {}).get("score") == "bad":
        word = "negative_csat"
    if str(ticket.get("status", "")).lower() == "open" and ticket.get("previous_status") in (
        "solved",
        "closed",
    ):
        word = "reopened"
    status = status_of(word)
    at = _time(e.get("time") or e.get("at") or ticket.get("updated_at"))
    if not status or at is None or tid is None:
        return None
    return Event((f"zendesk:{tid}",), status, at, word)


def _jira(e: dict[str, Any]) -> Event | None:
    issue = e.get("issue") or {}
    key = issue.get("key")
    word = ""
    for item in (e.get("changelog") or {}).get("items", []):
        if item.get("field") == "status":
            word = str(item.get("toString") or "")
    status = {
        "reopened": "complained",
        "done": "accepted",
        "resolved": "accepted",
        "closed": "accepted",
        "won't do": "reverted",
        "rejected": "reverted",
    }.get(word.lower()) or (status_of(word) if word else None)
    at = _time(
        e.get("timestamp", 0) / 1000
        if isinstance(e.get("timestamp"), int | float)
        else e.get("timestamp")
    )
    if not status or at is None or not key:
        return None
    return Event((f"jira:{key}",), status, at, f"status → {word}")


def _github(e: dict[str, Any]) -> Event | None:
    pr = e.get("pull_request")
    repo = (e.get("repository") or {}).get("full_name", "")
    if pr and e.get("action") == "closed":
        status = "accepted" if pr.get("merged") else "reverted"
        refs = [f"github:{repo}#{pr.get('number')}", pr.get("html_url", "")]
        head = (pr.get("head") or {}).get("sha")
        if head:
            refs.append(head)
        at = _time(pr.get("merged_at") or pr.get("closed_at"))
        label = "PR merged" if pr.get("merged") else "PR closed without merge"
        return Event(tuple(r for r in refs if r), status, at, label) if at else None
    issue = e.get("issue")
    if issue and e.get("action") == "reopened":
        at = _time(issue.get("updated_at"))
        return (
            Event((f"github:{repo}#{issue.get('number')}",), "complained", at, "issue reopened")
            if at
            else None
        )
    return None


def _pagerduty(e: dict[str, Any]) -> Event | None:
    ev = e.get("event") or e
    kind = str(ev.get("event_type") or "")
    data = ev.get("data") or {}
    if kind != "incident.triggered":
        return None
    details = data.get("body", {}).get("details") or data.get("custom_details") or {}
    refs = details.get("refs") or (
        [details["ref"]] if isinstance(details, dict) and details.get("ref") else []
    )
    trace = details.get("trace_id") if isinstance(details, dict) else None
    at = _time(ev.get("occurred_at"))
    if at is None or not (refs or trace):
        return None
    return Event(
        tuple(str(r) for r in refs),
        "failed",
        at,
        f"incident: {data.get('title', '')}"[:200],
        None,
        trace,
    )


PRESETS: dict[str, Callable[[dict[str, Any]], Event | None]] = {
    "generic": _generic,
    "stripe": _stripe,
    "zendesk": _zendesk,
    "jira": _jira,
    "github": _github,
    "pagerduty": _pagerduty,
}


def read(paths: Iterable[Path], preset: str = "generic") -> tuple[list[Event], int]:
    """Parse event files. Returns (events, lines skipped)."""
    parse = PRESETS[preset]
    events, skipped = [], 0
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                ev = parse(data) if isinstance(data, dict) else None
            except (ValueError, TypeError, AttributeError):
                ev = None
            if ev is None:
                skipped += 1
            else:
                events.append(ev)
    return events, skipped


def _id_part(ref: str) -> str:
    tail = re.split(r"[:#/]", ref.strip())[-1]
    return tail.lower() if len(tail) >= 4 else ""


def refs_of(t: DecisionTrace) -> set[str]:
    refs: set[str] = set()
    if t.context:
        refs |= {i.ref for i in t.context.inputs or []}
        if t.context.state_before:
            refs.add(t.context.state_before.ref)
    refs |= {a.target for a in t.actions or [] if a.target}
    if t.state_after:
        refs.add(t.state_after.ref)
    return {r for r in refs if r}


def detect(
    traces: list[DecisionTrace], events: list[Event], preset: str = "generic"
) -> list[Signal]:
    exact: dict[str, list[DecisionTrace]] = defaultdict(list)
    by_id: dict[str, list[DecisionTrace]] = defaultdict(list)
    ids = {t.id: t for t in traces}
    for t in traces:
        for r in refs_of(t):
            exact[r.lower()].append(t)
            if p := _id_part(r):
                by_id[p].append(t)
    out = []
    for ev in events:
        hits: dict[str, DecisionTrace] = {}
        if ev.trace_id and ev.trace_id in ids:
            hits[ev.trace_id] = ids[ev.trace_id]
        for r in ev.refs:
            for t in exact.get(r.lower(), []) + by_id.get(_id_part(r), []):
                hits[t.id] = t
        unit = (
            UnitHint(
                ev.unit or UNITS.get(preset, "work.item"), ev.at, None, ", ".join(ev.refs)[:1024]
            )
            if ev.status == "accepted"
            else None
        )
        for t in hits.values():
            if t.actor_time.started_at > ev.at:
                continue
            out.append(
                Signal(
                    t.id,
                    ev.status,
                    f"events:{preset}",
                    ev.at,
                    f"{preset}: {ev.label}",
                    ", ".join(ev.refs)[:500],
                    ev.value_usd,
                    unit,
                )
            )
    return out
