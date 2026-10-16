"""Provider-neutral tracking of tool-use loops: one loop (first user message → final answer)
becomes one DecisionTrace. Proposed tool calls are actions once their result comes back;
calls still unanswered when the loop ends are recorded as rejected alternatives.

Wrappers only observe: the original SDK call always runs exactly as written, and any
recording error is logged, never raised.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from decisiontrace.recorder import DecisionBuilder, _log_error, _set_current, clip, sha

STALE_SECONDS = 3600


def get(obj: Any, key: str, default: Any = None) -> Any:
    """Field access that works for dicts and SDK objects alike."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@dataclass
class ToolResult:
    call_id: str
    is_error: bool = False


@dataclass
class Loop:
    builder: DecisionBuilder
    pending: dict[str, tuple[str, Any]] = field(default_factory=dict)
    touched: float = field(default_factory=time.time)


class LoopTracker:
    def __init__(self, provider: str, agent: str, kind: str) -> None:
        self.provider = provider
        self.agent = agent
        self.kind = kind
        self.loops: dict[str, Loop] = {}

    def before(self, first_text: str, first_raw: Any, results: list[ToolResult]) -> Loop | None:
        try:
            now = time.time()
            for key in [k for k, lp in self.loops.items() if now - lp.touched > STALE_SECONDS]:
                self._finish(self.loops.pop(key))
            key = sha(first_raw)
            loop = self.loops.get(key)
            if loop is None:
                builder = DecisionBuilder(
                    self.kind, clip(first_text or "Agent task", 500), self.agent
                )
                builder.client = {"name": f"{self.provider}-sdk"}
                builder.attributes["decisiontrace.adapter"] = f"{self.provider}_sdk"
                if first_text:
                    builder.context(
                        "user_prompt",
                        f"{self.provider}:prompt",
                        summary=clip(first_text, 400),
                        body=first_text,
                    )
                loop = Loop(builder)
                self.loops[key] = loop
            for result in results:
                if result.call_id in loop.pending:
                    name, args = loop.pending.pop(result.call_id)
                    loop.builder.action(
                        name,
                        summary=_args_summary(name, args),
                        call_id=result.call_id,
                        parameters=args,
                        status="failed" if result.is_error else None,
                    )
                    loop.builder.capability(f"tool.{name}")
            loop.touched = now
            _set_current(loop.builder)
            return loop
        except Exception as exc:
            _log_error(exc)
            return None

    def after(
        self,
        loop: Loop | None,
        model: str | None,
        usage: dict[str, int],
        calls: list[tuple[str, str, Any]],
        done: bool,
        stop_reason: str | None = None,
    ) -> None:
        if loop is None:
            return
        try:
            b = loop.builder
            if model:
                b.model = {"provider": self.provider, "name": str(model)[:128]}
            for k, v in usage.items():
                b.cost[k] = b.cost.get(k, 0) + int(v or 0)
            for call_id, name, args in calls:
                loop.pending[call_id] = (name, args)
            if stop_reason:
                b.attributes[f"{self.provider}.stop_reason"] = str(stop_reason)[:64]
            if done:
                for key, lp in list(self.loops.items()):
                    if lp is loop:
                        del self.loops[key]
                self._finish(loop)
                _set_current(None)
        except Exception as exc:
            _log_error(exc)

    def _finish(self, loop: Loop) -> None:
        for call_id, (name, args) in loop.pending.items():
            loop.builder.reject(
                name,
                by="system",
                reason="Proposed but never executed",
                summary=_args_summary(name, args),
                call_id=call_id,
            )
        loop.pending.clear()
        if loop.builder.actions and loop.builder.outcome_status is None:
            loop.builder.outcome("pending")  # close later with `dt outcome`
        loop.builder.write()


def _args_summary(name: str, args: Any) -> str:
    if args in (None, {}, ""):
        return f"{name}()"
    if isinstance(args, dict):
        return clip(f"{name}(" + ", ".join(f"{k}={v}" for k, v in args.items()) + ")", 240)
    return clip(f"{name}({args})", 240)
