"""Record tool-use loops made through the OpenAI Python SDK (Chat Completions and
Responses APIs). Duck-typed: the ``openai`` package is never imported."""

from __future__ import annotations

import inspect
import json
from typing import Any

from decisiontrace.adapters.loop import Loop, LoopTracker, ToolResult, get


def _args(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = [get(p, "text", "") for p in content or [] if get(p, "type") in ("text", "input_text")]
    return " ".join(p for p in parts if p)


# -- Chat Completions -------------------------------------------------------------------------


def _chat_before(tracker: LoopTracker, kwargs: dict[str, Any]) -> Loop | None:
    messages = list(kwargs.get("messages") or [])
    first = next((m for m in messages if get(m, "role") == "user"), None)
    text = _text(get(first, "content")) if first is not None else ""
    results = [
        ToolResult(str(get(m, "tool_call_id"))) for m in messages if get(m, "role") == "tool"
    ]
    return tracker.before(text, json.dumps(get(first, "content"), default=str), results)


def _chat_after(tracker: LoopTracker, loop: Loop | None, resp: Any) -> None:
    choices = get(resp, "choices") or []
    choice = choices[0] if choices else None
    message = get(choice, "message")
    calls = [
        (
            str(get(c, "id")),
            str(get(get(c, "function"), "name")),
            _args(get(get(c, "function"), "arguments")),
        )
        for c in get(message, "tool_calls") or []
    ]
    finish = get(choice, "finish_reason")
    usage = get(resp, "usage")
    details = get(usage, "prompt_tokens_details")
    tokens = (
        {
            "input_tokens": get(usage, "prompt_tokens") or 0,
            "output_tokens": get(usage, "completion_tokens") or 0,
            "cache_read_input_tokens": get(details, "cached_tokens") or 0,
        }
        if usage is not None
        else {}
    )
    tracker.after(
        loop, get(resp, "model"), tokens, calls, done=finish != "tool_calls", stop_reason=finish
    )


# -- Responses API ----------------------------------------------------------------------------


def _responses_before(tracker: LoopTracker, kwargs: dict[str, Any]) -> Loop | None:
    raw = kwargs.get("input")
    if isinstance(raw, str):
        return tracker.before(raw, raw, [])
    items = list(raw or [])
    first = next((i for i in items if get(i, "role") == "user"), None)
    text = _text(get(first, "content")) if first is not None else ""
    results = [
        ToolResult(str(get(i, "call_id")))
        for i in items
        if get(i, "type") == "function_call_output"
    ]
    return tracker.before(text, json.dumps(get(first, "content"), default=str), results)


def _responses_after(tracker: LoopTracker, loop: Loop | None, resp: Any) -> None:
    calls = [
        (str(get(o, "call_id")), str(get(o, "name")), _args(get(o, "arguments")))
        for o in get(resp, "output") or []
        if get(o, "type") == "function_call"
    ]
    usage = get(resp, "usage")
    details = get(usage, "input_tokens_details")
    tokens = (
        {
            "input_tokens": get(usage, "input_tokens") or 0,
            "output_tokens": get(usage, "output_tokens") or 0,
            "cache_read_input_tokens": get(details, "cached_tokens") or 0,
        }
        if usage is not None
        else {}
    )
    tracker.after(
        loop, get(resp, "model"), tokens, calls, done=not calls, stop_reason=get(resp, "status")
    )


def _patch(resource: Any, before: Any, after: Any, tracker: LoopTracker) -> None:
    original = getattr(resource, "create", None)
    if original is None:
        return

    def call(*args: Any, **kwargs: Any) -> Any:
        loop = before(tracker, kwargs)
        result = original(*args, **kwargs)
        if kwargs.get("stream"):
            return result
        if inspect.isawaitable(result):

            async def finish() -> Any:
                response = await result
                after(tracker, loop, response)
                return response

            return finish()
        after(tracker, loop, result)
        return result

    resource.create = call


def wrap(client: Any, agent: str = "openai-agent", kind: str = "agent.decision") -> Any:
    """Instrument an ``openai.OpenAI`` / ``AsyncOpenAI`` client in place; returns it."""
    if getattr(client, "_decisiontrace_tracker", None) is not None:
        return client
    tracker = LoopTracker("openai", agent, kind)
    chat = get(client, "chat")
    if chat is not None and get(chat, "completions") is not None:
        _patch(get(chat, "completions"), _chat_before, _chat_after, tracker)
    if get(client, "responses") is not None:
        _patch(get(client, "responses"), _responses_before, _responses_after, tracker)
    client._decisiontrace_tracker = tracker
    return client
