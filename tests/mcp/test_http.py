"""Self-hosted MCP over HTTP: auth (header and secret URL), tool filtering, attribution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from decisiontrace.cli import app as cli
from decisiontrace.config import load_config
from decisiontrace.mcp_http import ServeError, build_app, new_token
from decisiontrace.model import DecisionTrace
from decisiontrace.store import Store

TOKEN = "t" * 40
H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "1"},
    },
}


def rpc(method: str, params: dict[str, Any] | None = None, id_: int = 2) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "method": method, **({"params": params} if params else {})}


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DT_HOME", str(tmp_path / "dt"))
    return tmp_path / "dt"


def test_health_needs_no_token_and_says_nothing(home: Path) -> None:
    with TestClient(build_app(TOKEN, host="0.0.0.0")) as c:
        r = c.get("/healthz")
    assert r.status_code == 200 and r.text == "ok"


def test_token_by_header_or_secret_url(home: Path) -> None:
    with TestClient(build_app(TOKEN, host="0.0.0.0")) as c:
        assert c.post("/mcp", json=INIT, headers=H).status_code == 401
        assert (
            c.post("/mcp", json=INIT, headers=H | {"Authorization": "Bearer wrong"}).status_code
            == 401
        )
        assert c.post(f"/t/{'x' * 40}/mcp", json=INIT, headers=H).status_code == 401
        assert c.post(f"/t/{TOKEN}", json=INIT, headers=H).status_code == 401
        ok = c.post("/mcp", json=INIT, headers=H | {"Authorization": f"Bearer {TOKEN}"})
        assert (
            ok.status_code == 200 and ok.json()["result"]["serverInfo"]["name"] == "decisiontrace"
        )
        r = c.post(f"/t/{TOKEN}/mcp", json=rpc("tools/list"), headers=H)
        assert {t["name"] for t in r.json()["result"]["tools"]} == {"record", "recall", "outcome"}


def test_record_through_http_is_attributed_to_the_person_not_the_server(home: Path) -> None:
    call = rpc(
        "tools/call",
        {
            "name": "record",
            "arguments": {
                "intent": "Refund $850 for order 7731",
                "kind": "refund.approve",
                "rules": [{"rule": "refund.max_auto_amount", "result": "fail"}],
                "on_behalf_of": "Meera (support lead)",
                "agent": "claude.ai",
            },
        },
    )
    with TestClient(build_app(TOKEN, host="0.0.0.0", client_name="claude.ai connector")) as c:
        r = c.post(f"/t/{TOKEN}/mcp", json=call, headers=H)
        assert r.status_code == 200 and not r.json()["result"]["isError"]
        anonymous = rpc(
            "tools/call", {"name": "record", "arguments": {"intent": "Approve PO"}}, id_=3
        )
        assert c.post(f"/t/{TOKEN}/mcp", json=anonymous, headers=H).status_code == 200
    with Store.open(load_config(home)) as s:
        traces = [
            t
            for t in s.records(record_type="decision", newest_first=False)
            if isinstance(t, DecisionTrace)
        ]
        assert s.verify().ok
    first, second = traces
    assert first.actor_time.on_behalf_of and first.actor_time.on_behalf_of.name == "Meera"
    assert first.actor_time.client and first.actor_time.client.name == "claude.ai connector"
    assert second.actor_time.on_behalf_of is None  # never the server's OS account


def test_tools_can_be_limited(home: Path) -> None:
    with TestClient(build_app(TOKEN, tools=["record", "outcome"], host="0.0.0.0")) as c:
        r = c.post(f"/t/{TOKEN}/mcp", json=rpc("tools/list"), headers=H)
        assert {t["name"] for t in r.json()["result"]["tools"]} == {"record", "outcome"}
        call = rpc("tools/call", {"name": "recall", "arguments": {"query": "refund"}}, id_=3)
        body = c.post(f"/t/{TOKEN}/mcp", json=call, headers=H).json()
        assert "error" in body or body["result"]["isError"]
    with pytest.raises(ValueError, match="unknown tool"):
        build_app(TOKEN, tools=["record", "delete_everything"], host="0.0.0.0")


def test_unsafe_configurations_are_refused(home: Path) -> None:
    with pytest.raises(ServeError, match="without a token"):
        build_app(None, host="0.0.0.0")
    with pytest.raises(ServeError, match="too short"):
        build_app("short", host="127.0.0.1")
    build_app(None, host="127.0.0.1")  # localhost without a token is fine
    assert len(new_token()) >= 40


def test_localhost_without_token_checks_host_header(home: Path) -> None:
    with TestClient(build_app(None, host="127.0.0.1"), base_url="http://127.0.0.1:8765") as c:
        assert c.post("/mcp", json=INIT, headers=H).status_code == 200
    with TestClient(build_app(None, host="127.0.0.1"), base_url="http://evil.example") as c:
        assert c.post("/mcp", json=INIT, headers=H).status_code != 200  # DNS-rebinding protection


def test_cli_refuses_open_network_without_token(home: Path) -> None:
    r = CliRunner().invoke(cli, ["mcp", "--http", "--host", "0.0.0.0"], env={"DT_MCP_TOKEN": ""})
    assert r.exit_code == 1 and "without a token" in r.output
    r = CliRunner().invoke(cli, ["mcp", "--new-token"])
    assert r.exit_code == 0 and len(r.output.strip()) >= 40
