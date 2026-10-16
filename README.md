# DecisionTrace

**Record *why* your AI made a decision, at the moment it's made — then ask `dt why` later.**

Logs tell you *what* an agent did. DecisionTrace records *why it was allowed to*: what it
was asked, what it looked at, which rules passed or failed, who granted an exception, what
it considered and rejected, who approved — and what happened next. Everything stays on your
machine, in an append-only, tamper-evident store.

```text
$ dt why c1a90b2
Why: Fix timezone bug in invoice due-date calculation

On 15 Oct 2026 09:30 UTC, Claude Code made a code change for Praveen (model claude-sonnet-5-5, took 8 min, cost $0.37).

It was based on the request "Due dates are a day early for users in IST"; file src/billing/due_dates.py; file tests/test_due_dates.py.

Rules checked (2) — passed: Edit(src/**), Bash(uv run pytest:*).

Considered and rejected:
  - Add +1 day offset for IST users — rejected by model: Patches the symptom; breaks other timezones

No human approval was recorded.

What was done (2 actions): Use aware datetimes in user timezone; uv run pytest tests/test_due_dates.py (12 passed).
Resulting state: git.commit c1a90b2.

Outcome: reverted.
  2026-10-15: reverted — Broke month-end invoices for UTC-8 customers; reverted in c77d013
```

## Five minutes to `dt why`

```bash
pip install liquicent-decisiontrace
dt install claude-code        # hooks into Claude Code; nothing else to configure
```

Use Claude Code as usual. Then:

```bash
dt log                        # today's decisions, grouped by what you asked
dt why <id | file | commit>   # the full account of one decision
dt similar <id>               # past decisions like it, with a similarity breakdown
dt ask "what did we revert last week?"
dt verify                     # recompute the hash chain
```

No Claude Code? Try the showcase without an API key:

```bash
git clone https://github.com/vpsingh88/liquicent-decisiontrace && cd liquicent-decisiontrace
uv sync
uv run python examples/refund_agent.py     # an agent refunds $850, over a $500 limit
uv run dt why "$(uv run dt log -n 1 | awk '{print $3}')"
```

## Where decisions come from

| You use | Do this | Guide |
|---|---|---|
| Claude Code | `dt install claude-code` | [docs/adapters/claude-code.md](docs/adapters/claude-code.md) |
| Claude Desktop, Cursor, any MCP client | `dt install claude-desktop` / `dt install cursor` | [docs/adapters/mcp.md](docs/adapters/mcp.md) |
| Anthropic or OpenAI SDK | `client = dt.wrap(client)` | [docs/adapters/sdk.md](docs/adapters/sdk.md) |
| OpenTelemetry GenAI spans | `dt ingest-otel`, point your exporter at it | [docs/adapters/otel.md](docs/adapters/otel.md) |
| Anything else | `with dt.decision(...) as d:` | [docs/adapters/sdk.md](docs/adapters/sdk.md#without-an-sdk) |

## The record

Every decision is `DT = ⟨C, P, E, X, H, T, O⟩`:

| | Field | Example |
|---|---|---|
| C | context | ticket 88412, order 7731, VIP customer |
| P | policies | `refund.max_auto_amount` → fail |
| E | exceptions | limit waived by the support lead: carrier damage |
| X | alternatives | partial refund of $500, rejected |
| H | human path | approval requested → approved after 9 min |
| T | actor & time | refunds agent, model, tokens, cost |
| O | outcome | pending → accepted (added later with `dt outcome`) |

The schema is an open standard — [schema/README.md](schema/README.md) — with field names
mapped to OpenTelemetry GenAI conventions.

## Principles

- **Captured at execution time.** Rejected options and approvals can't be rebuilt later.
- **Append-only, tamper-evident.** Outcomes and corrections are new linked records; every
  record carries the previous one's hash. `dt verify` recomputes the chain.
- **On top of your tools, not in front of them.** No gateway, no proxy. Hooks, spans and SDK
  callbacks you already have.
- **Local-first.** SQLite in `~/.decisiontrace`. No account, no server, no telemetry.
- **Private by default.** Secrets and personal data are redacted before anything is
  written; prompt bodies are stored only if you opt in; model reasoning is never stored.

## What it is not

Not a gateway or policy enforcer (your code and your tools enforce; DecisionTrace records),
not an observability dashboard, not a hosted service. Team-wide recall, trust scores and
reports are [Liquicent](https://liquicent.com)'s job — *DecisionTrace records. Valence
reveals. Liquicent learns.*

## Status

0.1 — pre-release. Built in the open: [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md),
[docs/progress-log.md](docs/progress-log.md), [CHANGELOG.md](CHANGELOG.md).

Apache-2.0. Contributions under the [DCO](CONTRIBUTING.md#developer-certificate-of-origin-dco).
