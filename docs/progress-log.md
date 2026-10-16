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
