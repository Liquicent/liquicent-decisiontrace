"""dt.wrap on OpenAI-shaped clients (duck typed; the openai package is not needed)."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS
from typing import Any

import pytest

import decisiontrace as dt
from decisiontrace.model import DecisionTrace
from decisiontrace.store import Store


@pytest.fixture
def home(config: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("DT_HOME", str(config.home))
    return config


def decisions(config: Any) -> list[DecisionTrace]:
    with Store.open(config) as s:
        return [r for r in s.records(newest_first=False) if isinstance(r, DecisionTrace)]


class FakeCompletions:
    def create(self, **kwargs: Any) -> Any:
        tool_msgs = [m for m in kwargs["messages"] if m.get("role") == "tool"]
        usage = NS(
            prompt_tokens=50, completion_tokens=10, prompt_tokens_details=NS(cached_tokens=20)
        )
        if not tool_msgs:
            call = NS(
                id="call_1",
                function=NS(
                    name="issue_refund", arguments=json.dumps({"order_id": "7", "amount": 900})
                ),
            )
            msg = NS(content=None, tool_calls=[call])
            return NS(
                model="gpt-5", choices=[NS(message=msg, finish_reason="tool_calls")], usage=usage
            )
        msg = NS(content="Refunded.", tool_calls=None)
        return NS(model="gpt-5", choices=[NS(message=msg, finish_reason="stop")], usage=usage)


class FakeResponses:
    def create(self, **kwargs: Any) -> Any:
        items = kwargs["input"] if isinstance(kwargs["input"], list) else []
        usage = NS(input_tokens=30, output_tokens=5, input_tokens_details=NS(cached_tokens=0))
        if not any(i.get("type") == "function_call_output" for i in items):
            out = [
                NS(
                    type="function_call",
                    call_id="fc_1",
                    name="lookup_order",
                    arguments='{"order_id": "7"}',
                )
            ]
            return NS(model="gpt-5", output=out, usage=usage, status="completed")
        return NS(model="gpt-5", output=[NS(type="message")], usage=usage, status="completed")


def make_client() -> Any:
    return NS(chat=NS(completions=FakeCompletions()), responses=FakeResponses())


def test_chat_completions_loop(home: Any) -> None:
    client = dt.wrap(make_client(), provider="openai", kind="refund.decide")
    msgs: list[dict[str, Any]] = [{"role": "user", "content": "Refund order 7 please"}]
    r = client.chat.completions.create(model="gpt-5", messages=msgs)
    call = r.choices[0].message.tool_calls[0]
    dt.policy("refund.max_auto_amount", "fail", detail="$900 > $500", enforced=True)
    dt.exception("refund.max_auto_amount", "Damaged in transit", granted_by="Ana (ops lead)")
    msgs += [
        {"role": "assistant", "tool_calls": [{"id": call.id}]},
        {"role": "tool", "tool_call_id": call.id, "content": "ok"},
    ]
    client.chat.completions.create(model="gpt-5", messages=msgs)
    (d,) = decisions(home)
    assert d.intent == "Refund order 7 please"
    assert [a.name for a in d.actions or []] == ["issue_refund"]
    assert d.exceptions and d.exceptions[0].granted_by.role == "ops lead"
    assert d.actor_time.model and d.actor_time.model.provider == "openai"
    assert d.actor_time.cost and d.actor_time.cost.input_tokens == 100
    assert d.actor_time.cost.cache_read_input_tokens == 40


def test_responses_api_loop(home: Any) -> None:
    client = dt.wrap(make_client(), provider="openai")
    first = client.responses.create(
        model="gpt-5", input=[{"role": "user", "content": "Where is order 7?"}]
    )
    fc = first.output[0]
    client.responses.create(
        model="gpt-5",
        input=[
            {"role": "user", "content": "Where is order 7?"},
            {
                "type": "function_call",
                "call_id": fc.call_id,
                "name": fc.name,
                "arguments": fc.arguments,
            },
            {"type": "function_call_output", "call_id": fc.call_id, "output": "shipped"},
        ],
    )
    (d,) = decisions(home)
    assert [a.summary for a in d.actions or []] == ["lookup_order(order_id=7)"]


def test_unknown_client_type() -> None:
    with pytest.raises(TypeError):
        dt.wrap(object())


def test_decision_context_manager(home: Any) -> None:
    with dt.decision("refund.approve", intent="Refund $850 for order 7731", agent="refunds") as d:
        d.context("order", "shop:7731", summary="damaged")
        d.policy("refund.max_auto_amount", "fail", detail="$850 > $500", enforced=True)
        dt.exception(
            "refund.max_auto_amount", "VIP", granted_by="Meera (support lead)"
        )  # module-level
        d.approval("approved", by="Meera (support lead)")
        d.action("stripe.refunds.create", summary="Full refund", type="api_call")
        d.reject("partial_refund", by="human", reason="damage covers whole order")
    (rec,) = decisions(home)
    assert rec.decision_kind == "refund.approve"
    assert rec.exceptions and rec.alternatives and rec.human_path
    assert dt.recorder.current() is None if hasattr(dt, "recorder") else True


def test_decision_marks_failure_and_reraises(home: Any) -> None:
    with pytest.raises(ValueError), dt.decision("job.run", intent="crashes") as d:
        d.action("step1")
        raise ValueError("boom")
    (rec,) = decisions(home)
    assert rec.outcome and rec.outcome.status == "failed"


def test_async_openai_client(home: Any) -> None:
    import anyio

    class AsyncCompletions:
        async def create(self, **kwargs: Any) -> Any:
            return FakeCompletions().create(**kwargs)

    client = dt.wrap(NS(chat=NS(completions=AsyncCompletions())), provider="openai")

    async def run() -> None:
        msgs: list[dict[str, Any]] = [{"role": "user", "content": "async refund"}]
        await client.chat.completions.create(model="gpt-5", messages=msgs)
        msgs.append({"role": "tool", "tool_call_id": "call_1", "content": "ok"})
        await client.chat.completions.create(model="gpt-5", messages=msgs)

    anyio.run(run)
    (d,) = decisions(home)
    assert [a.name for a in d.actions or []] == ["issue_refund"]
