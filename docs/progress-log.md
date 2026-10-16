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
