# DecisionTrace

**Record *why* your AI made a decision, at the moment it's made — then ask `dt why` later.**

Logs tell you *what* an agent did. DecisionTrace records *why it was allowed to*: the
request and inputs, the rules that passed or failed, exceptions and who granted them, the
options it rejected, who approved, and what happened next. Local, append-only,
tamper-evident.

```bash
pip install liquicent-decisiontrace
dt install claude-code
# …work as usual…
dt log
dt why <id | file | commit>
```

- New here? [Getting started](getting-started.md)
- What exactly is recorded? [Concepts](concepts.md)
- Using an SDK, MCP or OpenTelemetry? [Adapters](adapters/claude-code.md)
- Worried about what's stored? [Privacy & security](privacy.md)
