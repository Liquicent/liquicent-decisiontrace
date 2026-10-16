from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from decisiontrace.adapters.otel.ingest import (
    Buffer,
    decisions_from_spans,
    make_server,
    parse_otlp_json,
)
from decisiontrace.cli import app
from decisiontrace.model import DecisionTrace, parse_record
from decisiontrace.store import Store


def _kv(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def _span(
    sid: str,
    parent: str,
    name: str,
    attrs: dict[str, Any],
    events: list[Any] | None = None,
    error: bool = False,
    start: int = 1_792_000_000_000_000_000,
) -> dict[str, Any]:
    return {
        "traceId": "ab" * 16,
        "spanId": sid,
        "parentSpanId": parent,
        "name": name,
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(start + 2_000_000_000),
        "attributes": [_kv(k, v) for k, v in attrs.items()],
        "events": [
            {"name": n, "attributes": [_kv(k, v) for k, v in a.items()]} for n, a in events or []
        ],
        "status": {"code": 2} if error else {},
    }


PAYLOAD = {
    "resourceSpans": [
        {
            "resource": {"attributes": [_kv("service.name", "refund-svc")]},
            "scopeSpans": [
                {
                    "spans": [
                        _span(
                            "01" * 8,
                            "",
                            "invoke_agent refunds",
                            {
                                "gen_ai.operation.name": "invoke_agent",
                                "gen_ai.agent.name": "refunds",
                                "decisiontrace.intent": "Refund $850 for order 7731",
                                "decisiontrace.decision_kind": "refund.approve",
                            },
                        ),
                        _span(
                            "02" * 8,
                            "01" * 8,
                            "chat",
                            {
                                "gen_ai.operation.name": "chat",
                                "gen_ai.provider.name": "anthropic",
                                "gen_ai.request.model": "claude-opus-5-5",
                                "gen_ai.usage.input_tokens": 1000,
                                "gen_ai.usage.output_tokens": 90,
                                "gen_ai.input.messages": "TOP SECRET CUSTOMER TEXT",
                            },
                        ),
                        _span(
                            "03" * 8,
                            "01" * 8,
                            "execute_tool issue_refund",
                            {
                                "gen_ai.operation.name": "execute_tool",
                                "gen_ai.tool.name": "issue_refund",
                                "gen_ai.tool.call.id": "c1",
                                "gen_ai.tool.call.arguments": '{"amount": 850}',
                            },
                            events=[
                                (
                                    "decisiontrace.policy",
                                    {
                                        "policy_id": "refund.max_auto_amount",
                                        "result": "fail",
                                        "enforced": True,
                                    },
                                ),
                                (
                                    "decisiontrace.exception",
                                    {
                                        "policy_id": "refund.max_auto_amount",
                                        "reason": "VIP",
                                        "granted_by": "Meera (support lead)",
                                    },
                                ),
                                (
                                    "decisiontrace.approval",
                                    {"step": "approved", "by": "Meera (support lead)"},
                                ),
                                (
                                    "decisiontrace.rejected",
                                    {
                                        "name": "partial_refund",
                                        "by": "human",
                                        "reason": "full damage",
                                    },
                                ),
                            ],
                        ),
                        _span(
                            "04" * 8,
                            "01" * 8,
                            "execute_tool notify",
                            {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "notify"},
                            error=True,
                        ),
                        _span(
                            "05" * 8,
                            "01" * 8,
                            "invoke_agent checker",
                            {
                                "gen_ai.operation.name": "invoke_agent",
                                "gen_ai.agent.name": "fraud-checker",
                            },
                        ),
                        _span(
                            "06" * 8,
                            "05" * 8,
                            "execute_tool score",
                            {
                                "gen_ai.operation.name": "execute_tool",
                                "gen_ai.tool.name": "fraud_score",
                            },
                        ),
                    ]
                }
            ],
        }
    ]
}


def test_mapping() -> None:
    records = decisions_from_spans(parse_otlp_json(PAYLOAD))
    assert len(records) == 2
    parent = next(r for r in records if r["decision_kind"] == "refund.approve")
    child = next(r for r in records if r is not parent)
    assert parse_record(parent) and parse_record(child)
    assert [a["name"] for a in parent["actions"]] == ["issue_refund", "notify"]
    assert parent["actions"][1]["status"] == "failed"
    assert [a["name"] for a in child["actions"]] == ["fraud_score"], "nested agent owns its tools"
    assert parent["links"] == [{"type": "delegation", "target_id": child["id"]}]
    assert parent["exceptions"][0]["granted_by"]["role"] == "support lead"
    assert parent["alternatives"][0]["action"]["name"] == "partial_refund"
    assert parent["actor_time"]["cost"]["input_tokens"] == 1000
    assert parent["actor_time"]["model"] == {"provider": "anthropic", "name": "claude-opus-5-5"}
    assert "TOP SECRET" not in json.dumps(records)


def test_file_ingest_is_idempotent(tmp_path: Path) -> None:
    f = tmp_path / "spans.json"
    f.write_text(json.dumps(PAYLOAD))
    runner = CliRunner()
    home = ["--home", str(tmp_path / "dt")]
    assert (
        "2 decisions from 6 spans"
        in runner.invoke(app, [*home, "ingest-otel", "--file", str(f)]).output
    )
    assert "0 decisions" in runner.invoke(app, [*home, "ingest-otel", "--file", str(f)]).output
    out = (
        runner.invoke(app, [*home, "why", "issue_refund"]).output
        or runner.invoke(app, [*home, "log"]).output
    )
    assert out


def test_real_otlp_protobuf_exporter(config: Any) -> None:
    """An unmodified OTel SDK + OTLP/HTTP protobuf exporter pointed at the ingester."""
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http")
    examples = Path(__file__).resolve().parents[2] / "examples"
    sys.path.insert(0, str(examples))
    import otel_agent
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    buffer = Buffer(lambda: Store.open(config), "local", settle_seconds=0)
    server = make_server(buffer, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        provider = TracerProvider()
        endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1/traces"
        provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        otel_agent.run_agent(provider.get_tracer("t"))
        provider.force_flush()
        time.sleep(0.1)
        assert buffer.flush(force=True) == 1
    finally:
        server.shutdown()
    with Store.open(config) as s:
        (d,) = [r for r in s.records() if isinstance(r, DecisionTrace)]
        raw = b"".join(p.read_bytes() for p in config.home.rglob("*") if p.is_file())
    assert d.intent == "Refund $850 for order 7731"
    assert [a.name for a in d.actions or []] == ["issue_refund", "notify_customer"]
    assert d.policies and d.policies[0].result == "fail"
    assert d.actor_time.session_id == "conv-42"
    assert b"secret customer text" not in raw
