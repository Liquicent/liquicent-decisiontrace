"""Scripted model clients so the examples run without an API key.

The Anthropic one is the *real* SDK client with a mock HTTP transport, so `dt.wrap` is
exercised exactly as in production; only the model's replies are canned.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx2


def _msg(content: list[dict[str, Any]], stop: str, n: int) -> dict[str, Any]:
    return {
        "id": f"msg_offline_{n}",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 400 + 150 * n, "output_tokens": 60, "cache_read_input_tokens": 0},
    }


def scripted_anthropic_client(order_id: str, orders: dict[str, Any]) -> anthropic.Anthropic:
    amount = orders.get(order_id, {}).get("amount", 0)

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        turns = sum(1 for m in body["messages"] if m["role"] == "assistant")
        last = body["messages"][-1]["content"]
        if turns == 0:
            reply = _msg(
                [
                    {
                        "type": "tool_use",
                        "id": "toolu_lookup",
                        "name": "lookup_order",
                        "input": {"order_id": order_id},
                    }
                ],
                "tool_use",
                0,
            )
        elif turns == 1:
            reply = _msg(
                [
                    {"type": "text", "text": "Order found; issuing the refund."},
                    {
                        "type": "tool_use",
                        "id": "toolu_refund",
                        "name": "issue_refund",
                        "input": {"order_id": order_id, "amount": amount},
                    },
                ],
                "tool_use",
                1,
            )
        else:
            outcome = json.loads(last[0]["content"]) if isinstance(last, list) else {}
            text = (
                f"Refunded ${amount} for order {order_id}."
                if outcome.get("status") == "refunded"
                else f"I couldn't refund order {order_id}: {outcome.get('reason', 'unknown')}."
            )
            reply = _msg([{"type": "text", "text": text}], "end_turn", 2)
        return httpx2.Response(200, json=reply)

    return anthropic.Anthropic(
        api_key="offline",
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
