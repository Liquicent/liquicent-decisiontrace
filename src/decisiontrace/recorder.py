"""Record decisions from your own code, in any framework.

    import decisiontrace as dt

    with dt.decision("refund.approve", intent="Refund $850 for order 7731") as d:
        d.context("order", "shopify:7731", summary="delivered damaged")
        d.policy("refund.max_auto_amount", "fail", detail="$850 > $500", enforced=True)
        d.exception("refund.max_auto_amount", "VIP, carrier damage", granted_by="meera (support lead)")
        d.approval("approved", by="meera (support lead)")
        d.action("stripe.refunds.create", summary="Full refund $850")

Inside tool code called during a wrapped SDK loop (see ``decisiontrace.wrap``) the same
calls work without a handle: ``dt.policy(...)``, ``dt.exception(...)``, ``dt.approval(...)``,
``dt.reject(...)`` attach to the decision currently being recorded.

The record is written when the ``with`` block ends (or the wrapped loop finishes). Recording
never raises into your code: failures go to ``~/.decisiontrace/recorder-errors.log``.
"""

from __future__ import annotations

import contextvars
import getpass
import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from decisiontrace.config import init_home, load_config
from decisiontrace.ids import new_ulid
from decisiontrace.model import SCHEMA_VERSION

_current: contextvars.ContextVar[DecisionBuilder | None] = contextvars.ContextVar(
    "decisiontrace_current", default=None
)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _label(text: str, default: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_.]+", "_", text.strip().lower()).strip("._")
    return re.sub(r"\.{2,}", ".", cleaned)[:128] or default


def person(text: str, kind: str = "human") -> dict[str, Any]:
    """'meera (support lead)' → actor with name and role."""
    match = re.match(r"^\s*(.+?)\s*\((.+)\)\s*$", text)
    name, role = (match.group(1), match.group(2)) if match else (text.strip(), None)
    actor: dict[str, Any] = {
        "type": kind,
        "id": f"{'user' if kind == 'human' else kind}:{_label(name, 'unknown')}",
        "name": name[:256],
    }
    if role:
        actor["role"] = role[:128]
    return actor


