# Progress log

Claude Code appends a dated entry here at the end of every session.

## 2026-10-16 — Setup (before Phase 0)

**Done**
- Reviewed the Liquicent repos (`liquicent1`, `liquicent2`): marketing site + lead capture only;
  no runtime/trace code to reuse. DecisionTrace starts from scratch.
- Created repo `vpsingh88/liquicent-decisiontrace` (public, Apache-2.0).
- Added `CLAUDE.md` and `docs/BUILD_PLAN.md`.

**Findings**
- PyPI `decision-trace` already exists (logicoflife, v0.1.1, Apr 2026) with a similar
  evidence / policy_check / outcome API. `decisiontrace` is likely to be rejected by PyPI as
  too similar. Working assumption: publish as `liquicent-decisiontrace`, keep the `dt` CLI
  and `decisiontrace` import name.
- Hook latency budget (< 50 ms) means the Claude Code hook script must be stdlib-only and
  redact before enqueueing.
- Default embeddings: prefer SQLite FTS5 as the zero-download default; a small non-torch
  model as an optional extra.
- Phase 4 golden set can only draw on ~1.5–2 weeks of dogfood traces, not 3.

**Next**
- Phase 0 (starts 19 Oct per plan).

**Open decisions**
- Confirm PyPI package name.
- The paper: needed for the X/H/T field meanings and the `A` term in the similarity formula.

## 2026-10-16 — Papers reviewed (DecisionTrace, NewFirm, SocioTrustRank, WorkRank, Liquicent 2.1)

**Resolved for the v0.1 schema** (DecisionTrace paper is canonical)
- `X` = rejected actions/alternatives, `H` = approval path — confirmed by Appendix A.1/A.2.
- `T` is undefined in the papers; keep CLAUDE.md meaning (actor & time) and fill it with the
  Liquicent 2.1 transition-telemetry fields (actor_type/id, timestamps, delta, tokens,
  confidence, risk).
- Add an explicit `action` field for the chosen action `a_t` (eq. 1–2); it is not one of the
  seven fields and must not be folded into `O`.
