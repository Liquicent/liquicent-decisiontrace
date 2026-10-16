# OpenTelemetry

Already instrumented with OpenTelemetry GenAI spans? Don't change the agent — point its
exporter at DecisionTrace:

```bash
dt ingest-otel                          # listens on http://127.0.0.1:4318/v1/traces
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

OTLP/HTTP JSON works out of the box; protobuf (the default for most exporters) needs
`pip install 'liquicent-decisiontrace[otel]'`. Files from a collector's file exporter:
`dt ingest-otel --file spans.json`. Re-ingesting the same spans never duplicates.

| Span | DecisionTrace |
|---|---|
| `gen_ai.operation.name = invoke_agent` (else the trace root) | one decision; nested agents become linked decisions |
| `execute_tool` spans | `actions` (`gen_ai.tool.name`, `gen_ai.tool.call.id`, error status → failed) |
| `gen_ai.request/response.model`, `gen_ai.provider.name`, `gen_ai.usage.*` | `actor_time.model`, `.cost` |
| `gen_ai.conversation.id`, `gen_ai.agent.id/name` | `actor_time.session_id`, `.actor` |
| attributes `decisiontrace.intent`, `decisiontrace.decision_kind` | `intent`, `decision_kind` |
| span events `decisiontrace.policy` (`policy_id`, `result`, `detail`, `enforced`) | `policies` |
| span events `decisiontrace.exception` (`policy_id`, `reason`, `granted_by`) | `exceptions` |
| span events `decisiontrace.approval` (`step`, `by`, `detail`) | `human_path` |
| span events `decisiontrace.rejected` (`name`, `by`, `reason`) | `alternatives` |

Never read: `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`,
tool results. Tool arguments are hashed. Conventions pinned to
`opentelemetry-semantic-conventions` 0.66b1.

Example: `uv run python examples/otel_agent.py`.
