## What this does


## Checks

- [ ] Tests added or updated, and `uv run pytest -q` passes
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests` passes
- [ ] Every commit is signed off (`git commit -s`), as [CONTRIBUTING.md](../CONTRIBUTING.md) asks
- [ ] Nothing stores model reasoning, and nothing blocks, proxies or rewrites an agent's actions
