# Concepts

## A decision record

Every decision is `DT = ⟨C, P, E, X, H, T, O⟩`, plus what was actually done:

| | Field | Holds |
|---|---|---|
| C | `context` | inputs (typed references, hashes, short redacted summaries), state before |
| P | `policies` | each rule checked: id, version, engine, pass/fail, enforced or advisory |
| E | `exceptions` | rules waived, by whom, why |
| X | `alternatives` | options considered and not taken, and what rejected them |
| H | `human_path` | requested → approved / rejected / edited / escalated, with latency |
| T | `actor_time` | actor, on whose behalf, model, client, timestamps, tokens, cost |
| O | `outcome` | as known at record time; later outcomes are separate records |
| | `actions` | what was done (tool calls, API calls, file and memory writes) |
| | `state_after` | resulting state, e.g. the git commit |

`decision_kind` (e.g. `refund.approve`, `code.edit`) and `capabilities` are inferred from
what happened — never declared.

## Three record types

- **decision** — the record above
- **outcome** — what happened later (`accepted`, `reverted`, `complained`, …), linked by id
- **correction** — a fix to a recorded field, linked by id; views apply it, the stored
  decision never changes

## The store

SQLite in `~/.decisiontrace` (`DT_HOME` to move it). Records are append-only (triggers block
`UPDATE`/`DELETE`) and hash-chained: each stores `sha256(previous hash ‖ canonical JSON)`.
`dt verify` recomputes the chain and reports edited, removed or reordered records.

## Links

Decisions link to each other: `delegation` (an agent handing work to a subagent),
`hand_off`, `precedent`, `reversal`, `supersedes`. The local store keeps the edges; the
team-wide graph built from them is Liquicent's, not this project's.
