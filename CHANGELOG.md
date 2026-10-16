# Changelog

All notable changes to this project are documented here. The schema has its own version
(`schema_version`), independent of the package version.

## 0.1.0 — unreleased

First public release.

### Record
- Open JSON Schema v0.1.0 for `DT = ⟨C, P, E, X, H, T, O⟩` plus actions, state before/after,
  typed links, inferred capabilities; outcome and correction records; OTel GenAI field mapping.
- Local SQLite store: append-only (triggers), per-store SHA-256 hash chain, `dt verify`.
- Redaction before write: secrets removed; e-mail, phone, card, PAN and Aadhaar pseudonymised.
  Model reasoning never stored; bodies opt-in and erasable outside the chain.

### Adapters
- **Claude Code**: `dt install claude-code` — stdlib-only hook (~35 ms), one decision per
  prompt, subagents as linked decisions, permission outcomes, denials, approvals, model,
  tokens, git commit before/after.
- **MCP**: `dt mcp` with `record`, `recall`, `outcome`; `dt install claude-desktop|cursor`.
- **SDKs**: `dt.wrap()` for Anthropic (incl. tool runner, async, streaming) and OpenAI
  (Chat Completions, Responses); `dt.decision()` / `dt.policy()` / `dt.exception()` /
  `dt.approval()` for any code.
- **OpenTelemetry**: `dt ingest-otel` (OTLP/HTTP JSON and protobuf, or files).

### Recall
- `dt why <id|file|commit>`, `dt similar` (the paper's `Sim = αP + βX + γC + δA + εT − λΔt`),
  `dt ask` (offline filters; `--llm` with Claude), `dt outcome`, `dt eval` golden sets.
- Optional embeddings (`[embeddings]`: model2vec + sqlite-vec).
