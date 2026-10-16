# DecisionTrace OSS — Build Plan (Claude Code)

**Window:** 19 Oct – 29 Nov 2026 (6 weeks, full-time)
**Team:** Praveen + Claude Code
**Goal by 29 Nov:** a public GitHub repo where anyone using Claude Code (or an agent on the
Anthropic/OpenAI SDKs) can `pip install decisiontrace`, run `dt init`, and within five
minutes ask `dt why` about a decision their AI made yesterday.

Put this file at `docs/BUILD_PLAN.md` and `CLAUDE.md` at the repo root.

---

## Why this order

The wedge is employees' everyday use of Claude and ChatGPT. So the first adapter is the
one Praveen uses daily — **Claude Code hooks** — which means we dogfood from Week 1 and
every week of building produces real traces. MCP comes second because it lets *any*
MCP-capable client (Claude Desktop, Cursor, others) both write and recall traces. SDK and
OTel adapters come third so agent builders can adopt it. Recall (`why / similar / ask`)
is what makes people keep it installed; outcome capture is what Valence will later sell.

Interception/gateway is deliberately excluded — that market is taken.

---

## Phase 0 — Repo and schema (Days 1–3)

**Build**
- Repo scaffold per `CLAUDE.md` layout, `uv`, ruff, mypy, pytest, GitHub Actions CI
- `schema/decisiontrace.schema.json` v0.1 for `⟨C, P, E, X, H, T, O⟩`, plus 10 hand-written
  example traces (refund approval, PR merge, code edit, email draft, denied tool call…)
- Pydantic models, schema round-trip tests, ID scheme (ULID), `schema_version` field
- Apache-2.0 licence, DCO bot, CONTRIBUTING.md, SECURITY.md

**Exit test:** CI green; every example trace validates; models ↔ schema round-trip.

**Kickoff prompt**
> Read CLAUDE.md. Do Phase 0 of docs/BUILD_PLAN.md: scaffold the repo, write the v0.1
> JSON Schema for DT = ⟨C,P,E,X,H,T,O⟩ with OTel GenAI field mapping, 10 example traces,
> Pydantic models and round-trip tests, CI, licence and DCO. Tell me before anything that
> runs over 10 minutes.

---

## Phase 1 — Local store (Days 4–7)

**Build**
- SQLite store (WAL), migrations, append-only enforcement (triggers block UPDATE/DELETE)
- Per-store hash chain + `dt verify` to detect tampering
- Outcome and correction records as linked appends, not edits
- `redact.py`: secrets (keys, tokens), emails, phone numbers, Indian PAN/Aadhaar patterns;
  body storage off by default, hash + summary instead
- `dt init`, `dt log`, `dt show <id>`, `dt verify`, `dt export --jsonl`

**Exit test:** 100k synthetic traces write in under a minute; tampering one row makes
`dt verify` fail; redaction test suite passes; nothing secret ever reaches disk.

**Kickoff prompt**
> Phase 1 of the build plan: SQLite append-only store with hash chain, redaction, and the
> dt init/log/show/verify/export commands. Include the 100k-trace benchmark and a tamper
> test.

---

## Phase 2 — Claude Code adapter (Days 8–12) ← first dogfood

**Build**
- `dt install claude-code` writes hook config into `.claude/settings.json` (project or user)
- Hooks: `UserPromptSubmit` (C), `PreToolUse` (proposed action, policy check → P/E/X),
  `PostToolUse` (result), permission denials and user edits (X/H), `Stop` (closes the trace)
- Group events into one trace per *decision* (one user intent → actions), not per tool call
- Cost and model in `T`; git commit SHA linked when an edit is committed
- Fast path: hook script must add < 50 ms; writes go to a local queue, store drains it

**Exit test:** Praveen works a full day in Claude Code with it on; `dt log` shows that day's
decisions grouped sensibly; no noticeable slowdown; removing it is one command.

**Kickoff prompt**
> Phase 2: Claude Code adapter. Check the current Claude Code hooks documentation first,
> then build `dt install claude-code`, the hook handlers, decision grouping and the async
> queue. Keep hook latency under 50 ms and prove it with a test.

---

## Phase 3 — MCP server (Days 13–17)

**Build**
- `dt mcp` runs a local MCP server exposing:
  - `decisiontrace.record` — client-side recording for tools without hooks
  - `decisiontrace.recall` — "have we decided something like this before?" → top precedents
  - `decisiontrace.outcome` — attach an outcome to a past trace
