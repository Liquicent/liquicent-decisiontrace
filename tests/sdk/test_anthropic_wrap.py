"""dt.wrap on the real Anthropic SDK client, with a mock HTTP transport for the model."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

import decisiontrace as dt  # noqa: E402
from decisiontrace.model import DecisionTrace  # noqa: E402
from decisiontrace.store import Store  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
sys.path.insert(0, str(EXAMPLES))
import refund_agent  # noqa: E402
from _offline import scripted_anthropic_client  # noqa: E402


@pytest.fixture
def home(config: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("DT_HOME", str(config.home))
    return config


def decisions(config: Any) -> list[DecisionTrace]:
    with Store.open(config) as s:
        return [r for r in s.records(newest_first=False) if isinstance(r, DecisionTrace)]


def test_refund_showcase_records_p_e_h_and_actions(home: Any) -> None:
    client = scripted_anthropic_client("7731", refund_agent.ORDERS)
    answer = refund_agent.run(
        client, "Refund order 7731, it arrived crushed", "Meera (support lead)", "claude-opus-5-5"
    )
    assert answer == "Refunded $850 for order 7731."
    (d,) = decisions(home)
    assert d.decision_kind == "refund.decide"
    assert [a.name for a in d.actions or []] == ["lookup_order", "issue_refund"]
    assert (d.actions or [])[1].summary == "issue_refund(order_id=7731, amount=850)"
    assert [(p.policy_id, p.result) for p in d.policies or []] == [
        ("refund.max_auto_amount", "fail")
    ]
    assert d.exceptions and d.exceptions[0].granted_by.name == "Meera"
    assert [h.type for h in d.human_path or []] == ["requested", "approved"]
    assert d.actor_time.model and d.actor_time.model.name == "claude-opus-5-5"
    assert d.actor_time.cost and d.actor_time.cost.input_tokens == 400 + 550 + 700
    assert d.outcome and d.outcome.status == "pending"
    assert d.context and any(i.type == "order" for i in d.context.inputs or [])


def test_refund_denied_when_no_approver(home: Any) -> None:
    client = scripted_anthropic_client("7731", refund_agent.ORDERS)
    answer = refund_agent.run(client, "Refund order 7731", None, "claude-opus-5-5")
    assert "couldn't refund" in answer
    (d,) = decisions(home)
    assert [h.type for h in d.human_path or []] == ["requested", "rejected"]
    assert not d.exceptions


def test_small_refund_passes_policy(home: Any) -> None:
    client = scripted_anthropic_client("8120", refund_agent.ORDERS)
    refund_agent.run(client, "Refund order 8120", None, "claude-opus-5-5")
    (d,) = decisions(home)
    assert [(p.result) for p in d.policies or []] == ["pass"]
    assert not d.human_path


def _client(handler: Any, async_: bool = False) -> Any:
    transport = httpx2.MockTransport(handler)
    if async_:
        return anthropic.AsyncAnthropic(
            api_key="x", http_client=anthropic.DefaultAsyncHttpxClient(transport=transport)
        )
    return anthropic.Anthropic(
        api_key="x", http_client=anthropic.DefaultHttpxClient(transport=transport)
    )


def _two_step_handler(request: Any) -> Any:
    body = json.loads(request.content)
    if not any(m["role"] == "assistant" for m in body["messages"]):
        content = [
            {"type": "tool_use", "id": "toolu_a", "name": "get_order", "input": {"order_id": "1"}},
            {
                "type": "tool_use",
                "id": "toolu_b",
                "name": "delete_order",
                "input": {"order_id": "1"},
            },
        ]
        stop = "tool_use"
    else:
        content, stop = [{"type": "text", "text": "done"}], "end_turn"
    return httpx2.Response(
        200,
        json={
            "id": "m",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    )


def test_unanswered_tool_call_becomes_rejected_alternative(home: Any) -> None:
    client = dt.wrap(_client(_two_step_handler))
    msgs: list[Any] = [{"role": "user", "content": "check order 1"}]
    r = client.messages.create(model="claude-opus-5-5", max_tokens=100, messages=msgs)
    msgs += [
        {"role": "assistant", "content": r.content},
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_a", "content": "{}"}],
        },
    ]
    client.messages.create(model="claude-opus-5-5", max_tokens=100, messages=msgs)
    (d,) = decisions(home)
    assert [a.name for a in d.actions or []] == ["get_order"]
    assert [x.action.name for x in d.alternatives or []] == ["delete_order"]
    assert (d.alternatives or [])[0].rejected_by == "system"


def test_tool_runner_path(home: Any) -> None:
    from anthropic import beta_tool

    @beta_tool
    def get_order(order_id: str) -> str:
        """Look up an order.

        Args:
            order_id: the order id
        """
        dt.policy("orders.read_allowed", "pass")
        return json.dumps({"order_id": order_id, "status": "shipped"})

    def handler(request: Any) -> Any:
        body = json.loads(request.content)
        if not any(m["role"] == "assistant" for m in body["messages"]):
            content = [
                {
                    "type": "tool_use",
                    "id": "toolu_r",
                    "name": "get_order",
                    "input": {"order_id": "9"},
                }
            ]
            stop = "tool_use"
        else:
            content, stop = [{"type": "text", "text": "It shipped."}], "end_turn"
        return httpx2.Response(
            200,
            json={
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": content,
                "stop_reason": stop,
                "stop_sequence": None,
                "usage": {"input_tokens": 7, "output_tokens": 3},
            },
        )

    client = dt.wrap(_client(handler), agent="runner-agent")
    runner = client.beta.messages.tool_runner(
        model="claude-opus-5-5",
        max_tokens=1000,
        tools=[get_order],
        messages=[{"role": "user", "content": "Where is order 9?"}],
    )
    final = runner.until_done()
    assert final.content[-1].text == "It shipped."
    (d,) = decisions(home)
    assert [a.name for a in d.actions or []] == ["get_order"]
    assert [p.policy_id for p in d.policies or []] == ["orders.read_allowed"]
    assert d.actor_time.actor.name == "runner-agent"


def test_async_client(home: Any) -> None:
    client = dt.wrap(_client(_two_step_handler, async_=True))

    async def run() -> None:
        msgs: list[Any] = [{"role": "user", "content": "async check"}]
        r = await client.messages.create(model="claude-opus-5-5", max_tokens=100, messages=msgs)
        msgs += [
            {"role": "assistant", "content": r.content},
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_a", "content": "{}"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_b",
                        "content": "boom",
                        "is_error": True,
                    },
                ],
            },
        ]
        await client.messages.create(model="claude-opus-5-5", max_tokens=100, messages=msgs)

    anyio.run(run)
    (d,) = decisions(home)
    assert [(a.name, a.status) for a in d.actions or []] == [
        ("get_order", None),
        ("delete_order", "failed"),
    ]


def test_stream_manager(home: Any) -> None:
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "m",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-opus-5-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 11, "output_tokens": 0},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "hello"},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 4},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    sse = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events)

    def handler(request: Any) -> Any:
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=sse.encode()
        )

    client = dt.wrap(_client(handler))
    with client.messages.stream(
        model="claude-opus-5-5", max_tokens=100, messages=[{"role": "user", "content": "say hello"}]
    ) as stream:
        text = "".join(stream.text_stream)
    assert text == "hello"
    (d,) = decisions(home)
    assert d.intent == "say hello"
    assert d.actor_time.cost and d.actor_time.cost.output_tokens == 4


def test_recording_failure_never_breaks_the_call(
    home: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decisiontrace.store import Store as RealStore

    def broken(*a: Any, **k: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(RealStore, "open", broken)
    client = dt.wrap(_client(_two_step_handler))
    msgs: list[Any] = [{"role": "user", "content": "x"}]
    r = client.messages.create(model="claude-opus-5-5", max_tokens=100, messages=msgs)
    msgs += [
        {"role": "assistant", "content": r.content},
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_a", "content": "{}"}],
        },
    ]
    final = client.messages.create(model="claude-opus-5-5", max_tokens=100, messages=msgs)
    assert final.content[0].text == "done"
    assert "disk full" in (home.home / "recorder-errors.log").read_text()


def test_wrap_is_idempotent(home: Any) -> None:
    client = _client(_two_step_handler)
    assert dt.wrap(dt.wrap(client)) is client