def sha(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def clip(text: str, limit: int = 240) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


class DecisionBuilder:
    """Collects the parts of one DecisionTrace and writes it once."""

    def __init__(
        self,
        kind: str = "agent.decision",
        intent: str = "",
        agent: str = "agent",
        on_behalf_of: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.id = new_ulid()
        self.kind = _label(kind, "agent.decision")
        self.intent = intent
        self.started_at = _now()
        self.actor: dict[str, Any] = {
            "type": "agent",
            "id": f"agent:{_label(agent, 'agent')}",
            "name": agent[:256],
        }
        self.on_behalf_of = (
            person(on_behalf_of)
            if on_behalf_of
            else {"type": "human", "id": f"user:{_label(getpass.getuser(), 'local')}"}
        )
        self.inputs: list[dict[str, Any]] = []
        self.policies: list[dict[str, Any]] = []
        self.exceptions: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self.alternatives: list[dict[str, Any]] = []
        self.human: list[dict[str, Any]] = []
        self.capabilities: list[str] = []
        self.model: dict[str, str] | None = None
        self.client: dict[str, str] | None = None
        self.session_id: str | None = None
        self.cost = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
        self.outcome_status: str | None = None
        self.links: list[dict[str, str]] = []
        self.attributes: dict[str, Any] = dict(attributes or {})
        self.written = False

    # -- the C, P, E, X, H parts ------------------------------------------------------------

    def context(
        self, type: str, ref: str, summary: str | None = None, body: str | None = None
    ) -> None:
        item: dict[str, Any] = {"type": _label(type, "input"), "ref": clip(ref, 1024)}
        if summary:
            item["summary"] = clip(summary, 2000)
        if body is not None:
            item["hash"] = sha(body)
        self.inputs.append(item)

    def policy(
        self,
        policy_id: str,
        result: str,
        detail: str | None = None,
        enforced: bool = False,
        engine: str | None = None,
        version: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {"policy_id": clip(policy_id, 256), "result": result}
        if detail:
            entry["detail"] = clip(detail, 2000)
        if enforced:
            entry["enforced"] = True
        if engine:
            entry["engine"] = engine
        if version:
            entry["version"] = version[:64]
        self.policies.append(entry)

    def exception(self, policy_id: str, reason: str, granted_by: str) -> None:
        self.exceptions.append(
            {
                "policy_id": clip(policy_id, 256),
                "reason": clip(reason, 2000),
                "granted_by": person(granted_by),
                "at": _now(),
            }
        )

    def approval(
        self,
        step: str = "approved",
        by: str = "user",
        detail: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        kind = "agent" if by.startswith("agent:") else "human"
        actor = self.actor if kind == "agent" else person(by)
        entry: dict[str, Any] = {"type": step, "actor": actor, "at": _now()}
        if detail:
            entry["detail"] = clip(detail, 2000)
        if latency_ms is not None:
            entry["latency_ms"] = max(0, int(latency_ms))
        self.human.append(entry)

    def action(
        self,
        name: str,
        summary: str | None = None,
        type: str = "tool_call",
        target: str | None = None,
        call_id: str | None = None,
        parameters: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {"type": type, "name": clip(name, 256)}
        if call_id:
            entry["call_id"] = call_id[:256]
        if target:
            entry["target"] = clip(target, 1024)
        if summary:
            entry["summary"] = clip(summary, 2000)
        if parameters is not None:
            entry["parameters_hash"] = sha(parameters)
        if status and status != "executed":
            entry["status"] = status
        self.actions.append(entry)
        return entry

    def reject(
        self,
        name: str,
        by: str = "model",
        reason: str | None = None,
        summary: str | None = None,
        policy_id: str | None = None,
        call_id: str | None = None,
    ) -> None:
        action: dict[str, Any] = {
            "type": "tool_call",
            "name": clip(name, 256),
            "status": "cancelled",
        }
        if summary:
            action["summary"] = clip(summary, 2000)
        if call_id:
            action["call_id"] = call_id[:256]
        alt: dict[str, Any] = {"action": action, "rejected_by": by}
        if reason:
            alt["reason"] = clip(reason, 2000)
        if policy_id:
            alt["policy_id"] = clip(policy_id, 256)
        self.alternatives.append(alt)

    def outcome(self, status: str) -> None:
        self.outcome_status = status

    def capability(self, label: str) -> None:
        cap = _label(label, "")
        if cap and cap not in self.capabilities:
            self.capabilities.append(cap)

    # -- output -----------------------------------------------------------------------------

    def to_record(self, namespace: str = "local") -> dict[str, Any]:
        record: dict[str, Any] = {
            "record_type": "decision",
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "namespace": namespace,
            "decision_kind": self.kind,
            "intent": clip(self.intent or self.kind, 500),
        }
        if self.capabilities:
            record["capabilities"] = self.capabilities
        if self.inputs:
            record["context"] = {"inputs": self.inputs}
        for key, value in (
            ("policies", self.policies),
            ("exceptions", self.exceptions),
            ("actions", self.actions),
            ("alternatives", self.alternatives),
            ("human_path", self.human),
        ):
            if value:
                record[key] = value
        actor_time: dict[str, Any] = {
            "actor": self.actor,
            "on_behalf_of": self.on_behalf_of,
            "started_at": self.started_at,
            "ended_at": _now(),
        }
        if self.model:
            actor_time["model"] = self.model
        if self.client:
            actor_time["client"] = self.client
        if self.session_id:
            actor_time["session_id"] = self.session_id[:256]
        if any(self.cost.values()):
            actor_time["cost"] = dict(self.cost)
        record["actor_time"] = actor_time
        if self.outcome_status:
            record["outcome"] = {"status": self.outcome_status}
        if self.links:
            record["links"] = self.links
        if self.attributes:
            record["attributes"] = self.attributes
        return record

    def write(self) -> str | None:
        """Append to the local store once. Never raises; returns the id or None."""
        if self.written:
            return self.id
        self.written = True
        try:
            from decisiontrace.store import Store

            config = load_config()
            if not config.db_path.exists():
                config = init_home(config.home)
            with Store.open(config) as store:
                store.append(self.to_record(config.namespace))
            return self.id
        except Exception as exc:
            _log_error(exc)
            return None


def _log_error(exc: Exception) -> None:
    try:
        home = load_config().home
        home.mkdir(parents=True, exist_ok=True)
        with (home / "recorder-errors.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{_now()} {type(exc).__name__}: {str(exc)[:300]}\n")
    except OSError:
        pass


@contextmanager
def decision(
    kind: str = "agent.decision",
    intent: str = "",
    agent: str = "agent",
    on_behalf_of: str | None = None,
) -> Iterator[DecisionBuilder]:
    """Record one decision; it is written when the block exits (also on error)."""
    builder = DecisionBuilder(kind, intent, agent, on_behalf_of)
    token = _current.set(builder)
    try:
        yield builder
    except BaseException:
        if builder.outcome_status is None:
            builder.outcome("failed")
        raise
    finally:
        _current.reset(token)
        builder.write()


def current() -> DecisionBuilder | None:
    return _current.get()


def _set_current(builder: DecisionBuilder | None) -> None:
    _current.set(builder)


def policy(
    policy_id: str, result: str, detail: str | None = None, enforced: bool = False, **kw: Any
) -> None:
    """Record a rule check on the decision being recorded (no-op outside one)."""
    if (b := current()) is not None:
        b.policy(policy_id, result, detail, enforced, **kw)


def exception(policy_id: str, reason: str, granted_by: str) -> None:
    if (b := current()) is not None:
        b.exception(policy_id, reason, granted_by)


def approval(step: str = "approved", by: str = "user", detail: str | None = None) -> None:
    if (b := current()) is not None:
        b.approval(step, by, detail)


def reject(name: str, by: str = "model", reason: str | None = None, **kw: Any) -> None:
    if (b := current()) is not None:
        b.reject(name, by, reason, **kw)


def context(type: str, ref: str, summary: str | None = None) -> None:
    if (b := current()) is not None:
        b.context(type, ref, summary)
