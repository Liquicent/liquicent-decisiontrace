"""``dt why``: a plain-English account of why a decision was made.

Deterministic -- built from the record, no model call -- so it is reproducible, works offline
and never invents a reason that wasn't recorded.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

from decisiontrace.model import CorrectionRecord, DecisionTrace, OutcomeRecord
from decisiontrace.recall.precedent import Hit, similar
from decisiontrace.store import Store, StoreError, UnknownRecord
from decisiontrace.views import apply_corrections, current_outcome

_SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")

KIND_PHRASES = {
    "code.edit": "made a code change",
    "code.commit": "committed code",
    "code.release": "pushed code",
    "code.search": "searched the code",
    "code.test": "ran tests",
    "harness.update": "changed its own instructions",
    "research.delegate": "delegated work to a subagent",
    "research.web": "looked something up on the web",
    "refund.approve": "approved a refund",
    "refund.deny": "declined a refund",
    "pr.merge": "merged a pull request",
    "procurement.approve": "approved a purchase",
    "email.draft": "drafted an email",
    "tool.call": "used a tool",
}


def resolve_target(store: Store, target: str, cwd: Path | None = None) -> DecisionTrace:
    """Find the decision behind an id, a file path, or a git commit."""
    target = target.strip()
    try:
        rec = store.get(target)
        if isinstance(rec, DecisionTrace):
            return rec
        if isinstance(rec, OutcomeRecord | CorrectionRecord):
            parent = store.get(rec.trace_id)
            assert isinstance(parent, DecisionTrace)
            return parent
    except StoreError:
        pass
    if _SHA.match(target):
        made = store.by_ref("commit", target, prefix=True)
        if made:
            return made[-1]  # oldest decision whose turn ended at this commit
    candidates = {target}
    path = Path(target)
    if cwd is not None and path.is_absolute():
        with contextlib.suppress(ValueError):
            candidates.add(str(path.relative_to(cwd)))
    for ref in list(candidates):
        candidates.update(store.file_refs_like(ref.lstrip("./")))
    for ref in candidates:
        hits = store.by_ref("file", ref)
        if hits:
            return hits[0]  # most recent change to this file
    raise UnknownRecord(f"no decision found for {target!r} (id, file path or commit)")


def _who(actor: object) -> str:
    name = getattr(actor, "name", None) or getattr(actor, "id", "someone")
    role = getattr(actor, "role", None)
    return f"{name} ({role})" if role else str(name)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def explain(store: Store, trace: DecisionTrace, precedents: int = 3) -> str:
    related = store.related(trace.id)
    t = apply_corrections(trace, [r for r in related if isinstance(r, CorrectionRecord)])
    at = t.actor_time
    when = at.started_at.strftime("%d %b %Y %H:%M %Z").strip()
    verb = KIND_PHRASES.get(t.decision_kind, f"made a {t.decision_kind} decision")
    head = f"On {when}, {_who(at.actor)} {verb}"
    if at.on_behalf_of:
        head += f" for {_who(at.on_behalf_of)}"
    lines = [f"Why: {t.intent}", "", head + "."]
    extras = []
    if at.model:
        extras.append(f"model {at.model.name}")
    if at.ended_at:
        minutes = (at.ended_at - at.started_at).total_seconds() / 60
        extras.append(f"took {minutes:.0f} min" if minutes >= 1 else "took under a minute")
    if at.cost and at.cost.usd is not None:
        extras.append(f"cost ${at.cost.usd:.2f}")
    if extras:
        lines[-1] = lines[-1][:-1] + f" ({', '.join(extras)})."

    if t.context and t.context.inputs:
        asked = [i for i in t.context.inputs if i.type == "user_prompt"]
        other = [i for i in t.context.inputs if i.type != "user_prompt"]
        parts = []
        if asked and asked[0].summary:
            parts.append(f'the request "{asked[0].summary}"')
        for item in other[:6]:
            parts.append(f"{item.type} {item.ref}" + (f" ({item.summary})" if item.summary else ""))
        if len(other) > 6:
            parts.append(f"{len(other) - 6} more inputs")
        if parts:
            lines += ["", "It was based on " + "; ".join(parts) + "."]

    if t.policies:
        passed = [p for p in t.policies if p.result == "pass"]
        failed = [p for p in t.policies if p.result == "fail"]
        sentence = []
        if failed:
            sentence.append(
                "failed: "
                + "; ".join(p.policy_id + (f" ({p.detail})" if p.detail else "") for p in failed)
            )
        if passed:
            sentence.append("passed: " + ", ".join(p.policy_id for p in passed))
        unusual = [p for p in t.policies if p.result not in ("pass", "fail")]
        if unusual:
            sentence.append(
                "; ".join(
                    f"{p.policy_id}: {p.result}" + (f" ({p.detail})" if p.detail else "")
                    for p in unusual
                )
            )
        lines += ["", f"Rules checked ({len(t.policies)}) — " + ". ".join(sentence) + "."]
    else:
        lines += ["", "No rules were recorded for this decision."]

    if t.exceptions:
        for e in t.exceptions:
            lines.append(
                f"Exception: {e.policy_id} was waived by {_who(e.granted_by)} — {e.reason}."
            )
    elif t.policies and any(p.result == "fail" for p in t.policies):
        lines.append("No exception was recorded for the failed rule(s).")

    if t.alternatives:
        lines += ["", "Considered and rejected:"]
        for x in t.alternatives:
            why = f": {x.reason}" if x.reason else (f" (rule {x.policy_id})" if x.policy_id else "")
            lines.append(
                f"  - {x.action.summary or x.action.name} — rejected by {x.rejected_by}{why}"
            )

    if t.human_path:
        steps = []
        for h in t.human_path:
            wait = (
                f" after {h.latency_ms / 60000:.0f} min"
                if h.latency_ms and h.latency_ms >= 60000
                else ""
            )
            steps.append(
                f"{h.type} by {_who(h.actor)}{wait}" + (f" ({h.detail})" if h.detail else "")
            )
        lines += ["", "People involved: " + "; then ".join(steps) + "."]
    else:
        lines += ["", "No human approval was recorded."]

    if t.actions:
        done = [a.summary or (f"{a.name} {a.target}" if a.target else a.name) for a in t.actions]
        shown = done[:6] + ([f"and {len(done) - 6} more"] if len(done) > 6 else [])
        lines += [
            "",
            f"What was done ({_plural(len(t.actions), 'action')}): " + "; ".join(shown) + ".",
        ]
    if t.state_after:
        lines.append(f"Resulting state: {t.state_after.type} {t.state_after.ref[:12]}.")

    outcome = current_outcome(t, related)
    lines += ["", f"Outcome: {outcome}."]
    for r in related:
        if isinstance(r, OutcomeRecord) and r.note:
            lines.append(f"  {r.recorded_at.date()}: {r.status} — {r.note}")
    corrections = [r for r in related if isinstance(r, CorrectionRecord)]
    if corrections:
        lines.append(f"This account includes {_plural(len(corrections), 'later correction')}.")

    if precedents:
        hits: list[Hit] = [
            h for h in similar(store, trace, limit=precedents) if h.strength != "none"
        ]
        if hits:
            lines += ["", "Similar past decisions:"]
            for hit in hits:
                lines.append(
                    f"  - {hit.trace.id[:10]} ({hit.strength}, {hit.score:.2f}) {hit.trace.intent[:80]}"
                )
    return "\n".join(lines)
