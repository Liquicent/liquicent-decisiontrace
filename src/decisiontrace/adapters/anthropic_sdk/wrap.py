"""Record tool-use loops made through the Anthropic Python SDK.

Instruments ``messages.create``, ``messages.parse`` and ``messages.stream`` (and the
``beta`` equivalents, which the SDK's tool runner uses) on one client instance, sync or
async. Calls pass through unchanged.
"""

from __future__ import annotations

import contextlib
import inspect
import json
from typing import Any

from decisiontrace.adapters.loop import Loop, LoopTracker, ToolResult, get

DONE_REASONS = {
    "end_turn",
    "max_tokens",
    "stop_sequence",
    "refusal",
    "model_context_window_exceeded",
}


def _first_user(messages: list[Any]) -> tuple[str, Any]:
    for m in messages:
        if get(m, "role") == "user":
            content = get(m, "content")
            if isinstance(content, str):
                return content, content
            texts = [get(b, "text", "") for b in content or [] if get(b, "type") == "text"]
            return " ".join(t for t in texts if t), json.dumps(content, default=str, sort_keys=True)
    return "", ""


def _results(messages: list[Any]) -> list[ToolResult]:
    out = []
    for m in messages:
        if get(m, "role") != "user" or isinstance(get(m, "content"), str):
            continue
        for b in get(m, "content") or []:
            if get(b, "type") == "tool_result":
                out.append(ToolResult(str(get(b, "tool_use_id")), bool(get(b, "is_error", False))))
    return out


def _observe(tracker: LoopTracker, loop: Loop | None, message: Any) -> None:
    if message is None:
        return
    usage = get(message, "usage")
    tokens = (
        {
            "input_tokens": (get(usage, "input_tokens") or 0)
            + (get(usage, "cache_creation_input_tokens") or 0),
            "output_tokens": get(usage, "output_tokens") or 0,
            "cache_read_input_tokens": get(usage, "cache_read_input_tokens") or 0,
        }
        if usage is not None
        else {}
    )
    calls = [
        (str(get(b, "id")), str(get(b, "name")), get(b, "input"))
        for b in get(message, "content") or []
        if get(b, "type") == "tool_use"
    ]
    stop = get(message, "stop_reason")
    tracker.after(
        loop, get(message, "model"), tokens, calls, done=stop in DONE_REASONS, stop_reason=stop
    )


def _before(tracker: LoopTracker, kwargs: dict[str, Any]) -> Loop | None:
    messages = list(kwargs.get("messages") or [])
    text, raw = _first_user(messages)
    return tracker.before(text, raw, _results(messages))


class _StreamManager:
    def __init__(self, manager: Any, tracker: LoopTracker, loop: Loop | None) -> None:
        self._manager, self._tracker, self._loop, self._stream = manager, tracker, loop, None

    def __enter__(self) -> Any:
        self._stream = self._manager.__enter__()
        return self._stream

    def __exit__(self, *exc: Any) -> Any:
        with contextlib.suppress(Exception):  # recording must never break the caller
            _observe(
                self._tracker, self._loop, getattr(self._stream, "current_message_snapshot", None)
            )
        return self._manager.__exit__(*exc)

    async def __aenter__(self) -> Any:
        self._stream = await self._manager.__aenter__()
        return self._stream

    async def __aexit__(self, *exc: Any) -> Any:
        with contextlib.suppress(Exception):  # recording must never break the caller
            _observe(
                self._tracker, self._loop, getattr(self._stream, "current_message_snapshot", None)
            )
        return await self._manager.__aexit__(*exc)


def _patch(resource: Any, tracker: LoopTracker) -> None:
    for name in ("create", "parse"):
        original = getattr(resource, name, None)
        if original is None:
            continue

        def call(*args: Any, __orig: Any = original, **kwargs: Any) -> Any:
            loop = _before(tracker, kwargs)
            result = __orig(*args, **kwargs)
            if kwargs.get("stream"):  # raw stream=True iterators are not recorded
                return result
            if inspect.isawaitable(result):  # async client (decorators hide coroutine-ness)

                async def finish() -> Any:
                    message = await result
                    _observe(tracker, loop, message)
                    return message

                return finish()
            _observe(tracker, loop, result)
            return result

        setattr(resource, name, call)
    stream = getattr(resource, "stream", None)
    if stream is not None:

        def stream_call(*args: Any, __orig: Any = stream, **kwargs: Any) -> Any:
            loop = _before(tracker, kwargs)
            return _StreamManager(__orig(*args, **kwargs), tracker, loop)

        resource.stream = stream_call


def wrap(client: Any, agent: str = "anthropic-agent", kind: str = "agent.decision") -> Any:
    """Instrument an ``anthropic.Anthropic`` / ``AsyncAnthropic`` client in place; returns it."""
    if getattr(client, "_decisiontrace_tracker", None) is not None:
        return client
    tracker = LoopTracker("anthropic", agent, kind)
    resources = [get(client, "messages")]
    beta = get(client, "beta")
    if beta is not None:
        resources.append(get(beta, "messages"))
    for resource in resources:
        if resource is not None:
            _patch(resource, tracker)
    client._decisiontrace_tracker = tracker
    return client
