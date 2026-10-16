# Recall

## `dt why`

A plain-English account built only from what was recorded — no model call, so it is
reproducible and never invents a reason. Accepts a decision id (or prefix), a file path
(the latest decision that wrote it), or a git commit (the decision whose turn produced it).

## `dt similar`

Ranks precedents with the similarity function from *DecisionTrace and Context Graphs*:

```text
Sim = αP + βX + γC + δA + εT − λΔt
```

| Term | Meaning | Default weight |
|---|---|---|
| P | shared rules, weighted by whether they had the same result; exceptions on the same rule | α = 0.30 |
| X | the same options rejected, by the same kind of actor | β = 0.10 |
| C | overlap of intent and context (plus embedding cosine if enabled) | γ = 0.30 |
| A | the same actions and capabilities, same kind | δ = 0.20 |
| T | same actor, actor type, model, principal | ε = 0.10 |
| Δt | age gap in years (capped at 1) | λ = 0.10 |

Candidates must share at least one rule; if none do (common for coding agents) the
same kind family is used, then full-text matches. Terms neither decision has are dropped
from the weighting. Scores ≥ 0.75 are *strong* precedent, ≥ 0.60 *weak*.

Tune in `~/.decisiontrace/config.toml`:

```toml
[recall]
alpha = 0.3
lambda = 0.1
strong = 0.75
weak = 0.6
embeddings = "none"     # or "model2vec" with the [embeddings] extra
```

## `dt ask`

Offline, questions are turned into filters — time window (*today, yesterday, last week,
last 30 days*), outcome (*reverted*), *exception*, *denied/rejected*, *approved*, *failed /
over the limit*, *cost* — plus full-text search. `--llm` lets Claude write the answer from
the matching records (already redacted); nothing else is sent.

## Measuring it: `dt eval`

`dt eval --sample 20 -o golden.jsonl` drafts cases from your real decisions; fill in what
each explanation must mention, then `dt eval golden.jsonl` scores `dt why` (target 80%).
