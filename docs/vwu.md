# Verified work units

A **verified work unit** (VWU) is one completed, accepted and reversible unit of work that
met its quality and governance thresholds. The definition comes from the WorkRank paper.
It counts outcomes, not effort, time or process.

A unit is recorded on an accepted outcome record, so the decision itself is never edited:

```bash
dt outcome 01M4ZDRZG0 --accepted --vwu code.change \
  --verified-by automated --reversal-days 3 --reversal-cost 150 \
  --quality-metric ci.required_checks/v1 --quality-threshold 1 --quality-value 1
dt outcomes detect --git . --vwu      # merged, unreverted commits become code.change units
dt vwu                                # every unit, its state, and who did the work
```

## What a unit records

| Field | Holds |
|---|---|
| `unit` | What one unit is, a dotted label: `code.change`, `support.ticket`, `sales.close` |
| `quantity` | Units delivered (absent means 1) |
| `executor` | Who did the work (absent means the decision's actor) |
| `quality` | The predefined threshold: `metric` id, `threshold`, `value`, `baseline`, `direction` |
| `measured` | The measurement window: `started_at`, `ended_at` |
| `verification` | `method` (human, automated, outcome_signal, precedent, sample), `at`, `verifier`, `ref` |
| `reversal` | `window_ends_at` (until when it can be undone) and `max_cost_usd` (what undoing costs) |

A value that misses its threshold is not a unit and is rejected. The same goes for a window
that ends before the verification, and for a unit on any status but `accepted`.

## Who earns from a unit

Whoever executed it: a person, an agent, or a vendor's person or agent. The `Actor` record
carries `org`, the accountable organisation the executor works for, and `version`, an
agent's model, prompt and tool bundle. Trust earned by one agent version need not carry to
the next. DecisionTrace records who did the work; it never scores them. Trust, routing and
settlement need many people's records and live in [Liquicent](out-of-scope.md).

## State

A unit's state is derived when you read it, never stored:

- **provisional**: still inside its reversal window.
- **final**: the window has ended with no cancel. A cancel after the window does not reopen it.
- **reverted**: a later outcome for the same decision was `reverted`, `failed` or
  `overridden` inside the window. A complaint or an escalation does not undo delivery.

## The number to watch

`dt vwu` ends with the share of units verified without a person. When agents produce far more
units than people can review, that share decides how fast work can be accepted. Checks that
run by themselves (`automated`, `outcome_signal`, `precedent`, `sample`) are what keep
review from becoming the bottleneck.
