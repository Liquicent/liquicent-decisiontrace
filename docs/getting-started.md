# Getting started

The short version. For every step in detail, see the [user guide](user-guide.md).

## 1. Install

```bash
pipx install liquicent-decisiontrace     # Python 3.11+; or: uv tool install liquicent-decisiontrace
dt init                                  # creates ~/.decisiontrace (optional: install does it)
```

`pipx` (or `uv tool`) gives `dt` its own environment and puts it on your PATH. Use it
where plain `pip install` fails with "externally-managed-environment", as it does on
Debian, Ubuntu and Homebrew Python:

```bash
sudo apt install pipx      # macOS: brew install pipx
pipx ensurepath            # then open a new terminal
```

In a project's virtual environment, `pip install liquicent-decisiontrace` works as usual.
Upgrade later with `pipx upgrade liquicent-decisiontrace`.

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
git clone https://github.com/Liquicent/liquicent-decisiontrace && cd liquicent-decisiontrace
uv sync
uv run python examples/refund_agent.py
uv run dt log
```
