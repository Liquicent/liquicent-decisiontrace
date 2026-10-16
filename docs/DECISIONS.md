# Decisions

Standing decisions for DecisionTrace OSS. Each one is optimised for the same goal: the open
source gets early adopters fast, and Liquicent keeps the parts that compound into revenue.
Change a decision by adding a new dated entry below it, not by editing it.

## D1 — Open-core boundary (2026-10-16)

**Open (Apache-2.0, this repo):** the schema/spec, Pydantic models, local SQLite store with
hash chain, redaction, all capture adapters (Claude Code, MCP, Anthropic/OpenAI SDKs, OTel),
and *single-user, local* recall: `dt why`, `dt similar`, `dt ask`, `dt outcome`.

**Liquicent (closed):** anything that needs many people's traces or acts on them —
the shared Context Graph across a team or company, precedent-based auto-approval and earned
autonomy, TrustRank / WorkRank / SocioTrustRank, Valence reports and the compounding score,
cost/friction analytics, policy optimisation, hosted sync, SSO, retention and compliance packs.

**Not built anywhere in this repo:** enforcement, gateways, proxies. We record policy and
Authority Envelope checks; we never enforce them (CLAUDE.md #3).

**Why:** adoption needs recall that is useful to one developer on day one, otherwise nobody
keeps the hooks installed. Revenue needs the things that only get better with more traces,
more people and more time — those are network effects one laptop can't copy. "Open-source
the record of decisions; monetize what the organization learns."

## D2 — The schema is the standard (2026-10-16)

The JSON Schema is versioned separately from the package (`schema_version`) and documented
as an open spec so other tools can emit DecisionTraces without our code. Every DecisionTrace
anyone writes is a future Liquicent input. Field names follow OTel GenAI conventions (pinned to
`opentelemetry-semantic-conventions` 0.66b1) so existing telemetry maps in cheaply.

## D3 — Names (2026-10-16)

- PyPI distribution: `liquicent-decisiontrace` (`decision-trace` already exists on PyPI, and
  `decisiontrace` is likely to be refused as too similar).
- Import name `decisiontrace`, CLI `dt`, product name "DecisionTrace".
- Before launch, check a trademark search on "DecisionTrace"; if it is not registrable, lead
  with "Liquicent DecisionTrace".

## D4 — Licence and contributions (2026-10-16)

Apache-2.0 (patent grant, enterprise-friendly) with DCO sign-off, not a CLA. Keeps the
contribution bar low; Liquicent's closed parts live in separate repos so relicensing this
one is never needed.

## D5 — Record execution, not cognition (2026-10-16)

Never store model reasoning or chain-of-thought, even with body storage on. Store inputs,
policy evaluations, actions, rejected alternatives, approvals and outcomes. (Liquicent Full
Design 2.0; also the privacy line enterprises will ask about first.)

## D6 — Start now (2026-10-16)

Phase 0 starts 16 Oct instead of 19 Oct. Every extra week of dogfood traces improves the
Phase 4 golden set.
