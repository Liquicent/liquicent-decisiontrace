# Outcome detection

A decision without an outcome teaches nothing, and people rarely run `dt outcome`. `dt
outcomes detect` fills outcomes in from signals that already exist. It is safe to run as
often as you like (for example daily from cron):

```bash
dt outcomes detect                                   # signals inside the store
dt outcomes detect --git ~/src/app                   # + git reverts and merges
dt outcomes detect --events zendesk.jsonl --preset zendesk
dt outcomes detect --events stripe-events.jsonl --preset stripe --dry-run
dt outcomes detect --assume-accepted-after 14        # opt-in: silence counts as accepted
dt outcomes detect --git . --events zendesk.jsonl --preset zendesk --vwu   # + verified work units
```

## Sources

| Source | Signal | Outcome |
|---|---|---|
| Store | a human `overrode` step on the decision | overridden |
| Store | the decision's last action failed | failed |
| Store | a later decision links to it with `reversal` / `supersedes` | reverted / overridden |
| Store | a person decides the same business item (same ticket, order…) within 24 h | overridden |
| `--git` | the decision's commit (made by it, or the first commit within 3 days touching its files) is reverted | reverted |
| `--git` | that commit is on the main branch and survives `--settle-days` (3) | accepted |
| `--events --preset stripe` | dispute → complained; refund/payment failed → failed; cancelled/voided → reverted; refunded/succeeded → accepted | as listed |
| `--events --preset zendesk` | reopened ticket, bad satisfaction rating → complained; solved → accepted | as listed |
| `--events --preset jira` | status → Reopened → complained; Done/Resolved/Closed → accepted; Won't Do → reverted | as listed |
| `--events --preset github` | PR merged → accepted; closed unmerged → reverted; issue reopened → complained | as listed |
| `--events --preset pagerduty` | incident triggered with `ref` or `trace_id` in its details → failed | failed |
| `--events` (generic) | `{"ref", "event", "at", "value_usd"?}` or `{"trace_id", …}`; event words such as reopened, chargeback, rolled_back, failed, solved, merged | mapped |
| `--assume-accepted-after N` | a decision that acted and has no negative signal N days later | accepted (noted as an assumption) |

Events match a decision when their ref equals one of its refs (context inputs, action
targets, state), or when the id part after the last `:` `#` `/` (4+ characters) is equal —
so `stripe:ch_9001` matches an order recorded as `shop:ch_9001`, and `88412` matches
`zendesk:88412`. Only decisions made before the event are matched.

## Rules

- An outcome recorded by a person, or with the decision itself, is never overridden.
- Per decision, the most serious signal wins (reverted > failed > complained > overridden >
  escalated > accepted). Bad news later replaces an earlier detected *accepted*; nothing
  detected ever turns a bad outcome back into a good one.
- Detected outcomes are ordinary appended outcome records, `recorded_by` a system actor
  `decisiontrace:detect:<source>`, with the evidence in `attributes`. Their `recorded_at`
  is when the signal happened, so replays see them only from that moment.
- Running twice records nothing new.

## Verified work units (`--vwu`)

With `--vwu`, an *accepted* outcome from a delivery signal also records a
[verified work unit](vwu.md), verified by `outcome_signal`:

| Source | Unit | Reversible until |
|---|---|---|
| `--git` | `code.change` | merge time + `--settle-days` (already passed, so the unit is final at once) |
| `--events --preset stripe` | `stripe.payment` (`stripe.refund` for a refund) | event time + `--vwu-window-days` (7) |
| `--events --preset zendesk` / `jira` / `github` | `zendesk.ticket` / `jira.issue` / `github.pull_request` | event time + `--vwu-window-days` |
| `--events` (generic) | the event's `unit` if it is a dotted label, else `work.item` | event time + `--vwu-window-days` |

Signals inside the store and `--assume-accepted-after` never make units: an assumption is
not a verification. A later reverted, failed or overridden signal inside the window turns the
unit to `reverted` (see `dt vwu`). Turn `--vwu` on from the first run: an outcome already
detected without a unit is not recorded again.
