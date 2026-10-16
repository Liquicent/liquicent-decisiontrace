"""An agent instrumented with plain OpenTelemetry (GenAI conventions), recorded by
DecisionTrace without touching the agent's code: just point the exporter at `dt ingest-otel`.

    uv run python examples/otel_agent.py                 # starts an embedded ingester
    dt ingest-otel &  uv run python examples/otel_agent.py --endpoint http://localhost:4318

Rule checks, exceptions and approvals are ordinary span events named `decisiontrace.*`.
"""

from __future__ import annotations

import argparse
import threading
import time

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import Status, StatusCode


def run_agent(tracer: trace.Tracer, order_id: str = "7731", amount: int = 850) -> None:
    with tracer.start_as_current_span("invoke_agent refunds") as agent:
        agent.set_attribute("gen_ai.operation.name", "invoke_agent")
        agent.set_attribute("gen_ai.agent.name", "refunds")
        agent.set_attribute("gen_ai.conversation.id", "conv-42")
        agent.set_attribute("decisiontrace.decision_kind", "refund.approve")
        agent.set_attribute("decisiontrace.intent", f"Refund ${amount} for order {order_id}")
        with tracer.start_as_current_span("chat claude-opus-5-5") as chat:
            chat.set_attribute("gen_ai.operation.name", "chat")
            chat.set_attribute("gen_ai.provider.name", "anthropic")
            chat.set_attribute("gen_ai.request.model", "claude-opus-5-5")
            chat.set_attribute("gen_ai.usage.input_tokens", 1200)
            chat.set_attribute("gen_ai.usage.output_tokens", 140)
            chat.set_attribute(
                "gen_ai.input.messages", '[{"role":"user","content":"secret customer text"}]'
            )
        with tracer.start_as_current_span("execute_tool issue_refund") as tool:
            tool.set_attribute("gen_ai.operation.name", "execute_tool")
            tool.set_attribute("gen_ai.tool.name", "issue_refund")
            tool.set_attribute("gen_ai.tool.call.id", "call_1")
            tool.set_attribute(
                "gen_ai.tool.call.arguments", f'{{"order_id": "{order_id}", "amount": {amount}}}'
            )
            tool.add_event(
                "decisiontrace.policy",
                {
                    "policy_id": "refund.max_auto_amount",
                    "result": "fail",
                    "detail": f"${amount} exceeds $500",
                    "enforced": True,
                },
            )
            tool.add_event(
                "decisiontrace.exception",
                {
                    "policy_id": "refund.max_auto_amount",
                    "reason": "carrier damage",
                    "granted_by": "Meera (support lead)",
                },
            )
            tool.add_event(
                "decisiontrace.approval", {"step": "approved", "by": "Meera (support lead)"}
            )
        with tracer.start_as_current_span("execute_tool notify_customer") as tool:
            tool.set_attribute("gen_ai.operation.name", "execute_tool")
            tool.set_attribute("gen_ai.tool.name", "notify_customer")
            tool.set_status(Status(StatusCode.ERROR, "smtp down"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--endpoint", help="running `dt ingest-otel` (default: start one in-process)"
    )
    args = parser.parse_args()
    buffer = server = None
    endpoint = args.endpoint
    if not endpoint:
        from decisiontrace.adapters.otel.ingest import Buffer, make_server
        from decisiontrace.config import init_home
        from decisiontrace.store import Store

        config = init_home()
        buffer = Buffer(lambda: Store.open(config), config.namespace, settle_seconds=0)
        server = make_server(buffer, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
    provider = TracerProvider(resource=Resource.create({"service.name": "refund-service"}))
    provider.add_span_processor(
        SimpleSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    run_agent(provider.get_tracer("refund-agent"))
    provider.force_flush()
    if buffer is not None and server is not None:
        time.sleep(0.2)
        print(f"{buffer.flush(force=True)} decision(s) recorded from OpenTelemetry spans.")
        server.shutdown()
    print("Try:  dt log   ·   dt why <id>")


if __name__ == "__main__":
    main()
