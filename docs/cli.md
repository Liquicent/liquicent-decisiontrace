# CLI reference

Run `dt <command> --help` for every option. Global option: `--home PATH` (or `DT_HOME`)
selects the store directory (default `~/.decisiontrace`).

## Recording

| Command | What it does |
|---|---|
| `dt init` | Create the local store (safe to run again). |
| `dt install` | Start recording: claude-code (hooks), or claude-desktop / cursor (MCP server). `--scope user\|project\|local` for Claude Code. |
| `dt uninstall` | Stop recording (recorded decisions are kept). |
| `dt mcp` | Run the local MCP server (stdio), or print client setup with `--config claude-desktop\|cursor\|claude-code`. |
| `dt ingest-otel` | Receive OpenTelemetry GenAI spans (OTLP/HTTP on port 4318), or `--file` OTLP JSON. |
| `dt append` | Validate, redact and append records from `.json` / `.jsonl` files (all or nothing). |
| `dt drain` | Move queued Claude Code hook events into the store now (normally automatic). |

## Recall

| Command | What it does |
|---|---|
| `dt log` | List recent decisions, newest first (`-n`, `--kind`, `--since`). |
| `dt show` | One decision with rules, exceptions, alternatives, approvals and outcome (`--json`). |
| `dt why` | Plain-English account of a decision, by id, file path or git commit. |
| `dt similar` | Rank past decisions by similarity, with the P, X, C, A, T, Δt breakdown. |
| `dt ask` | Ask a question about your decisions. Works offline; `--llm` uses Claude. |
| `dt outcomes` (`dt outcomes detect`) | Fill in outcomes from the store, git (`--git`) and business events (`--events --preset stripe\|zendesk\|jira\|github\|pagerduty`); see [outcome detection](outcomes.md). |
| `dt outcome` | Record what happened after a decision (`--accepted`, `--reverted`, `--overridden`, `--escalated`, `--failed`, `--complained`, `--note`, `--value-usd`). |

## Integrity and data

| Command | What it does |
|---|---|
| `dt verify` | Recompute the hash chain and report any tampering. |
| `dt export` | Export every record, oldest first, with its hash-chain fields (`--jsonl`, `-o`). |
| `dt validate` | Check records against the schema and the Python models (without storing them). |
| `dt reindex` | Rebuild search indexes and compute missing embeddings (if enabled). |
| `dt eval` | Score `dt why` against a hand-checked golden set, or draft one with `--sample N`. |
| `dt schema` | Print the path of the DecisionTrace JSON Schema. |
| `dt version` | Show the package and schema versions. |
