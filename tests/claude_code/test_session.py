"""End-to-end: hook payloads for a realistic Claude Code session → queue → drain → store."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from decisiontrace.adapters.claude_code import hook
from decisiontrace.adapters.claude_code.drain import drain
from decisiontrace.model import DecisionTrace
from decisiontrace.store import Store

SECRET = "sk-ant-api03-SESSIONsecretSESSIONsecret00"


def _send(home: Path, payload: dict[str, Any]) -> None:
    base = {"session_id": "sess-1", "cwd": str(home.parent / "proj"), "permission_mode": "default"}
    hook.run(json.dumps({**base, **payload}), home=str(home), drain=False)
    time.sleep(0.001)


def _pre_post(home: Path, tid: str, tool: str, tool_input: dict[str, Any], **extra: Any) -> None:
    common = {
        "prompt_id": "p1",
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": tid,
        **extra,
    }
    _send(home, {"hook_event_name": "PreToolUse", **common})
    _send(home, {"hook_event_name": "PostToolUse", "tool_response": {"ok": True}, **common})


def _transcript(path: Path) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    rows = [
        {"type": "user", "timestamp": now + ".000Z", "message": {"role": "user"}},
        {
            "type": "assistant",
            "timestamp": now + ".100Z",
            "version": "2.1.300",
            "isSidechain": False,
            "message": {
                "id": "msg_1",
                "model": "claude-opus-5-5",
                "usage": {
                    "input_tokens": 10,
                    "cache_creation_input_tokens": 90,
                    "cache_read_input_tokens": 1000,
                    "output_tokens": 50,
                },
            },
        },
        {  # same message streamed in two lines: counted once
            "type": "assistant",
            "timestamp": now + ".200Z",
            "version": "2.1.300",
            "isSidechain": False,
            "message": {
                "id": "msg_1",
                "model": "claude-opus-5-5",
                "usage": {
                    "input_tokens": 10,
                    "cache_creation_input_tokens": 90,
                    "cache_read_input_tokens": 1000,
                    "output_tokens": 50,
                },
            },
        },
        {
            "type": "assistant",
            "timestamp": now + ".300Z",
            "version": "2.1.300",
            "isSidechain": False,
            "message": {
                "id": "msg_2",
                "model": "claude-opus-5-5",
                "usage": {"input_tokens": 5, "output_tokens": 20},
            },
        },
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.fixture
def session(config: Any, tmp_path: Path) -> Path:
    home: Path = config.home
    cwd = home.parent / "proj"
    transcript = tmp_path / "transcript.jsonl"
    _send(
        home,
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt_id": "p1",
            "prompt": f"Fix the failing billing test. My key is {SECRET}, don't leak it.",
        },
    )
    _pre_post(home, "t1", "Read", {"file_path": f"{cwd}/src/billing.py"})
    # edit that needed permission and was approved
    edit = {"file_path": f"{cwd}/src/billing.py", "old_string": "a", "new_string": "b"}
    _send(
        home,
        {
            "hook_event_name": "PreToolUse",
            "prompt_id": "p1",
            "tool_name": "Edit",
            "tool_input": edit,
            "tool_use_id": "t2",
        },
    )
    _send(
        home,
        {
            "hook_event_name": "PermissionRequest",
            "prompt_id": "p1",
            "tool_name": "Edit",
            "tool_input": edit,
        },
    )
    _send(
        home,
        {
            "hook_event_name": "PostToolUse",
            "prompt_id": "p1",
            "tool_name": "Edit",
            "tool_input": edit,
            "tool_use_id": "t2",
            "tool_response": {"ok": True},
        },
    )
    _pre_post(home, "t3", "Bash", {"command": "uv run pytest tests/test_billing.py"})
    # asked and denied by the user: PreToolUse + PermissionRequest, nothing after
    rm = {"command": "rm -rf build"}
    _send(
        home,
        {
            "hook_event_name": "PreToolUse",
            "prompt_id": "p1",
            "tool_name": "Bash",
            "tool_input": rm,
            "tool_use_id": "t4",
        },
    )
    _send(
        home,
        {
            "hook_event_name": "PermissionRequest",
            "prompt_id": "p1",
            "tool_name": "Bash",
            "tool_input": rm,
        },
    )
    # subagent
    task = {"subagent_type": "Explore", "description": "find other callers", "prompt": "search"}
    _send(
        home,
        {
            "hook_event_name": "PreToolUse",
            "prompt_id": "p1",
            "tool_name": "Task",
            "tool_input": task,
            "tool_use_id": "t5",
        },
    )
    _send(
        home,
        {
            "hook_event_name": "SubagentStart",
            "prompt_id": "p1",
            "agent_id": "a1",
            "agent_type": "Explore",
        },
    )
    _pre_post(home, "t6", "Grep", {"pattern": "due_date"}, agent_id="a1", agent_type="Explore")
    _send(
        home,
        {
            "hook_event_name": "SubagentStop",
            "prompt_id": "p1",
            "agent_id": "a1",
            "agent_type": "Explore",
            "agent_transcript_path": str(transcript),
        },
    )
    _send(
        home,
        {
            "hook_event_name": "PostToolUse",
            "prompt_id": "p1",
            "tool_name": "Task",
            "tool_input": task,
            "tool_use_id": "t5",
            "tool_response": {"ok": True},
        },
    )
    # auto mode denial
    push = {"command": "git push --force origin main"}
    _send(
        home,
        {
            "hook_event_name": "PreToolUse",
            "prompt_id": "p1",
            "tool_name": "Bash",
            "tool_input": push,
            "tool_use_id": "t7",
        },
    )
    _send(
        home,
        {
            "hook_event_name": "PermissionDenied",
            "prompt_id": "p1",
            "tool_name": "Bash",
            "tool_input": push,
        },
    )
    # interrupted by the user
    slow = {"command": "sleep 600"}
    _send(
        home,
        {
            "hook_event_name": "PreToolUse",
            "prompt_id": "p1",
            "tool_name": "Bash",
            "tool_input": slow,
            "tool_use_id": "t8",
        },
    )
    _send(
        home,
        {
            "hook_event_name": "PostToolUseFailure",
            "prompt_id": "p1",
            "tool_name": "Bash",
            "tool_input": slow,
            "tool_use_id": "t8",
            "error": "Interrupted",
            "is_interrupt": True,
        },
    )
    _transcript(transcript)
    _send(
        home,
        {
            "hook_event_name": "Stop",
            "prompt_id": "p1",
            "transcript_path": str(transcript),
            "last_assistant_message": "Done. I fixed it.",
        },
    )
    # a second prompt still in progress
    _send(
        home, {"hook_event_name": "UserPromptSubmit", "prompt_id": "p2", "prompt": "now refactor"}
    )
    _pre_post_p2 = {
        "hook_event_name": "PreToolUse",
        "prompt_id": "p2",
        "tool_name": "Read",
        "tool_input": {"file_path": f"{cwd}/a.py"},
        "tool_use_id": "t9",
    }
    _send(home, _pre_post_p2)
    return home


def _decisions(config: Any) -> list[DecisionTrace]:
    with Store.open(config) as s:
        return [r for r in s.records(newest_first=False) if isinstance(r, DecisionTrace)]


def test_drain_builds_parent_and_child(session: Path, config: Any) -> None:
    result = drain(session)
    assert result.added == 2
    assert result.kept == 2, "prompt p2 is still running and stays queued"
    child, parent = _decisions(config)
    assert parent.decision_kind == "code.edit"
    assert parent.capabilities is not None
    assert {"code.read", "code.edit", "code.test", "agent.delegate"} <= set(parent.capabilities)
    assert [lk.target_id for lk in parent.links or []] == [child.id]
    assert child.decision_kind == "code.search"
    assert child.actor_time.actor.id == "claude-code:Explore"
    assert child.intent.startswith("Explore subagent")


def test_actions_alternatives_and_human_path(session: Path, config: Any) -> None:
    drain(session)
    _, parent = _decisions(config)
    assert [a.call_id for a in parent.actions or []] == ["t1", "t2", "t3", "t5"]
    edit = next(a for a in parent.actions or [] if a.call_id == "t2")
    assert edit.type == "file_write" and edit.target == "src/billing.py"
    alts = {a.action.call_id: a for a in parent.alternatives or []}
    assert alts["t4"].rejected_by == "human" and alts["t4"].reason == "Permission denied"
    assert alts["t7"].rejected_by == "policy" and alts["t7"].policy_id == "permission:Bash"
    assert alts["t8"].reason == "Interrupted by user"
    kinds = [h.type for h in parent.human_path or []]
    assert kinds.count("approved") == 1 and kinds.count("rejected") == 2
    bash = next(p for p in parent.policies or [] if p.policy_id == "permission:Bash")
    assert bash.result == "fail" and "asked the user, denied" in (bash.detail or "")
    edit_policy = next(p for p in parent.policies or [] if p.policy_id == "permission:Edit")
    assert edit_policy.result == "pass" and "approved" in (edit_policy.detail or "")


def test_model_tokens_and_version_from_transcript(session: Path, config: Any) -> None:
    drain(session)
    _, parent = _decisions(config)
    at = parent.actor_time
    assert at.model is not None and at.model.name == "claude-opus-5-5"
    assert at.client is not None and at.client.version == "2.1.300"
    assert at.cost is not None
    assert at.cost.input_tokens == 105  # 10 + 90 (cache creation) + 5, msg_1 counted once
    assert at.cost.output_tokens == 70
    assert at.cost.cache_read_input_tokens == 1000


def test_completeness_every_executed_call_in_exactly_one_trace(session: Path, config: Any) -> None:
    """Full Design Thm 2: every executed tool call belongs to exactly one DecisionTrace."""
    executed = []
    for line in (session / "queue" / "sess-1.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event["hook_event_name"] == "PostToolUse" and event.get("prompt_id") == "p1":
            executed.append(event["tool_use_id"])
    drain(session)
    seen = [
        a.call_id
        for d in _decisions(config)
        for a in d.actions or []
        if a.status in (None, "executed")
    ]
    assert sorted(str(s) for s in seen) == sorted(executed)


def test_secret_and_reasoning_never_stored(session: Path, config: Any) -> None:
    drain(session)
    raw = b"".join(p.read_bytes() for p in config.home.rglob("*") if p.is_file())
    assert SECRET.encode() not in raw
    assert b"Done. I fixed it." not in raw, "assistant messages are not recorded"
    _, parent = _decisions(config)
    assert "[REDACTED:anthropic_key]" in parent.intent


def test_redrain_is_idempotent_and_second_prompt_lands_later(session: Path, config: Any) -> None:
    drain(session)
    assert drain(session).added == 0
    _send(
        session,
        {
            "hook_event_name": "PostToolUse",
            "prompt_id": "p2",
            "tool_name": "Read",
            "tool_input": {"file_path": "a.py"},
            "tool_use_id": "t9",
            "tool_response": {},
        },
    )
    _send(session, {"hook_event_name": "Stop", "prompt_id": "p2"})
    assert drain(session).added == 1
    assert len(_decisions(config)) == 3
    with Store.open(config) as s:
        assert s.verify().ok


def test_stale_turns_are_flushed(session: Path, config: Any) -> None:
    drain(session)
    result = drain(session, now=time.time() + 7200)
    assert result.added == 1 and result.kept == 0


def test_git_state_recorded(config: Any, tmp_path: Path) -> None:
    home: Path = config.home
    repo = home.parent / "proj"
    (repo / ".git" / "refs" / "heads").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / ".git" / "refs" / "heads" / "main").write_text("a" * 40 + "\n")
    _send(home, {"hook_event_name": "UserPromptSubmit", "prompt_id": "g1", "prompt": "commit it"})
    _pre_post_cmd = {
        "prompt_id": "g1",
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m fix"},
        "tool_use_id": "c1",
    }
    _send(home, {"hook_event_name": "PreToolUse", **_pre_post_cmd})
    _send(home, {"hook_event_name": "PostToolUse", "tool_response": {}, **_pre_post_cmd})
    (repo / ".git" / "refs" / "heads" / "main").write_text("b" * 40 + "\n")
    _send(home, {"hook_event_name": "Stop", "prompt_id": "g1"})
    drain(home)
    (decision,) = _decisions(config)
    assert decision.decision_kind == "code.commit"
    assert decision.context and decision.context.state_before
    assert decision.context.state_before.ref == "a" * 40
    assert decision.state_after and decision.state_after.ref == "b" * 40
    assert (decision.attributes or {}).get("decisiontrace.git_commit_created") is True
