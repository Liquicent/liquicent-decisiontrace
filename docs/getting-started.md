# Getting started

## 1. Install

```bash
pip install liquicent-decisiontrace      # Python 3.11+
dt init                                  # creates ~/.decisiontrace (optional: install does it)
```

## 2. Record

Pick the tool you already use:

```bash
dt install claude-code      # Claude Code hooks (all projects)
dt install claude-desktop   # MCP server for Claude Desktop
dt install cursor           # MCP server for Cursor
```

In Python: `client = dt.wrap(anthropic.Anthropic())` — see [SDK adapter](adapters/sdk.md).

## 3. Recall

```bash
dt log                                  # recent decisions
dt why 01M53TRF3G                       # by id (any unique prefix)
dt why src/billing/due_dates.py         # the last decision that changed this file
dt why c1a90b2                          # the decision that produced this commit
dt similar 01M53TRF3G                   # precedents, with similarity breakdown
dt ask "which refunds needed an exception last week?"
```

## 4. Close the loop

```bash
dt outcome 01M53TRF3G --reverted --note "broke month-end invoices"
dt verify
```

Outcomes are appended, never edited in — the original decision stays exactly as recorded.

## Try it without any setup

```bash
git clone https://github.com/vpsingh88/liquicent-decisiontrace && cd liquicent-decisiontrace
uv sync
uv run python examples/refund_agent.py
uv run dt log
```
