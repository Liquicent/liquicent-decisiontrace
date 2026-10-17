# DecisionTrace schema v0.1.0

`decisiontrace.schema.json` is the canonical, open definition of a DecisionTrace record
(JSON Schema 2020-12). Any tool can emit records that validate against it; this package is
one implementation.

## Records

A store is an append-only sequence of three record types (`record_type`):

| `record_type` | Meaning |
|---|---|
| `decision` | One decision, `DT = ⟨C, P, E, X, H, T, O⟩` |
| `outcome` | An outcome learned later, linked by `trace_id` (never an edit); an accepted one may carry a verified work unit (`vwu`) |
| `correction` | A correction to a decision, linked by `trace_id`; `changes` maps field paths to corrected values |

## Decision fields

| Paper | Field | Contents |
|---|---|---|
| C | `context` | `workflow`, `inputs[]` (typed references, optional hash/summary), `state_before` |
| P | `policies[]` | `policy_id`, `version`/`hash`, `engine`, `result` (pass/fail/not_applicable/error), `enforced` |
| E | `exceptions[]` | Rule overridden, `reason`, `granted_by`, `at` |
| X | `alternatives[]` | Action not taken + `rejected_by` (model/human/policy/system) and why |
| H | `human_path[]` | Typed steps: requested, approved, rejected, edited, escalated, commented, overrode |
| T | `actor_time` | `actor`, `on_behalf_of`, `model`, `client`, `session_id`, `started_at`/`ended_at`, `cost` |
| O | `outcome` | Status known at record time; later outcomes are `outcome` records |
| a_t | `actions[]` | What was actually done (tool call, API call, message, file/memory write, state change) |
| S_t+1 | `state_after` | Reference to the resulting state (e.g. git commit) |

Also: `decision_kind` (dotted label), `intent` (one redacted line), `capabilities[]`
(inferred, never declared), `links[]` (typed edges: context, precedent, reversal, exec,
delegation, hand_off, supersedes), `attributes` (namespaced extension keys), `integrity`
(per-store hash chain, set by the store).

## Rules the schema encodes

- **References, not copies.** Context, state and diffs are pointers plus optional SHA-256.
  Bodies are not part of the record.
- **No reasoning.** There is no field for model reasoning or chain-of-thought, and unknown
  fields are rejected.
- **Typed human path,** so approvals per 100 decisions can be counted without parsing text.
- **Timestamps carry an offset;** IDs are ULIDs (sortable by time).

## Verified work units

An accepted outcome record may carry `vwu`: one completed, accepted and reversible unit of
work that met its quality threshold (the WorkRank paper's VWU).

| Field | Contents |
|---|---|
| `unit` | Dotted label for what one unit is, e.g. `code.change`, `support.ticket` |
| `quantity` | Units delivered (absent means 1) |
| `executor` | Who did the work (absent means the decision's actor) |
| `quality` | `metric` (definition id), `threshold`, `value`, `baseline`, `direction` (higher/lower) |
| `measured` | Measurement window: `started_at`, `ended_at` |
| `verification` | `method` (human, automated, outcome_signal, precedent, sample), `at`, `verifier`, `ref` |
| `reversal` | `window_ends_at`, `max_cost_usd` |

Actors carry `org` (the accountable organisation, e.g. a vendor) and `version` (an agent's
model, prompt and tool bundle). The schema rejects a unit on any status but `accepted`. JSON
Schema cannot compare two values, so the reference implementation and `dt validate` also
reject a value that misses its threshold and windows that end before they start.

## OpenTelemetry GenAI mapping

Pinned to `opentelemetry-semantic-conventions` 0.66b1. Fields carry an `x-otel` annotation.

| DecisionTrace | OTel attribute |
|---|---|
| `actor_time.model.provider` | `gen_ai.provider.name` |
| `actor_time.model.name` | `gen_ai.request.model` |
| `actor_time.session_id` | `gen_ai.conversation.id` |
| `actor_time.actor.id` / `.name` (agents) | `gen_ai.agent.id` / `gen_ai.agent.name` |
| `actor_time.cost.input_tokens` | `gen_ai.usage.input_tokens` |
| `actor_time.cost.output_tokens` | `gen_ai.usage.output_tokens` |
| `actor_time.cost.cache_read_input_tokens` | `gen_ai.usage.cache_read.input_tokens` |
| `actions[].name` (tool calls) | `gen_ai.tool.name` |
| `actions[].call_id` | `gen_ai.tool.call.id` |
| `context.workflow` | `gen_ai.workflow.name` |

## Examples

The `schema/examples/` folder holds ten decisions (refunds, PR merge, Claude Code edit, email draft, denied
tool call, escalated purchase order, memory write, delegation parent/child) plus two outcomes
(one a reverted edit, one a verified work unit) and one correction. Validate any file with `dt validate`.
