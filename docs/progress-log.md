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
