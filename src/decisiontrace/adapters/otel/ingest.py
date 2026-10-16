"""Turn OpenTelemetry GenAI spans into DecisionTraces.

Point an existing OTLP/HTTP exporter at ``http://localhost:4318`` while ``dt ingest-otel``
runs (JSON always; protobuf with the ``[otel]`` extra), or feed it OTLP JSON files.

Mapping (semantic conventions as in opentelemetry-semantic-conventions 0.66b1):

* a span with ``gen_ai.operation.name = invoke_agent`` is one decision; without agent spans,
  each trace's root span is
* ``execute_tool`` spans → actions (``gen_ai.tool.name``, ``gen_ai.tool.call.id``; error status
  → failed); tool arguments are hashed, never stored
* model, provider, conversation id and token usage → ``actor_time``
* span events ``decisiontrace.policy`` / ``.exception`` / ``.approval`` / ``.rejected`` carry
  rule checks, exceptions, approvals and rejected options
* message content attributes (``gen_ai.input.messages``, ``gen_ai.output.messages``,
  ``gen_ai.system_instructions``, tool results) are never read
"""

from __future__ import annotations

import base64
import json
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from decisiontrace.ids import stable_ulid
from decisiontrace.model import SCHEMA_VERSION
from decisiontrace.recorder import clip, person, sha

ERROR = {2, "STATUS_CODE_ERROR"}


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: str
    name: str
    start_ns: int
    end_ns: int
    attrs: dict[str, Any]
    events: list[tuple[str, dict[str, Any]]]
    error: bool
    resource: dict[str, Any] = field(default_factory=dict)


def _value(v: dict[str, Any]) -> Any:
    for key in ("stringValue", "boolValue", "doubleValue"):
        if key in v:
            return v[key]
    if "intValue" in v:
        return int(v["intValue"])
    if "arrayValue" in v:
        return [_value(x) for x in v["arrayValue"].get("values", [])]
    return None


