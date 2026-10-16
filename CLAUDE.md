# DecisionTrace — repo instructions for Claude Code

DecisionTrace is the open-source half of Liquicent. It records **why** an AI-assisted
decision was made, at the moment it is made, so it can be recalled, audited and reused
as precedent later.

Company line: **DecisionTrace records. Valence reveals. Liquicent learns.**
This repo is only the "records" part, plus the local recall that makes recording worth it.

## Non-negotiables

1. **Capture at execution time.** A trace that is not captured when the decision happens
   cannot be rebuilt afterwards (the before/after state doesn't contain the rejected
   options or the approval path). Every adapter hooks into the live path.
2. **Append-only and tamper-evident.** Traces are never updated or deleted in place.
   Outcomes and corrections are new linked records. Each record carries the hash of the
   previous one (per-store hash chain).
3. **Sit on top of existing control planes, never replace them.** No gateway, no proxy,
   no interception layer. We read hooks, spans and SDK callbacks that already exist.
4. **Local-first, zero-config.** `pip install liquicent-decisiontrace && dt init` must work offline
   on a laptop with SQLite. No account, no server, no telemetry home.
5. **Capabilities are discovered, not declared.** Never require users to write a
   manifest of what their agents do. Infer capability labels from traces.
6. **Privacy by default.** Redact secrets and PII before write. Store prompt/response
   bodies only when the user opts in; store hashes and summaries otherwise.
7. **Record execution, not cognition.** Never store model reasoning or chain-of-thought.
   Store inputs, evaluations, actions, rejected alternatives, approvals and outcomes.

## The record

A DecisionTrace is `DT = ⟨C, P, E, X, H, T, O⟩`:

| Field | Meaning | Examples |
|---|---|---|
| `C` context | Inputs the decision was made on | ticket id, customer, files read, retrieved docs |
| `P` policies | Rules evaluated, with pass/fail | refund limit, CEL/OPA rule ids, Authority Envelope |
| `E` exceptions | Rules overridden and by whom | "limit waived — VIP" |
| `X` alternatives | Options considered and rejected | other tool calls proposed, denied permissions |
| `H` human path | Approvals, edits, escalations | approved by, edited diff, time-to-approve |
| `T` actor & time | Who/what decided, when, with what | agent, model, user, tool, timestamps, cost |
| `O` outcome | What happened, filled later via `dt outcome` | accepted, reverted, customer complained |

The canonical schema lives in `schema/decisiontrace.schema.json` (JSON Schema, versioned).
Python models in `src/decisiontrace/model.py` are generated from or validated against it.
Field names map to OTel GenAI semantic conventions wherever one exists.

## Stack

- Python 3.11+, `uv` for env and packaging, `ruff` + `mypy --strict`, `pytest`
- Store: SQLite (WAL) + `sqlite-vec` for similarity; optional Postgres + pgvector backend later
- CLI: `typer`. MCP server: official `mcp` Python SDK
- Embeddings: pluggable; default is a small local model, never a paid API by default
- Licence: Apache-2.0, contributions under DCO (sign-off), not a CLA

## Layout

```
schema/                 JSON Schema + example traces
src/decisiontrace/
  model.py              record types
  store/                sqlite backend, hash chain, migrations
  redact.py             secret/PII redaction
  adapters/             claude_code/, mcp/, otel/, anthropic_sdk/, openai_sdk/
  recall/               similarity, precedent, why/ask
  cli.py                dt command
  mcp_server.py         decisiontrace.recall / record / outcome tools
tests/                  unit + golden traces
examples/               runnable demos
docs/                   BUILD_PLAN.md, adapter guides
```

## Commands (keep these working at all times)

```
uv run pytest -q
uv run ruff check . && uv run mypy src
uv run dt --help
```

## How we work

- Team of two: Praveen and Claude Code. Praveen gives short directional prompts and
  expects complete, working, tested output — don't stop to ask unless a decision is
  irreversible or truly ambiguous; state the assumption and continue.
- Work one phase of `docs/BUILD_PLAN.md` at a time. Finish its exit test before moving on.
- Every change: tests first or alongside, all checks green, short commit message.
- Before any step likely to take more than 10 minutes (big refactor, long test run,
  model download), say so and give a time estimate.
- At the end of each session, append a dated entry to `docs/progress-log.md`:
  what was done, what's next, open decisions.

## Out of scope for this repo (open-core boundary)

See `docs/DECISIONS.md` (D1). Rule of thumb: if it needs many people's traces, or acts on
traces instead of recording and recalling them, it belongs to Liquicent, not here.

Valence reports, compounding score, WorkRank / trust routing, Company Brain, multi-tenant
SaaS, SSO, org-wide dashboards. Design interfaces so these can consume the store, but do
not build them here.
