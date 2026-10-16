# Contributing to DecisionTrace

Thanks for helping. DecisionTrace records **why** an AI-assisted decision was made; read
`CLAUDE.md` for the non-negotiables (capture at execution time, append-only, no gateways,
local-first, privacy by default, record execution not cognition).

## Setup

```bash
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests
uv run dt --help
```

## Rules

- Tests come with every change. CI must be green.
- The JSON Schema in `schema/decisiontrace.schema.json` is canonical. If you change it,
  update `src/decisiontrace/model.py`; `tests/test_schema_model_sync.py` fails on drift.
  Schema changes that break existing records need a new `schema_version`.
- Never add code that stores model reasoning / chain-of-thought, or that blocks, proxies
  or rewrites an agent's actions.

## Developer Certificate of Origin (DCO)

We use the [DCO](https://developercertificate.org/), not a CLA. Sign off every commit:

```bash
git commit -s -m "Your message"
```

This adds `Signed-off-by: Your Name <you@example.com>`, certifying you wrote the change or
have the right to submit it under the Apache-2.0 licence. The DCO check fails on pull
requests with unsigned commits; fix with `git rebase --signoff main` and force-push.
