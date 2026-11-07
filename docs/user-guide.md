# User guide

DecisionTrace records **why** an AI-assisted decision was made, at the moment it happens:
what was asked, which rules passed or failed, the exceptions and who granted them, the
options that were rejected, who approved, and what happened afterwards. Everything stays
on your machine in a local file. There is no account and no server.

This page walks through the whole lifecycle: install, record, recall, record outcomes,
count verified work, keep the store trustworthy, and share one server with a team.

## 1. Install

You need Python 3.11 or newer.

```bash
sudo apt install pipx          # macOS: brew install pipx
pipx ensurepath                # then close and reopen the terminal
pipx install liquicent-decisiontrace
dt init                        # creates your store in ~/.decisiontrace
dt version                     # check it works
```

`uv tool install liquicent-decisiontrace` works instead of pipx. Inside a project's
virtual environment, plain `pip install liquicent-decisiontrace` works too; outside one,
Debian, Ubuntu and Homebrew Python refuse it with "externally-managed-environment".
Upgrade later with `pipx upgrade liquicent-decisiontrace`.

## 2. Start recording

Pick the tool you already use:

| You use | Run this | What happens |
|---|---|---|
| Claude Code | `dt install claude-code` | Hooks record every decision in every project; `--scope project` records only this repo |
| Claude Desktop | `dt install claude-desktop` | Adds the DecisionTrace MCP server: Claude can record, recall and log outcomes |
| Cursor | `dt install cursor` | The same, for Cursor |
| Your own Python agent | `client = dt.wrap(anthropic.Anthropic())` | Each tool-use loop becomes one decision; `openai.OpenAI()` and the async clients work too |
| An agent already traced with OpenTelemetry | `dt ingest-otel` | GenAI spans become decisions, with no code change |
| A team on Claude.ai, ChatGPT or Claude Code | A self-hosted server | One connector URL for everyone; see [section 7](#7-teams-one-shared-server) |

Then work as usual. `dt uninstall claude-code` (or `claude-desktop`, `cursor`) stops
recording; decisions already recorded are kept.

### In your own code

Your code enforces its rules; tell DecisionTrace what happened from inside the tool:

```python
import anthropic, decisiontrace as dt

client = dt.wrap(anthropic.Anthropic())


def issue_refund(order_id, amount):
    if amount > 500:
        dt.policy("refund.max_auto_amount", "fail", detail=f"${amount} > $500", enforced=True)
        dt.exception("refund.max_auto_amount", "carrier damage", granted_by="Support lead")
        dt.approval("approved", by="Support lead")
    ...
```

Without an SDK:

```python
with dt.decision("refund.approve", intent="Refund $850 for order 7731", agent="refunds") as d:
    d.context("order", "shop:7731", summary="arrived crushed")
    d.policy("refund.max_auto_amount", "fail", enforced=True)
    d.action("stripe.refunds.create", summary="Full refund $850", type="api_call")
```

Recording never raises into your code; problems go to `~/.decisiontrace/recorder-errors.log`.
More in [Anthropic and OpenAI SDKs](adapters/sdk.md) and [OpenTelemetry](adapters/otel.md).

## 3. Look back

```bash
dt log                               # recent decisions, newest first
dt show <id>                         # one decision in full
dt why <id>                          # a plain-English account (any unique start of the id)
dt why src/billing/due_dates.py      # the last decision that changed this file
dt why c1a90b2                       # the decision behind this git commit
dt similar <id>                      # past decisions like it, with the similarity breakdown
dt ask "what did we revert last week?"   # offline; --llm uses Claude
```

See [Recall](recall.md) for how similarity and `dt ask` work.

## 4. Record what happened

A decision teaches something only once its outcome is known. Outcomes are appended as new
records; the decision itself is never edited.

By hand:

```bash
dt outcome <id> --accepted
dt outcome <id> --reverted --note "broke month-end invoices"
dt outcome <id> --complained --value-usd -250
```

Other outcomes: `--overridden`, `--escalated`, `--failed`.

Automatically, from signals that already exist (safe to run every day, for example from cron):

```bash
dt outcomes detect                                   # overrides and reversals in the store
dt outcomes detect --git ~/src/app                   # git reverts and merges
dt outcomes detect --events tickets.jsonl --preset zendesk
dt outcomes detect --assume-accepted-after 14        # opt-in: no complaint in 14 days = accepted
dt outcomes detect --dry-run                         # preview; writes nothing
```

Presets: `stripe`, `zendesk`, `jira`, `github`, `pagerduty`, or `generic` JSON Lines. An
outcome a person recorded is never overridden. Details in [Outcome detection](outcomes.md).

## 5. Count verified work

A verified work unit (VWU) is one piece of accepted work that met its quality bar and can
still be undone at a known cost.

```bash
dt outcome <id> --accepted --vwu code.change --verified-by automated \
  --reversal-days 3 --reversal-cost 150 \
  --quality-metric ci.required_checks/v1 --quality-threshold 1 --quality-value 1

dt outcomes detect --git . --vwu      # merged, unreverted commits become code.change units
dt vwu                                # every unit, its state, and who did the work
```

A unit is **provisional** inside its reversal window, **final** after it, and **reverted**
if it was undone in time. The footer of `dt vwu` shows the share of units checked without a
person. See [Verified work units](vwu.md).

## 6. Keep it trustworthy

```bash
dt verify                          # recompute the hash chain; reports any tampering
dt export -o export.jsonl          # every record, for backup or for Valence
dt validate records.jsonl          # check records against the schema without storing them
```

- Secrets (API keys, tokens, passwords) are removed before anything is written.
- Emails, phone numbers, cards, PAN and Aadhaar become stable pseudonyms.
- Model reasoning and assistant replies are never stored; prompt and response bodies only
  if you set `bodies = true` in `~/.decisiontrace/config.toml`.
- `dt verify` prints the head hash: save it somewhere you trust to anchor the chain.

See [Privacy & security](privacy.md).

## 7. Teams: one shared server

Run one DecisionTrace server; Claude.ai, ChatGPT, Claude Code and your agents connect to it.

```bash
export DT_MCP_TOKEN=$(dt mcp --new-token)        # keep it in your secret store
DT_HOME=/srv/decisiontrace dt mcp --http --host 0.0.0.0 --port 8765 --allowed-host dt.yourco.com
```

Or use the Docker setup in `deploy/self-hosted-mcp/`: copy `.env.example` to `.env`, set
your host and token, then `docker compose up -d --build` (Caddy obtains the HTTPS
certificate).

| Tool | Setup |
|---|---|
| Claude.ai (an owner adds it for the organisation) | Custom connector: `https://dt.yourco.com/t/<token>/mcp` |
| ChatGPT business workspace | An admin adds a custom MCP connector at the same URL |
| Claude Code | `claude mcp add --transport http decisiontrace https://dt.yourco.com/mcp --header "Authorization: Bearer $DT_MCP_TOKEN"` |

The server must be reachable over HTTPS from the internet: connectors call it from the AI
provider's cloud. Full guide: [Self-hosted MCP](adapters/self-hosted-mcp.md).

## 8. Try it without any setup

```bash
git clone https://github.com/Liquicent/liquicent-decisiontrace && cd liquicent-decisiontrace
uv sync
uv run python examples/refund_agent.py   # offline demo; --live uses real Claude
uv run dt log
uv run dt why <id from the log>
```

## Quick reference

| Task | Command |
|---|---|
| Start recording | `dt install claude-code` |
| What happened today | `dt log` |
| Why did it do that? | `dt why <id / file / commit>` |
| Has this come up before? | `dt similar <id>` |
| How did it turn out? | `dt outcome <id> --accepted` or `dt outcomes detect --git .` |
| Verified work | `dt vwu` |
| Is the record intact? | `dt verify` |
| Stop recording | `dt uninstall claude-code` |
| Help on any command | `dt <command> --help` |

Every command is listed in the [CLI reference](cli.md).