def _attrs(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    return {a["key"]: _value(a.get("value", {})) for a in items or []}


def _hex(value: str, base64_ids: bool) -> str:
    if not value:
        return ""
    if base64_ids:
        return base64.b64decode(value).hex()
    return value.lower()


def parse_otlp_json(payload: dict[str, Any], base64_ids: bool = False) -> list[Span]:
    spans = []
    for rs in payload.get("resourceSpans", []):
        resource = _attrs(rs.get("resource", {}).get("attributes"))
        for ss in rs.get("scopeSpans", []):
            for s in ss.get("spans", []):
                status = s.get("status", {}) or {}
                spans.append(
                    Span(
                        trace_id=_hex(s.get("traceId", ""), base64_ids),
                        span_id=_hex(s.get("spanId", ""), base64_ids),
                        parent_id=_hex(s.get("parentSpanId", ""), base64_ids),
                        name=str(s.get("name", "")),
                        start_ns=int(s.get("startTimeUnixNano", 0)),
                        end_ns=int(s.get("endTimeUnixNano", 0)),
                        attrs=_attrs(s.get("attributes")),
                        events=[
                            (e.get("name", ""), _attrs(e.get("attributes")))
                            for e in s.get("events", [])
                        ],
                        error=status.get("code") in ERROR,
                        resource=resource,
                    )
                )
    return spans


def parse_otlp_protobuf(body: bytes) -> list[Span]:
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    request = ExportTraceServiceRequest()
    request.ParseFromString(body)
    return parse_otlp_json(MessageToDict(request), base64_ids=True)


def _iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _op(span: Span) -> str:
    return str(span.attrs.get("gen_ai.operation.name", ""))


def decisions_from_spans(spans: list[Span], namespace: str = "local") -> list[dict[str, Any]]:
    by_id = {s.span_id: s for s in spans}
    order = {s.span_id: i for i, s in enumerate(spans)}
    children: dict[str, list[Span]] = defaultdict(list)
    for s in spans:
        children[s.parent_id].append(s)
    roots = [s for s in spans if _op(s) == "invoke_agent"]
    if not roots:
        roots = [s for s in spans if not s.parent_id or s.parent_id not in by_id]
    agent_ids = {r.span_id for r in roots}

    def subtree(root: Span) -> list[Span]:
        out, stack = [], [root]
        while stack:
            node = stack.pop()
            out.append(node)
            # nested agent spans are their own decisions
            stack.extend(c for c in children.get(node.span_id, []) if c.span_id not in agent_ids)
        return out

    records = []
    for root in roots:
        records.append(
            _decision(
                root,
                sorted(subtree(root), key=lambda s: (s.start_ns, order[s.span_id])),
                namespace,
                [c for c in children.get(root.span_id, []) if c.span_id in agent_ids],
            )
        )
    return records


def _decision(
    root: Span, spans: list[Span], namespace: str, child_agents: list[Span]
) -> dict[str, Any]:
    a = root.attrs
    agent_name = a.get("gen_ai.agent.name") or root.resource.get("service.name") or "agent"
    actor: dict[str, Any] = {
        "type": "agent",
        "id": clip(str(a.get("gen_ai.agent.id") or f"agent:{agent_name}"), 256),
        "name": clip(str(agent_name), 256),
    }
    rec: dict[str, Any] = {
        "record_type": "decision",
        "schema_version": SCHEMA_VERSION,
        "id": _decision_id(root),
        "namespace": namespace,
        "decision_kind": str(a.get("decisiontrace.decision_kind") or "agent.decision"),
        "intent": clip(
            str(a.get("decisiontrace.intent") or a.get("gen_ai.agent.description") or root.name),
            500,
        ),
    }
    actions, policies, exceptions, human, alternatives = [], [], [], [], []
    model = provider = conversation = None
    tokens = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
    for s in spans:
        sa = s.attrs
        model = model or sa.get("gen_ai.response.model") or sa.get("gen_ai.request.model")
        provider = provider or sa.get("gen_ai.provider.name") or sa.get("gen_ai.system")
        conversation = conversation or sa.get("gen_ai.conversation.id")
        if _op(s) in ("chat", "text_completion", "generate_content"):
            tokens["input_tokens"] += int(sa.get("gen_ai.usage.input_tokens") or 0)
            tokens["output_tokens"] += int(sa.get("gen_ai.usage.output_tokens") or 0)
            tokens["cache_read_input_tokens"] += int(
                sa.get("gen_ai.usage.cache_read.input_tokens") or 0
            )
        if _op(s) == "execute_tool":
            action: dict[str, Any] = {
                "type": "tool_call",
                "name": clip(str(sa.get("gen_ai.tool.name") or s.name), 256),
            }
            if sa.get("gen_ai.tool.call.id"):
                action["call_id"] = clip(str(sa["gen_ai.tool.call.id"]), 256)
            if sa.get("gen_ai.tool.call.arguments") is not None:
                action["parameters_hash"] = sha(sa["gen_ai.tool.call.arguments"])
            if sa.get("gen_ai.tool.description"):
                action["summary"] = clip(str(sa["gen_ai.tool.description"]), 2000)
            if s.error:
                action["status"] = "failed"
            actions.append(action)
        for name, ev in s.events:
            at = _iso(s.end_ns or s.start_ns)
            if name == "decisiontrace.policy" and ev.get("policy_id"):
                p: dict[str, Any] = {
                    "policy_id": clip(str(ev["policy_id"]), 256),
                    "result": str(ev.get("result", "pass")),
                }
                if ev.get("detail"):
                    p["detail"] = clip(str(ev["detail"]), 2000)
                if ev.get("enforced"):
                    p["enforced"] = True
                policies.append(p)
            elif name == "decisiontrace.exception" and ev.get("policy_id"):
                exceptions.append(
                    {
                        "policy_id": clip(str(ev["policy_id"]), 256),
                        "reason": clip(str(ev.get("reason") or "-"), 2000),
                        "granted_by": person(str(ev.get("granted_by") or "unknown")),
                        "at": at,
                    }
                )
            elif name == "decisiontrace.approval":
                step: dict[str, Any] = {
                    "type": str(ev.get("step", "approved")),
                    "actor": person(str(ev.get("by") or "unknown")),
                    "at": at,
                }
                if ev.get("detail"):
                    step["detail"] = clip(str(ev["detail"]), 2000)
                human.append(step)
            elif name == "decisiontrace.rejected" and ev.get("name"):
                alt: dict[str, Any] = {
                    "action": {
                        "type": "tool_call",
                        "name": clip(str(ev["name"]), 256),
                        "status": "cancelled",
                    },
                    "rejected_by": str(ev.get("by", "model")),
                }
                if ev.get("reason"):
                    alt["reason"] = clip(str(ev["reason"]), 2000)
                alternatives.append(alt)
    for key, value in (
        ("policies", policies),
        ("exceptions", exceptions),
        ("actions", actions),
        ("alternatives", alternatives),
        ("human_path", human),
    ):
        if value:
            rec[key] = value
    actor_time: dict[str, Any] = {"actor": actor, "started_at": _iso(root.start_ns)}
    if root.end_ns > root.start_ns:
        actor_time["ended_at"] = _iso(root.end_ns)
    if model:
        actor_time["model"] = {
            "provider": str(provider or "unknown"),
            "name": clip(str(model), 128),
        }
    if conversation:
        actor_time["session_id"] = clip(str(conversation), 256)
    if any(tokens.values()):
        actor_time["cost"] = tokens
    actor_time["client"] = {"name": "opentelemetry"}
    rec["actor_time"] = actor_time
    if root.error:
        rec["outcome"] = {"status": "failed"}
    elif actions:
        rec["outcome"] = {"status": "pending"}
    if child_agents:
        rec["links"] = [{"type": "delegation", "target_id": _decision_id(c)} for c in child_agents]
    rec["attributes"] = {
        "decisiontrace.adapter": "otel",
        "otel.trace_id": root.trace_id,
        "otel.span_id": root.span_id,
    }
    return rec


def _decision_id(span: Span) -> str:
    return stable_ulid(span.start_ns // 1_000_000, f"otel:{span.trace_id}:{span.span_id}")


def store_decisions(store: Any, records: list[dict[str, Any]]) -> int:
    fresh = [r for r in records if not store.has(r["id"])]
    # children first so delegation targets exist in the same batch order
    fresh.sort(key=lambda r: bool(r.get("links")))
    if fresh:
        store.append_many(fresh)
    return len(fresh)


class Buffer:
    """Collects spans per trace and flushes a trace once it has gone quiet."""

    def __init__(self, store_factory: Any, namespace: str, settle_seconds: float = 2.0) -> None:
        self.spans: dict[str, list[Span]] = defaultdict(list)
        self.touched: dict[str, float] = {}
        self.lock = threading.Lock()
        self.store_factory = store_factory
        self.namespace = namespace
        self.settle = settle_seconds
        self.added = 0

    def add(self, spans: list[Span]) -> None:
        with self.lock:
            for s in spans:
                self.spans[s.trace_id].append(s)
                self.touched[s.trace_id] = time.time()

    def flush(self, force: bool = False) -> int:
        with self.lock:
            now = time.time()
            ready = [t for t, ts in self.touched.items() if force or now - ts >= self.settle]
            batches = [self.spans.pop(t) for t in ready]
            for t in ready:
                self.touched.pop(t, None)
        records = [r for batch in batches for r in decisions_from_spans(batch, self.namespace)]
        if not records:
            return 0
        with self.store_factory() as store:
            n = store_decisions(store, records)
        self.added += n
        return n


def make_server(buffer: Buffer, host: str = "127.0.0.1", port: int = 4318) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path.rstrip("/") != "/v1/traces":
                self.send_response(404)
                self.end_headers()
                return
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            kind = self.headers.get("Content-Type", "")
            try:
                if "json" in kind:
                    spans = parse_otlp_json(json.loads(body or b"{}"))
                    reply, reply_type = b"{}", "application/json"
                else:
                    spans = parse_otlp_protobuf(body)
                    reply, reply_type = b"", "application/x-protobuf"
            except ImportError:
                self.send_response(415)
                self.end_headers()
                self.wfile.write(
                    b"protobuf needs: pip install 'liquicent-decisiontrace[otel]' (or use http/json)"
                )
                return
            except Exception:
                self.send_response(400)
                self.end_headers()
                return
            buffer.add(spans)
            self.send_response(200)
            self.send_header("Content-Type", reply_type)
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args: Any) -> None:  # keep stdout clean
            return

    return ThreadingHTTPServer((host, port), Handler)