- Install snippets for Claude Desktop, Claude Code and Cursor
- Recall returns precedent with its policy/exception/approval path, not just text

**Exit test:** In Claude Desktop, asking "how did we handle the last refund over the
limit?" returns the right past trace through `decisiontrace.recall`.

**Kickoff prompt**
> Phase 3: local MCP server with record, recall and outcome tools using the official MCP
> Python SDK, plus install snippets for Claude Desktop, Claude Code and Cursor. Add an
> end-to-end test that records three traces and recalls the right one.

---

## Phase 4 — Recall engine and the `dt` verbs (Days 18–24)

**Build**
- Embeddings into `sqlite-vec`; local default model, pluggable providers
- Similarity per the paper: candidate filter on shared policies, then
  `Sim = αP + βX + γC + δA + εT − λΔt`, weights in config, strong/weak precedent thresholds
- `dt why <id|file|commit>` — plain-English account of a decision: context, rules,
  exceptions, who approved, what was rejected
- `dt similar <id|text>` — ranked precedents with similarity breakdown
- `dt ask "<question>"` — natural-language query over the store (LLM optional; works with
  structured filters alone when no key is set)
- `dt outcome <id> --accepted|--reverted|--note` — the hook Valence's compounding score
  will later read

**Exit test:** On Praveen's own 3 weeks of traces, `dt why` on a random commit gives a
correct, readable explanation 8 times out of 10 (hand-checked golden set of 20).

**Kickoff prompt**
> Phase 4: recall engine. Implement the paper's similarity function with configurable
> weights over sqlite-vec, then dt why / similar / ask / outcome. Build a 20-item golden
> set from my real traces and report the score.

---

## Phase 5 — SDK and OTel adapters (Days 25–30)

**Build**
- `decisiontrace.wrap(anthropic_client)` and `wrap(openai_client)` — tool-use loops become
  traces with no other code change
- OTel GenAI span ingester: point an existing OTel exporter at `dt ingest-otel`
- One example agent per adapter in `examples/` (refund agent with a policy limit is the
  showcase: it exercises P, E, X, H and O)

**Exit test:** each example runs from a clean clone in one command and produces traces
that `dt why` explains correctly.

**Kickoff prompt**
> Phase 5: Anthropic and OpenAI SDK wrappers and an OTel GenAI span ingester, each with a
> runnable example. The refund agent with a policy limit is the showcase example.

---

## Phase 6 — Launch (Days 31–36)

**Build**
- README that gets to `dt why` in five minutes, with a 60-second GIF
- Docs site (mkdocs), adapter guides, schema reference, "what's out of scope" page
- PyPI release 0.1.0, signed tags, CHANGELOG
- Launch pack: Show HN post, LinkedIn post, ANS-100 follow-up note to past assessment
  contacts offering a free two-week Valence observation on top of their traces

**Exit test:** a stranger (one of 99tests' testers is ideal) installs from PyPI and reaches
`dt why` without help; record where they got stuck and fix it before announcing.

**Kickoff prompt**
> Phase 6: launch. Write the README, mkdocs site and CHANGELOG, prepare the 0.1.0 PyPI
> release, and draft the Show HN and LinkedIn posts. Don't publish anything — leave the
> release and posts for me to approve.

---

## Running alongside the build

- **Validation, not after it.** Fold one question into every ANS-100 meeting from Week 1:
  *"When your AI made a wrong call last month, could you find out why?"* Target 12 answers
  by launch. If fewer than 4 say "no, and it hurt", re-scope before Phase 6.
- **Design partners.** Ask 2–3 of those 12 to run the Claude Code adapter for two weeks in
  November — that is the first Valence report.
- **Progress log.** Claude Code appends to `docs/progress-log.md` every session; upload it to
  the Liquicent project when planning outside the repo.

## Decisions to confirm before Phase 0

1. **Name and repo:** `decisiontrace` on PyPI and `liquicent/decisiontrace` on GitHub —
   check both are free.
2. **Field mapping:** the meanings of X (rejected alternatives), H (human approval path) and
   T (actor/time/cost) above are my reading of the paper; confirm or correct.
3. **Licence:** Apache-2.0 + DCO recommended (lower friction than a CLA for a solo
   maintainer; still lets you keep Valence closed).

## What's deliberately not in v0.1

Gateway/interception, Valence reports, compounding score, WorkRank/trust routing,
Authority Envelope enforcement (we *record* envelope checks, we don't enforce them),
multi-user sync, hosted service.
