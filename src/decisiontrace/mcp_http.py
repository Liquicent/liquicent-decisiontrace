"""Self-hosted MCP server over HTTP: the same tools as ``dt mcp``, for a whole company.

Run it inside the company's own infrastructure (behind TLS) and connect Claude.ai or ChatGPT
workspaces, Claude Code, or the company's own agents to it. Records stay in the company's
store; nothing is sent anywhere else.

Authentication is a shared token, accepted two ways:

* ``Authorization: Bearer <token>`` on ``/mcp`` — for clients that can send a header
  (Claude Code, SDK agents);
* a secret URL, ``/t/<token>/mcp`` — for connector UIs that only take a URL.

``/healthz`` answers ``ok`` without a token and returns no data. Access logs are off by
default so the secret URL is never written to a log.
"""

from __future__ import annotations

import hmac
import os
import secrets
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings

from decisiontrace.mcp_server import TOOLS, build_server

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
MIN_TOKEN = 24
TOKEN_ENV = "DT_MCP_TOKEN"


class ServeError(ValueError):
    pass


def new_token() -> str:
    return secrets.token_urlsafe(32)


async def _plain(
    send: Send, status: int, body: bytes, extra: list[tuple[bytes, bytes]] | None = None
) -> None:
    headers = [
        (b"content-type", b"text/plain; charset=utf-8"),
        (b"content-length", str(len(body)).encode()),
    ]
    await send(
        {"type": "http.response.start", "status": status, "headers": headers + (extra or [])}
    )
    await send({"type": "http.response.body", "body": body})


def guard(app: ASGIApp, token: str | None, path: str = "/mcp") -> ASGIApp:
    """Health check, then token check (header or secret path), then the MCP app."""
    expected_header = f"Bearer {token}".encode() if token else None
    secret_prefix = f"/t/{token}" if token else None

    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)  # lifespan
            return
        req_path: str = scope.get("path", "")
        if req_path == "/healthz":
            await _plain(send, 200, b"ok")
            return
        if token is None:
            await app(scope, receive, send)
            return
        if (
            secret_prefix
            and req_path.startswith(secret_prefix + "/")
            and hmac.compare_digest(req_path[: len(secret_prefix)].encode(), secret_prefix.encode())
        ):
            inner = dict(scope)
            inner["path"] = req_path[len(secret_prefix) :]
            inner["raw_path"] = inner["path"].encode()
            await app(inner, receive, send)
            return
        given = b""
        for name, value in scope.get("headers", []):
            if name.lower() == b"authorization":
                given = value
        if (
            expected_header
            and req_path.startswith(path)
            and hmac.compare_digest(given, expected_header)
        ):
            await app(scope, receive, send)
            return
        await _plain(
            send, 401, b"unauthorized", [(b"www-authenticate", b'Bearer realm="decisiontrace"')]
        )

    return wrapped


def build_app(
    token: str | None,
    tools: tuple[str, ...] | list[str] = TOOLS,
    client_name: str = "mcp-http",
    host: str = "127.0.0.1",
    allowed_hosts: list[str] | None = None,
) -> ASGIApp:
    """The guarded ASGI app. Raises ServeError for an unsafe configuration."""
    if token is not None and len(token) < MIN_TOKEN:
        raise ServeError(
            f"token too short: use at least {MIN_TOKEN} characters (`dt mcp --new-token`)"
        )
    if token is None and host not in LOOPBACK:
        raise ServeError(
            f"refusing to listen on {host} without a token: set {TOKEN_ENV} (or --token), "
            "and put TLS in front"
        )
    server = build_server(tools=tuple(tools), client_name=client_name, local_user=False)
    if allowed_hosts:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts
        )
    elif host in LOOPBACK and token is None:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
        )
    else:
        # behind a reverse proxy the Host header is the public name; the token already stops
        # a rebinding page (it cannot know the token)
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    inner = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=security,
        host=host,
    )
    return guard(inner, token)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    tools: tuple[str, ...] | list[str] = TOOLS,
    client_name: str = "mcp-http",
    allowed_hosts: list[str] | None = None,
    access_log: bool = False,
) -> None:
    import uvicorn

    app = build_app(
        token or os.environ.get(TOKEN_ENV) or None, tools, client_name, host, allowed_hosts
    )
    uvicorn.run(
        app, host=host, port=port, access_log=access_log, log_level="info", proxy_headers=True
    )
