# Anthropic and OpenAI SDKs

```python
import anthropic, decisiontrace as dt

client = dt.wrap(anthropic.Anthropic())        # or openai.OpenAI(), AsyncAnthropic(), AsyncOpenAI()
```

That's the only change. Each tool-use loop — from the first user message until the model
stops asking for tools — becomes one DecisionTrace:

| Seen in the loop | Recorded as |
|---|---|
| first user message | `intent` + `context.inputs[user_prompt]` (hash + redacted summary) |
| tool calls whose results came back | `actions` (`failed` if the result was an error) |
| tool calls proposed but never answered | `alternatives`, rejected by `system` |
| model, token usage across the loop | `actor_time.model`, `.cost` |

Covered: `messages.create`, `messages.parse`, `messages.stream` and their `beta` versions
(so the SDK's tool runner is recorded too); OpenAI Chat Completions and Responses. Raw
`stream=True` iterators are passed through but not recorded.

## Recording rules, exceptions and approvals

Your code enforces the rules; tell DecisionTrace what happened from inside the tool:

```python
def issue_refund(order_id, amount):
    if amount > 500:
        dt.policy("refund.max_auto_amount", "fail", detail=f"${amount} > $500", enforced=True)
        if not approved_by_lead():
            dt.approval("rejected", by="Meera (support lead)")
            return {"status": "denied"}
        dt.exception("refund.max_auto_amount", "carrier damage", granted_by="Meera (support lead)")
        dt.approval("approved", by="Meera (support lead)")
    ...
```

These calls attach to the loop being recorded and do nothing outside one.

## Without an SDK

```python
with dt.decision("refund.approve", intent="Refund $850 for order 7731", agent="refunds") as d:
    d.context("order", "shop:7731", summary="arrived crushed")
    d.policy("refund.max_auto_amount", "fail", enforced=True)
    d.exception("refund.max_auto_amount", "VIP", granted_by="Meera (support lead)")
    d.action("stripe.refunds.create", summary="Full refund $850", type="api_call")
```

Recording never raises into your code; errors go to `~/.decisiontrace/recorder-errors.log`.

Example: `uv run python examples/refund_agent.py` (offline; `--live` for real Claude).
