"""Local MCP server: any MCP client can record decisions and recall precedents.

Tools (shown to clients as ``decisiontrace`` → ``record`` / ``recall`` / ``outcome``):

* ``record``  -- write a decision for clients that have no hooks (Claude Desktop, Cursor, …)
* ``recall``  -- "have we decided something like this before?" → precedents with their
  rule / exception / approval path, not just text
* ``outcome`` -- attach what happened to a past decision

Runs over stdio; everything stays in the local store.
"""

from __future__ import annotations

import getpass
import re
from datetime import UTC, datetime
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from decisiontrace.config import init_home, load_config
from decisiontrace.ids import new_ulid
from decisiontrace.model import SCHEMA_VERSION, DecisionTrace
from decisiontrace.recall.precedent import precedent_view, search, similar
from decisiontrace.store import Store, StoreError

INSTRUCTIONS = """\
DecisionTrace keeps a local, tamper-evident record of decisions and why they were made.
- Before deciding something that involves a rule, a limit, an exception or an approval,
  call `recall` with a short description to see how similar cases were handled.
- After such a decision is made, call `record` with the rules checked, any exception and
  who granted it, options rejected, and who approved.
- When you learn how a past decision turned out, call `outcome`.
Never put secrets or your own reasoning into these tools; record facts only."""

_ULIDISH = re.compile(r"^[0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{6,26}$")


class Rule(BaseModel):
    rule: str = Field(description="Rule or policy id, e.g. 'refund.max_auto_amount'")
    result: Literal["pass", "fail", "not_applicable"] = "pass"
    detail: str | None = Field(default=None, description="e.g. 'Amount $850 exceeds $500 limit'")


class Exception_(BaseModel):
    rule: str = Field(description="The rule that was waived")
    reason: str
    granted_by: str = Field(description="Who granted it, e.g. 'meera (support lead)'")


class Approval(BaseModel):
    step: Literal["requested", "approved", "rejected", "edited", "escalated"] = "approved"
    by: str
    note: str | None = None


def _label(text: str, default: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_.]+", "_", text.strip().lower()).strip("._")
    cleaned = re.sub(r"\.{2,}", ".", cleaned)
    return cleaned[:128] or default


def _person(text: str) -> dict[str, Any]:
    match = re.match(r"^\s*(.+?)\s*\((.+)\)\s*$", text)
    name, role = (match.group(1), match.group(2)) if match else (text.strip(), None)
    person: dict[str, Any] = {
        "type": "human",
        "id": f"user:{_label(name, 'unknown')}",
        "name": name,
    }
    if role:
        person["role"] = role[:128]
    return person


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _store() -> Store:
    config = load_config()
    if not config.db_path.exists():
        config = init_home(config.home)
    return Store.open(config)


def record_decision(
    intent: str,
    kind: str = "general.decision",
    context: list[str] | None = None,
    rules: list[Rule] | None = None,
    exceptions: list[Exception_] | None = None,
    rejected: list[str] | None = None,
    approvals: list[Approval] | None = None,
    actions: list[str] | None = None,
    outcome: Literal["pending", "accepted", "reverted", "escalated", "failed"] | None = None,
    agent: str = "mcp-client",
    on_behalf_of: str | None = None,
    client_name: str = "mcp",
    local_user: bool = True,
) -> dict[str, Any]:
    now = _now()
    if on_behalf_of:
        principal: dict[str, Any] | None = _person(on_behalf_of)
    elif local_user:
        principal = {"type": "human", "id": f"user:{_label(getpass.getuser(), 'local')}"}
    else:
        principal = None  # a shared server does not know who is behind the request
    agent_actor = {"type": "agent", "id": f"mcp:{_label(agent, 'client')}", "name": agent[:256]}
    record: dict[str, Any] = {
        "record_type": "decision",
        "schema_version": SCHEMA_VERSION,
        "id": new_ulid(),
        "namespace": load_config().namespace,
        "decision_kind": _label(kind, "general.decision"),
        "intent": intent.strip()[:500] or "Decision",
        "actor_time": {
            "actor": agent_actor,
            **({"on_behalf_of": principal} if principal else {}),
            "client": {"name": client_name[:128] or "mcp"},
            "started_at": now,
        },
        "attributes": {"decisiontrace.adapter": "mcp"},
    }
    if context:
        record["context"] = {
            "inputs": [
                {"type": "note", "ref": f"mcp:{i}", "summary": c[:2000]}
                for i, c in enumerate(context)
            ]
        }
    if rules:
        record["policies"] = [
            {
                "policy_id": r.rule[:256],
                "result": r.result,
                **({"detail": r.detail[:2000]} if r.detail else {}),
            }
            for r in rules
        ]
    if exceptions:
        record["exceptions"] = [
            {
                "policy_id": e.rule[:256],
                "reason": e.reason[:2000],
                "granted_by": _person(e.granted_by),
                "at": now,
            }
            for e in exceptions
        ]
    if rejected:
        record["alternatives"] = [
            {
                "action": {
                    "type": "other",
                    "name": "option",
                    "summary": r[:2000],
                    "status": "proposed",
                },
                "rejected_by": "human",
            }
            for r in rejected
        ]
    if approvals:
        record["human_path"] = [
            {
                "type": a.step,
                "actor": _person(a.by),
                "at": now,
                **({"detail": a.note[:2000]} if a.note else {}),
            }
            for a in approvals
        ]
    if actions:
        record["actions"] = [
            {"type": "other", "name": "action", "summary": a[:2000]} for a in actions
        ]
    if outcome:
        record["outcome"] = {"status": outcome}
    with _store() as store:
        result = store.append(record)
    return {"id": result.record.id, "redactions": result.redactions}


