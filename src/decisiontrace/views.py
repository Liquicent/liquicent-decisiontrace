"""Human-readable views of records, with corrections and later outcomes applied."""

from __future__ import annotations

import re
from typing import Any

from decisiontrace.model import (
    CorrectionRecord,
    DecisionTrace,
    OutcomeRecord,
    parse_record,
    to_json_dict,
)

_PATH_PART = re.compile(r"([a-z_]+)(?:\[(\d+)\])?")


def apply_corrections(trace: DecisionTrace, corrections: list[CorrectionRecord]) -> DecisionTrace:
    """Return the decision as corrected (the stored record itself never changes)."""
    if not corrections:
        return trace
    data = to_json_dict(trace)
    data.pop("integrity", None)
    for correction in corrections:
        for path, value in correction.changes.items():
            _set_path(data, path, value)
    result = parse_record(data)
    assert isinstance(result, DecisionTrace)
    return result


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = [_PATH_PART.fullmatch(p) for p in path.split(".")]
    node: Any = data
    for i, match in enumerate(parts):
        assert match is not None
        key, index = match.group(1), match.group(2)
        last = i == len(parts) - 1
        if index is None:
            if last:
                node[key] = value
            else:
                node = node.setdefault(key, {})
        else:
            items = node.setdefault(key, [])
            pos = int(index)
            if pos >= len(items):
                raise ValueError(f"correction path {path!r} is out of range")
            if last:
                items[pos] = value
            else:
                node = items[pos]


def current_outcome(trace: DecisionTrace, related: list[OutcomeRecord | CorrectionRecord]) -> str:
    outcomes = [r for r in related if isinstance(r, OutcomeRecord)]
    if outcomes:
        return outcomes[-1].status
    return trace.outcome.status if trace.outcome else "-"


def short(ulid: str) -> str:
    return ulid[:10]


def _actor(a: Any) -> str:
    label = a.name or a.id
    return f"{label} ({a.role})" if a.role else label


def render_trace(
    trace: DecisionTrace,
    related: list[OutcomeRecord | CorrectionRecord],
    incoming: list[tuple[str, str]] | None = None,
) -> str:
    """Plain-text account of one decision: C, P, E, X, H, T, O."""
    corrections = [r for r in related if isinstance(r, CorrectionRecord)]
    t = apply_corrections(trace, corrections)
    at = t.actor_time
    lines = [
        f"{t.intent}",
        f"  id {t.id}  ·  {t.decision_kind}  ·  namespace {t.namespace}",
        "",
        "Who / when (T)",
        f"  {_actor(at.actor)}"
        + (f" on behalf of {_actor(at.on_behalf_of)}" if at.on_behalf_of else ""),
        f"  {at.started_at.isoformat()}" + (f" → {at.ended_at.isoformat()}" if at.ended_at else ""),
    ]
    if at.model:
        lines.append(f"  model {at.model.provider}/{at.model.name}")
    if at.cost:
        parts = []
        if at.cost.usd is not None:
            parts.append(f"${at.cost.usd:.4f}")
        if at.cost.input_tokens is not None or at.cost.output_tokens is not None:
            parts.append(
                f"{at.cost.input_tokens or 0:,} in / {at.cost.output_tokens or 0:,} out tokens"
            )
        if at.cost.cache_read_input_tokens:
            parts.append(f"{at.cost.cache_read_input_tokens:,} cached")
        if parts:
            lines.append("  cost " + ", ".join(parts))
    if t.context and (t.context.inputs or t.context.state_before):
        lines += ["", "Context (C)"]
        for item in t.context.inputs or []:
            lines.append(
                f"  {item.type}: {item.ref}" + (f" — {item.summary}" if item.summary else "")
            )
        if t.context.state_before:
            lines.append(f"  state before: {t.context.state_before.ref}")
    if t.policies:
        lines += ["", "Rules checked (P)"]
        for p in t.policies:
            mark = {"pass": "✓", "fail": "✗"}.get(p.result, "·")
            gate = " [enforced]" if p.enforced else ""
            lines.append(
                f"  {mark} {p.policy_id}: {p.result}{gate}" + (f" — {p.detail}" if p.detail else "")
            )
    if t.exceptions:
        lines += ["", "Exceptions (E)"]
        for e in t.exceptions:
            lines.append(f"  {e.policy_id} waived by {_actor(e.granted_by)}: {e.reason}")
    if t.actions:
        lines += ["", "What was done"]
        for a in t.actions:
            status = f" [{a.status}]" if a.status and a.status != "executed" else ""
            lines.append(f"  {a.name}{status}" + (f" — {a.summary}" if a.summary else ""))
    if t.alternatives:
        lines += ["", "Rejected options (X)"]
        for x in t.alternatives:
            why = f": {x.reason}" if x.reason else (f" ({x.policy_id})" if x.policy_id else "")
            desc = x.action.summary or x.action.name
            lines.append(f"  {desc} — rejected by {x.rejected_by}{why}")
    if t.human_path:
        lines += ["", "Human path (H)"]
        for h in t.human_path:
            wait = f" after {h.latency_ms / 60000:.0f} min" if h.latency_ms else ""
            lines.append(
                f"  {h.type} by {_actor(h.actor)}{wait}" + (f" — {h.detail}" if h.detail else "")
            )
    if t.state_after:
        lines += ["", f"State after: {t.state_after.ref}"]
    lines += ["", f"Outcome (O): {current_outcome(t, related)}"]
    for r in related:
        if isinstance(r, OutcomeRecord):
            note = f" — {r.note}" if r.note else ""
            lines.append(f"  {r.recorded_at.date()} {r.status} by {_actor(r.recorded_by)}{note}")
            if r.vwu:
                v = r.vwu
                qty = v.quantity if v.quantity is not None else 1
                lines.append(
                    f"    verified work unit: {v.unit} x{qty:g}, {v.verification.method},"
                    f" reversible until {v.reversal.window_ends_at.date()}"
                )
    if corrections:
        lines += ["", "Corrections applied"]
        for c in corrections:
            lines.append(f"  {c.corrected_at.date()} by {_actor(c.corrected_by)}: {c.reason}")
    links = [(lk.type, lk.target_id) for lk in t.links or []]
    incoming = [(k, s) for k, s in (incoming or []) if k not in ("outcome", "correction")]
    if links or incoming:
        lines += ["", "Links"]
        lines += [f"  → {kind} {short(target)}" for kind, target in links]
        lines += [f"  ← {kind} from {short(src)}" for kind, src in incoming]
    return "\n".join(lines)