- Similarity `A` term: assume `A` = chosen-action similarity (the paper's `a_t`). `T` in Sim =
  actor/tool similarity; recency stays in `−λΔt`. Weights configurable.
- Precedent thresholds default to strong ≥ 0.75, weak ≥ 0.6 (from A.4's θ grid).
- `dt outcome` records accepted / reverted / overridden / escalated so Valence can later
  compute the trust inputs (`A_t`, `R_t`, `O_t`) and cost terms (EC: escalation, rollback,
  override counts).

**Watch-outs**
- NewFirm's 6-tuple text lists "evaluative events, exceptions, approvals", which reads as
  E/X/H shifted by one. Follow the DecisionTrace paper; store policy evaluations under `P`.
- The candidate filter `Pi ∩ Pj ≠ ∅` returns nothing for traces with no policies (common in
  Claude Code). Need a fallback candidate set (same workflow/tool) in Phase 4.
- Append-only vs deletion (SocioTrustRank: "opt-in and deletable"; GDPR): hash the redacted
  record, keep optional bodies in a separate table so a body can be erased without breaking
  the chain.
- Context Graph needs an edges table from v0.1 (outcome/correction, reversal, precedent links).

**Next**
- Phase 0.

## 2026-10-16 — Second batch reviewed (Full Design 2.0, Deployable Agentic Systems, Embedded Transformer, 2.1/2.2 HLD + UTG spec)

**Schema additions for Phase 0**
- `action` (`U_t`) plus `state_before` / `state_after` *references* (e.g. git SHA, file hashes),
  so a trace also satisfies Full Design 2.0's definition (realized transition
  `(X_t, U_t, X_{t+1})` + constraint evaluations).
- Policy entries carry `policy_id` + `version`/`hash` (UTG: "versioned by policy hash") and
  `enforced: bool` (NKP-style hard constraint vs advisory rule).
- `namespace` field from v0.1 (tenant isolation of DecisionTrace graphs, Deployable §7).
  Defaults to the local user; cheap now, painful to add later.
- Typed links, using the UTG edge names: `decision`, `context`, `precedent`, `reversal`,
  `exec`, plus `delegation` for parent→child traces (A2A trace reference; Claude Code
  subagents). Traces form a DAG; the hash chain is separate and per-store.
- Memory writes (e.g. an agent editing CLAUDE.md or a memory file) are a decision kind, so the
  attribution invariant (every memory mutation → one trace) can hold.

**New invariants / tests**
- Record execution, not cognition: never store model reasoning / chain-of-thought, even with
  body storage on. Only inputs, evaluations, actions, approvals, outcomes.
- Completeness (Full Design Thm 2): every executed tool call belongs to exactly one trace.
  Phase 2 adds a test for this.
- Record enough to replay later (input hashes, model id, params), but replay itself stays out
  of v0.1.

**Out of scope here, but noted**
- WorkRank and TrustRank formulas differ across papers (WorkRank: `A·Q/(1+R)` vs
  `Capability·T·CostEff` vs EMA; TrustRank: EMA vs `τ + ηA − μR − νO`). Valence will need
  one canonical version; this repo only records the outcome signals both need.
- The HLD's first wedge (PR governance / code review) matches the Claude Code adapter; PR
  merge and code edit are among the Phase 0 example traces.
- Embedded Transformer / belief-state cognition: no impact on this repo.

## 2026-10-16 — Project export + ChatGPT archive reviewed

**Sources:** project notes, investor deck text (Oct 2026), solo-builder progress log,
recovered index of ChatGPT project chats (Jul 2025 – Oct 2026). PDFs were the same ones
already reviewed.

**Open-core boundary — needs Praveen's call**
- Aug 2026 OSS strategy chat: open-source DecisionTrace + execution kernel (NKP/FSA guards,
  approvals, replay, adapters); keep Context Graph / precedent / trust proprietary.
- Investor deck (slide 13): OSS = SDK + local capture + replay/viewer.
- BUILD_PLAN: OSS includes precedent recall (`dt similar`, paper's Sim function); excludes
  enforcement and replay; no viewer.
- Proposed line: open = single-user/local recall (`why/similar/ask`) because it drives
  retention; proprietary = cross-team Context Graph, precedent-based auto-approval, trust,
  autonomy, compounding score. Keep enforcement out (CLAUDE.md #3). Deck should be updated
  to match ("replay/viewer" and "execution boundary" wording predate the Oct no-gateway call).

**Requirements this adds to the store**
- Compounding score (performance ÷ cost per capability): every trace needs a reliable
  per-decision cost in `T` and a capability label (inferred, not declared).
- "Approvals per 100 decisions": `H` must make approvals countable (typed events, not text).
- Harness-update loop: changes to prompts, skills, CLAUDE.md, routing are themselves
  traces (same as the memory-write decision kind).
- Hand-offs / chain map: delegation links must cross tools and people, not just subagents.

**Missing files referenced in the notes**
- `liquicent-oss-plan.md` (90-day plan) and `liquicent-valence-addendum.md` — not in either
  archive.

## 2026-10-16 — Decisions made; Phase 0 done (pending CI on GitHub)

**Decisions** (Praveen delegated; recorded in `docs/DECISIONS.md`)
- D1 open-core boundary: open = capture, store, adapters, single-user local recall;
  Liquicent = anything needing many people's traces or acting on them (shared Context
  Graph, auto-approval, trust/WorkRank, Valence, compounding score). No enforcement here.
- D2 schema is an open standard, versioned on its own, OTel GenAI names pinned to 0.66b1.
- D3 PyPI `liquicent-decisiontrace`, import `decisiontrace`, CLI `dt`.
- D4 Apache-2.0 + DCO. D5 record execution, not cognition (now CLAUDE.md #7). D6 start now.

**Phase 0 built**
- `schema/decisiontrace.schema.json` v0.1.0: decision / outcome / correction records;
  C, P, E, X, H, T, O plus `actions`, `state_before/after`, typed `links` (UTG edge names +
  delegation, hand_off), `namespace`, `capabilities`, `attributes`, `integrity`.
- 10 example decisions + 1 outcome + 1 correction in `schema/examples/`.
- Pydantic models (frozen, extra=forbid), ULID ids, schema loader, `dt version/schema/validate`.
- 123 tests: example validation and exact round-trip, schema↔model drift guard (fields,
  required, enums), 25 invalid mutations rejected by both, ULIDs, CLI.
- CI (3.11–3.13: ruff, format, mypy --strict, pytest, wheel install check), DCO check,
  CONTRIBUTING, SECURITY, schema reference, README.

**Assumption made:** `actions` is a list (one user intent → several tool calls in Claude
Code), not the single `a_t` of the paper.

**Next:** Phase 1 — SQLite append-only store, hash chain, redaction, dt init/log/show/
verify/export, 100k benchmark, tamper test.

**For Praveen (GitHub settings, 2 minutes):** enable *Private vulnerability reporting*
(Settings → Code security) so SECURITY.md works; add repo topics.

## 2026-10-16 — Phase 1 done: local store

Praveen: open source = company Phase 1 (all of BUILD_PLAN 0–6, this repo); Valence = Phase 2
and Liquicent = Phase 3, both in private repos. Working through BUILD_PLAN phases in order.

**Built**
- `store/`: SQLite (WAL) with append-only triggers on records and links, per-store hash
  chain (`sha256(prev ‖ canonical JSON)`, genesis = 64 zeros), head count/hash in meta,
  migrations via `user_version`. Outcomes/corrections are linked appends; unknown
  `trace_id` rejected; batches are all-or-nothing.
- Opt-in bodies in a separate, erasable table outside the chain (`forget_bodies`), so GDPR
  erasure never breaks `verify`.
- `redact.py`: secrets (Anthropic, OpenAI, Stripe, GitHub, Slack, AWS, Google, JWT, private
  keys, bearer tokens, URL credentials, `password=`-style assignments) removed; e-mail,
  phone, PAN, Aadhaar (Verhoeff), cards (Luhn) pseudonymised with a per-store salt.
- `config.py`: `~/.decisiontrace` (or `DT_HOME` / `--home`), `config.toml` with salt.
- CLI: `dt init / append / log / show / outcome / verify / export` (+ `validate`).
  `show` applies corrections and later outcomes without touching stored records.

**Exit test**
- 100k synthetic traces: 33.8 s to write, 3 s to verify (limit 60 s). CI job added.
- Tamper tests: edited field, edited + re-hashed row, deleted middle row, truncated tail,
  altered index column — all fail `verify`.
- Redaction suite (true positives and negatives) passes; planted secrets never appear in
  any file under the store directory, including WAL.

**Known limit:** the chain is tamper-*evident*, not tamper-proof: someone who rewrites the
whole file and the meta row can forge it. `dt verify` prints the head hash so it can be
anchored elsewhere (e.g. committed to git). Noted for the docs.

**Next:** Phase 2 — Claude Code adapter.

## 2026-10-16 — Phase 2 done: Claude Code adapter (pending Praveen's full-day dogfood)

**Built**
- `adapters/claude_code/hook.py`: stdlib-only, run as `python -I -S`; redacts, appends one
  line per event to `queue/<session>.jsonl`; always exit 0, silent; spawns a background
  drain on Stop/StopFailure/SessionEnd. Median 35 ms (test asserts < 50 ms). Package
  `__init__` made lazy and `typing`/`dataclasses` kept off the hook's import path for this.
- `builder.py`: one decision per `prompt_id`; subagents (by `agent_id`) become linked child
  decisions (`delegation`). Permission outcomes → `policies`; denied / auto-denied /
  interrupted / blocked calls → `alternatives`; prompts+answers → `human_path`; model,
  tokens (cache-creation counted as input, streamed lines de-duplicated by message id) and
  Claude Code version from the transcript; git HEAD before/after read without spawning git.
  Kind and capabilities inferred from tools (`harness.update` for CLAUDE.md/.claude edits).
- `drain.py`: flock, stable ULIDs (re-drain never duplicates), unfinished turns re-queued,
  stale turns (>1 h) flushed, build failures parked in `queue/failed/`.
- `dt install|uninstall claude-code --scope user|project|local` (preserves other hooks,
  backup, idempotent), `dt drain`; `log`/`show` drain first.

**Verified against real Claude Code 2.1.301** (`claude -p` in a scratch repo): prompt,
file read, edit, bash, permission mode, model, 10,950/509 tokens, version, git HEAD all
recorded; chain verifies.

**Exit test status:** latency ✓ (35 ms), one-command removal ✓, completeness test ✓
(every executed tool call in exactly one trace). *Full day of real use by Praveen: pending.*

**Hooks doc notes:** no event for an interactive user deny; inferred from
PermissionRequest with no PostToolUse. `CLAUDE_CODE_VERSION` env not documented; version
read from transcript instead.

## 2026-10-16 — Phase 3 done: MCP server

**Built**
- `mcp_server.py` on the official MCP Python SDK **2.3.0** (`MCPServer`; v2 renamed
  FastMCP): tools `record`, `recall`, `outcome`, with server instructions (recall before
  rule/limit decisions; record facts only, never secrets or reasoning).
- Recall layer (shared with Phase 4): SQLite FTS5 index (migration 2, rebuilt from records if
  missing), BM25 + small recency weight for free-text queries; `precedent_view` returns
  rules, exceptions (who, role, why), approval path, rejected options, outcome. Passing a
  decision id ranks by the paper's similarity function (`recall/similarity.py`, done early).
- `dt mcp` (stdio), `dt mcp --config claude-desktop|cursor|claude-code`,
  `dt install|uninstall claude-desktop|cursor` (merge, backup), `python -m decisiontrace`.

**Exit test** ✓ — three decisions recorded through MCP, "how did we handle the last refund
over the limit?" returns the over-limit refund first, with its exception and approval path;
verified both in-process and over real stdio (`python -m decisiontrace mcp`).
Live check in the Claude Desktop app itself: pending (needs Praveen's machine).

**Other:** benchmark still 35.8 s with the FTS index. Ruff E501 dropped in favour of the
formatter (ruff's recommended setup).

## 2026-10-16 — Phase 4 done: recall engine (real-trace golden set pending)

**Built**
- `recall/similarity.py`: the paper's `Sim = αP + βX + γC + δA + εT − λΔt`, every component in
  [0,1]; P weights shared rules by result agreement and exceptions on the same rule; weights
  and strong/weak thresholds (0.75 / 0.60) configurable under `[recall]`. Terms that neither
  decision has (no policies / no alternatives) drop out of the denominator, so identical
  coding decisions still score 1.0. Candidate filter `Pi ∩ Pj ≠ ∅`, falling back to the
  same kind family, then full-text — fixes the empty-candidate problem for coding traces.
- Optional embeddings (`[embeddings]` extra: model2vec + sqlite-vec, no PyTorch): vectors
  are derived data outside the chain; `store.nearest` uses `vec_distance_cosine` when
  sqlite-vec loads, pure Python otherwise (tested to agree). Blended into C and into
  free-text search. Off by default; FTS5 needs no download. *Not tested with a real model
  here — huggingface.co is blocked from this environment; covered by a hashing embedder.*
- Indexes: `refs` (files written/read, commits before/after → decision), index version in
  meta so rebuilds happen only when the index format changes.
- `dt why <id|file|commit>`: deterministic plain-English account (context, rules incl.
  not-applicable, exceptions and who, rejected options, people, actions, resulting commit,
  outcome history, corrections, similar precedents). Never invents a reason.
- `dt similar <id|text>` with P/X/C/A/T/Δt breakdown; `dt ask` (time windows, outcome,
  exception/denial/approval/failed-rule filters, cost ordering, counts) offline;
  `--llm` sends only redacted precedent views to `claude-opus-5-5` with server-side
  refusal fallback (`fallbacks: "default"`); `[llm]` extra.
- `dt eval <golden.jsonl>` and `dt eval --sample 20 -o golden.jsonl` (drafts cases from real
  traces for hand-checking); `dt reindex`.

**Exit test**: golden set over the 10 example decisions: 10/10 (it caught a real bug —
not-applicable rules were missing from explanations). *Praveen's 20-item golden set from
his own traces: pending (needs ~1–2 weeks of dogfood; run `dt eval --sample 20`).*

## 2026-10-16 — Phase 5 done: SDK and OTel adapters

**Built**
- `recorder.py`: public API for any framework — `with dt.decision(...) as d:` plus
  `dt.policy / exception / approval / reject / context` that attach to the decision being
  recorded (contextvar). Never raises; errors to `recorder-errors.log`.
- `adapters/loop.py`: provider-neutral tool-loop tracker (one loop = one decision; answered
  calls → actions, unanswered → rejected alternatives; tokens summed; outcome `pending`).
- `dt.wrap(client)`: Anthropic (`create`, `parse`, `stream`, sync + async, incl. `beta` —
  covers the SDK tool runner, which uses `beta.messages.parse/stream`) and OpenAI (Chat
  Completions + Responses, duck-typed). Awaitables detected at call time (the SDK's
  decorators hide coroutine functions).
- `dt ingest-otel`: OTLP/HTTP receiver (JSON; protobuf with `[otel]`), `--file` mode,
  per-trace buffering, idempotent ids; GenAI spans → decisions, `decisiontrace.*` span events
  → P/E/H/X; message content never read.
- Examples: `refund_agent.py` (showcase — P, E, X, H, O; offline scripted model via the real
  SDK client + mock transport, `--live` for real Claude) and `otel_agent.py` (real OTel SDK
  + OTLP protobuf exporter, embedded ingester).

**Exit test** ✓ — both examples run from a clean clone in one command and `dt why` explains
the result (rule failed, Meera's exception and approval, actions). Tested on the real
Anthropic SDK (1.15) incl. tool runner, async and SSE streaming; real OTLP protobuf
exporter end to end. `--live` against the real API not run here (no key in this env).

## 2026-10-16 — Phase 6 prepared: launch (release and posts await Praveen)

**Built**
- README rewritten to reach `dt why` in five minutes (real output, not a mock-up), adapter
  table, record, principles, what it isn't.
- Docs site (mkdocs-material, `mkdocs build --strict` in CI): getting started, concepts,
  adapters, recall (similarity formula and tuning), CLI reference, schema reference,
  privacy & security (incl. the tamper-evident-not-tamper-proof limit), out of scope.
  Test keeps the CLI reference in sync with the commands.
- Version 0.1.0, CHANGELOG, release workflow (tag-triggered, version check, tests, build,
  PyPI Trusted Publishing — not triggered). `twine check` passes on wheel and sdist; clean
  wheel install works. `liquicent-decisiontrace` still free on PyPI.
- `docs/demo.tape` to record the 60-second GIF with vhs (vhs not available here).
- Show HN, LinkedIn and ANS-100 follow-up drafts written **outside the public repo**
  (handed to Praveen), not posted.

**Exit test:** the stranger test needs a real person (a 99tests tester) — pending. A
scripted fresh-clone run of the README steps passes (see below).

**Waiting on Praveen:** PyPI Trusted Publishing setup, signed `v0.1.0` tag, GIF recording,
stranger test, trademark check, GitHub private vulnerability reporting, docs hosting.