def recall_decisions(query: str, limit: int = 5, kind: str | None = None) -> dict[str, Any]:
    limit = max(1, min(limit, 20))
    with _store() as store:
        hits = []
        q = query.strip()
        if _ULIDISH.match(q):
            try:
                base = store.get(q)
            except StoreError:
                base = None
            if isinstance(base, DecisionTrace):
                hits = similar(store, base, limit=limit)
        if not hits:
            hits = search(store, q, limit=limit, kind=_label(kind, "") if kind else None)
        precedents = []
        for hit in hits:
            view = precedent_view(store, hit.trace)
            view["score"] = hit.score
            view["strength"] = hit.strength
            if hit.components:
                view["similarity"] = hit.components
            precedents.append(view)
    return {"query": query, "count": len(precedents), "precedents": precedents}


def record_outcome(
    decision_id: str,
    status: Literal[
        "accepted", "reverted", "overridden", "escalated", "failed", "complained", "other"
    ],
    note: str | None = None,
) -> dict[str, Any]:
    with _store() as store:
        trace = store.get(decision_id)
        if not isinstance(trace, DecisionTrace):
            raise ValueError(f"{decision_id} is not a decision")
        record: dict[str, Any] = {
            "record_type": "outcome",
            "schema_version": SCHEMA_VERSION,
            "id": new_ulid(),
            "namespace": trace.namespace,
            "trace_id": trace.id,
            "status": status,
            "recorded_by": {"type": "agent", "id": "mcp:client"},
            "recorded_at": _now(),
        }
        if note:
            record["note"] = note[:2000]
        store.append(record)
    return {"decision": trace.id, "intent": trace.intent, "status": status}


TOOLS = ("record", "recall", "outcome")


def build_server(
    tools: tuple[str, ...] | list[str] = TOOLS, client_name: str = "mcp", local_user: bool = True
) -> MCPServer:
    """The MCP server. ``tools`` limits what is exposed (e.g. no ``recall`` on a shared server);
    ``local_user=False`` for a shared server: decisions are not attributed to its OS account."""
    unknown = set(tools) - set(TOOLS)
    if unknown:
        raise ValueError(
            f"unknown tool(s): {', '.join(sorted(unknown))}; choose from {', '.join(TOOLS)}"
        )
    server = MCPServer(name="decisiontrace", title="DecisionTrace", instructions=INSTRUCTIONS)

    if "record" in tools:

        @server.tool(
            name="record",
            description="Record a decision: rules checked, exceptions, rejected options, approvals.",
        )
        def record(
            intent: str,
            kind: str = "general.decision",
            context: list[str] | None = None,
            rules: list[Rule] | None = None,
            exceptions: list[Exception_] | None = None,
            rejected: list[str] | None = None,
            approvals: list[Approval] | None = None,
            actions: list[str] | None = None,
            outcome: Literal["pending", "accepted", "reverted", "escalated", "failed"]
            | None = None,
            agent: str = "mcp-client",
            on_behalf_of: str | None = None,
        ) -> dict[str, Any]:
            """Record a decision. `kind` is a dotted label like 'refund.approve'. `on_behalf_of`:
            the person you are working for, e.g. 'Meera (support lead)', when known."""
            return record_decision(
                intent,
                kind,
                context,
                rules,
                exceptions,
                rejected,
                approvals,
                actions,
                outcome,
                agent,
                on_behalf_of=on_behalf_of,
                client_name=client_name,
                local_user=local_user,
            )

    if "recall" in tools:

        @server.tool(
            name="recall",
            description="Find how similar decisions were handled before (rules, exceptions, approvals, outcome).",
        )
        def recall(query: str, limit: int = 5, kind: str | None = None) -> dict[str, Any]:
            """`query` is a description ('refund over the limit') or a decision id to find precedents for."""
            return recall_decisions(query, limit, kind)

    if "outcome" in tools:

        @server.tool(name="outcome", description="Record what happened after a past decision.")
        def outcome(
            decision_id: str,
            status: Literal[
                "accepted", "reverted", "overridden", "escalated", "failed", "complained", "other"
            ],
            note: str | None = None,
        ) -> dict[str, Any]:
            """Attach an outcome to a decision (by id or unique prefix)."""
            return record_outcome(decision_id, status, note)

    return server


def main() -> None:
    build_server().run("stdio")
