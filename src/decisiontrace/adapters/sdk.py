"""``decisiontrace.wrap(client)`` -- pick the right adapter for an SDK client."""

from __future__ import annotations

from typing import Any


def wrap(
    client: Any, provider: str | None = None, agent: str | None = None, kind: str = "agent.decision"
) -> Any:
    """Record the tool-use loops a client makes, with no other code change.

    ``provider`` is detected from the client's package ('anthropic' or 'openai'); pass it
    explicitly for test doubles or compatible clients.
    """
    provider = provider or type(client).__module__.split(".")[0]
    if provider == "anthropic":
        from decisiontrace.adapters.anthropic_sdk import wrap as wrap_anthropic

        return wrap_anthropic(client, agent=agent or "anthropic-agent", kind=kind)
    if provider == "openai":
        from decisiontrace.adapters.openai_sdk import wrap as wrap_openai

        return wrap_openai(client, agent=agent or "openai-agent", kind=kind)
    raise TypeError(
        f"don't know how to wrap a {type(client).__name__}; pass provider='anthropic' or 'openai'"
    )
