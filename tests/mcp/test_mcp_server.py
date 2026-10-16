"""Exit test: record three decisions over MCP, then recall the right one."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters

from decisiontrace.mcp_server import build_server
from decisiontrace.store import Store

OVER_LIMIT = {
    "intent": "Refund $850 for order 7731, parcel crushed in transit",
    "kind": "refund.approve",
    "context": ["VIP customer, six years, no prior refunds"],
    "rules": [
        {
            "rule": "refund.max_auto_amount",
            "result": "fail",
            "detail": "Amount $850 exceeds the $500 limit",
        },
        {"rule": "refund.evidence_required", "result": "pass"},
    ],
    "exceptions": [
        {
            "rule": "refund.max_auto_amount",
            "reason": "VIP and carrier damage confirmed",
            "granted_by": "Meera (support lead)",
        }
    ],
    "rejected": ["Partial refund of $500"],
    "approvals": [
        {"step": "requested", "by": "refunds agent"},
        {"step": "approved", "by": "Meera (support lead)"},
    ],
    "actions": ["Full refund $850 via Stripe"],
    "outcome": "accepted",
}
WITHIN_LIMIT = {
    "intent": "Refund $120 for order 8120, wrong size",
    "kind": "refund.approve",
    "rules": [
        {
            "rule": "refund.max_auto_amount",
            "result": "pass",
            "detail": "Amount $120 is within the limit",
        }
    ],
    "actions": ["Refund $120 via Stripe"],
    "outcome": "accepted",
}
PR_MERGE = {
    "intent": "Merge PR 212 retry webhook delivery",
    "kind": "pr.merge",
    "rules": [{"rule": "ci.required_checks", "result": "pass"}],
    "approvals": [{"step": "approved", "by": "Praveen"}],
}
QUESTION = "how did we handle the last refund over the limit?"


def _payload(result: Any) -> dict[str, Any]:
    data: Any = getattr(result, "structured_content", None)
    if isinstance(data, dict):
        data = data.get("result", data)
    else:
        data = json.loads("".join(getattr(c, "text", "") for c in result.content))
    assert isinstance(data, dict)
    return data


async def _session(client: Client) -> tuple[list[str], dict[str, Any]]:
    ids = []
    for args in (OVER_LIMIT, WITHIN_LIMIT, PR_MERGE):
        ids.append(_payload(await client.call_tool("record", args))["id"])
    recalled = _payload(await client.call_tool("recall", {"query": QUESTION}))
    return ids, recalled


@pytest.fixture
def home(config: Any, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DT_HOME", str(config.home))
    return Path(config.home)


def test_tools_are_listed(home: Path) -> None:
    async def run() -> list[str]:
        async with Client(build_server()) as client:
            return sorted(t.name for t in (await client.list_tools()).tools)

    assert anyio.run(run) == ["outcome", "recall", "record"]


def test_record_recall_outcome_in_process(home: Path, config: Any) -> None:
    async def run() -> tuple[list[str], dict[str, Any], dict[str, Any]]:
        async with Client(build_server()) as client:
            ids, recalled = await _session(client)
            done = _payload(
                await client.call_tool(
                    "outcome",
                    {"decision_id": ids[0][:10], "status": "complained", "note": "Charged twice"},
                )
            )
            return ids, recalled, done

    ids, recalled, done = anyio.run(run)
    top = recalled["precedents"][0]
    assert top["id"] == ids[0], recalled
    assert top["exceptions"][0]["waived_by"] == "Meera"
    assert top["exceptions"][0]["role"] == "support lead"
    assert any(r["result"] == "fail" for r in top["rules"])
    assert [s["step"] for s in top["approval_path"]] == ["requested", "approved"]
    assert recalled["precedents"][-1]["kind"] != "pr.merge" or len(recalled["precedents"]) == 2
    assert done["status"] == "complained"
    with Store.open(config) as s:
        assert s.count() == 4
        assert s.verify().ok


def test_recall_by_decision_id_uses_similarity(home: Path) -> None:
    async def run() -> dict[str, Any]:
        async with Client(build_server()) as client:
            ids, _ = await _session(client)
            return _payload(await client.call_tool("recall", {"query": ids[1]}))

    recalled = anyio.run(run)
    top = recalled["precedents"][0]
    assert top["kind"] == "refund.approve"
    assert "similarity" in top and top["strength"] in ("strong", "weak", "none")


def test_record_redacts(home: Path, config: Any) -> None:
    async def run() -> dict[str, Any]:
        async with Client(build_server()) as client:
            return _payload(
                await client.call_tool(
                    "record",
                    {
                        "intent": "Rotated key sk-ant-api03-ZZZZZZZZZZZZZZZZZZZZZZZZ for jo@example.com"
                    },
                )
            )

    out = anyio.run(run)
    assert out["redactions"] == 2
    raw = b"".join(p.read_bytes() for p in Path(config.home).rglob("*") if p.is_file())
    assert b"ZZZZZZZZZZZZZZZZ" not in raw and b"jo@example.com" not in raw


def test_end_to_end_over_stdio(home: Path) -> None:
    """The real transport a desktop client uses: `python -m decisiontrace mcp`."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "decisiontrace", "mcp"],
        env={**os.environ, "DT_HOME": str(home)},
    )

    async def run() -> tuple[list[str], dict[str, Any]]:
        async with Client(params) as client:
            return await _session(client)

    ids, recalled = anyio.run(run)
    assert recalled["precedents"][0]["id"] == ids[0]
