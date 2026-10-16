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
