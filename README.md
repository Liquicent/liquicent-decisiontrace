# DecisionTrace

**Record *why* your AI made a decision, at the moment it's made.**

Logs and traces tell you *what* an AI did. DecisionTrace records *why it was allowed to*:
the context it used, the rules it checked, the exceptions granted, the options it rejected,
who approved it, and what happened next. Records are append-only, tamper-evident and stay on
your machine.

> **Status: pre-alpha.** Schema, local store (append-only, hash-chained, redacted) and
> `dt init / append / log / show / outcome / verify / export` work today. The Claude Code
> adapter, MCP server and `dt why` are next — see [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md).

## The record

Every decision is `DT = ⟨C, P, E, X, H, T, O⟩`:

| | Field | Example |
|---|---|---|
| C | context | ticket 88412, order 7731, VIP customer |
| P | policies | `refund.max_auto_amount` → fail |
| E | exceptions | limit waived by support lead: carrier damage |
| X | alternatives | partial refund of $500, rejected |
| H | human path | approval requested → approved after 9 min |
| T | actor & time | refunds agent, model, cost $0.04 |
| O | outcome | pending → accepted |

See [`schema/README.md`](schema/README.md) and [`schema/examples/`](schema/examples/).

## Try it

```bash
git clone https://github.com/vpsingh88/liquicent-decisiontrace && cd liquicent-decisiontrace
uv sync
uv run dt init
uv run dt append schema/examples/*.json   # load the example decisions
uv run dt log
uv run dt show 01M4ZCMB                   # the $850 refund: rules, exception, approval
uv run dt verify                          # recompute the hash chain
```

## Principles

- Capture at execution time — a decision's rejected options and approvals can't be
  rebuilt later.
- Append-only and tamper-evident.
- Sits on top of the tools you already use. No gateway, no proxy.
- Local-first: SQLite on your laptop, no account, no telemetry.
- Privacy by default: secrets and PII redacted; no model reasoning stored, ever.

## Licence

Apache-2.0. Contributions under the [DCO](CONTRIBUTING.md#developer-certificate-of-origin-dco).

DecisionTrace is the open-source part of [Liquicent](https://liquicent.com):
*DecisionTrace records. Valence reveals. Liquicent learns.*
