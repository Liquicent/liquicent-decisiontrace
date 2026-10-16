"""Showcase: a refund agent whose rule checks, exception, approval and outcome are recorded.

    uv run python examples/refund_agent.py            # offline: scripted model, no API key
    uv run python examples/refund_agent.py --live     # real Claude (needs Anthropic credentials)

Then:  dt log  ·  dt why <id>  ·  dt ask "which refunds needed an exception?"

The only DecisionTrace-specific lines are `dt.wrap(client)` and the `dt.policy / exception /
approval` calls inside the tool that enforces the refund limit. The limit is enforced by
*your* code; DecisionTrace only records what happened.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import anthropic
except ImportError:
    sys.exit("This example needs the Anthropic SDK: pip install 'liquicent-decisiontrace[llm]'")

import decisiontrace as dt

sys.path.insert(0, str(Path(__file__).parent))
from _offline import scripted_anthropic_client

AUTO_LIMIT = 500
ORDERS = {
    "7731": {
        "amount": 850,
        "customer": "VIP, 6 years, no prior refunds",
        "issue": "parcel crushed",
    },
    "8120": {"amount": 120, "customer": "new customer", "issue": "wrong size"},
}
TOOLS = [
    {
        "name": "lookup_order",
        "description": "Look up an order by id.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "issue_refund",
        "description": "Refund an order. Refunds above the auto-approval limit need a human approver.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}, "amount": {"type": "number"}},
            "required": ["order_id", "amount"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def lookup_order(order_id: str) -> dict[str, Any]:
    order = ORDERS.get(order_id)
    if order is None:
        return {"error": "no such order"}
    dt.context(
        "order",
        f"shop:{order_id}",
        summary=f"${order['amount']}, {order['issue']}; {order['customer']}",
    )
    return order


def ask_approver(order_id: str, amount: float, approver: str | None) -> bool:
    if approver:
        return True
    if sys.stdin.isatty():
        return (
            input(f"Approve ${amount} refund for order {order_id}? [y/N] ").strip().lower() == "y"
        )
    return False


def issue_refund(order_id: str, amount: float, approver: str | None) -> dict[str, Any]:
    if amount <= AUTO_LIMIT:
        dt.policy(
            "refund.max_auto_amount",
            "pass",
            detail=f"${amount} within ${AUTO_LIMIT}",
            enforced=True,
        )
        return {"status": "refunded", "amount": amount}
    dt.policy(
        "refund.max_auto_amount", "fail", detail=f"${amount} exceeds ${AUTO_LIMIT}", enforced=True
    )
    dt.approval("requested", by="agent:refunds", detail="Over the auto-approval limit")
    if not ask_approver(order_id, amount, approver):
        dt.approval("rejected", by=approver or "support lead")
        return {"status": "denied", "reason": "approver declined"}
    who = approver or "support lead"
    dt.exception("refund.max_auto_amount", "Carrier damage confirmed; VIP customer", granted_by=who)
    dt.approval("approved", by=who)
    return {"status": "refunded", "amount": amount}


def run(client: Any, request: str, approver: str | None, model: str) -> str:
    client = dt.wrap(client, agent="refunds agent", kind="refund.decide")
    messages: list[dict[str, Any]] = [{"role": "user", "content": request}]
    while True:
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            tools=TOOLS,
            messages=messages,
            system="You are a refunds agent. Look up the order, then refund the full order amount.",
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            args = block.input
            out = (
                lookup_order(**args)
                if block.name == "lookup_order"
                else issue_refund(args["order_id"], args["amount"], approver)
            )
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(out),
                    "is_error": "error" in out,
                }
            )
        messages.append({"role": "user", "content": results})


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--live", action="store_true", help="call real Claude instead of the scripted model"
    )
    parser.add_argument("--order", default="7731")
    parser.add_argument(
        "--approver", default="Meera (support lead)", help="'' to be asked interactively"
    )
    args = parser.parse_args()
    client = anthropic.Anthropic() if args.live else scripted_anthropic_client(args.order, ORDERS)
    answer = run(
        client,
        f"Customer says order {args.order} arrived damaged. Please refund it.",
        args.approver or None,
        model="claude-opus-5-5",
    )
    print(answer)
    print(
        '\nRecorded. Try:  dt log   ·   dt why <id>   ·   dt ask "which refunds needed an exception?"'
    )


if __name__ == "__main__":
    main()
