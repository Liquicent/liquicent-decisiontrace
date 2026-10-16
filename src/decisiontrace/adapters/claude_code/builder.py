"""Turn queued Claude Code hook events into DecisionTraces.

One user prompt (``prompt_id``) is one decision: what was asked (C), what permission checks
ran (P), what was done (actions), what was proposed but not done (X), who approved what (H),
model, tokens and timing (T). A subagent's work inside that prompt is its own decision,
linked from the parent with a ``delegation`` edge.
"""

from __future__ import annotations

import getpass
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from decisiontrace.ids import stable_ulid
from decisiontrace.model import SCHEMA_VERSION

ADAPTER = "claude_code"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob", "LS"}
WEB_TOOLS = {"WebFetch", "WebSearch"}
DELEGATE_TOOLS = {"Task", "Agent"}
PLAN_TOOLS = {"TodoWrite", "TaskCreate", "TaskUpdate", "ExitPlanMode"}
MEMORY_FILE = re.compile(r"(^|/)(CLAUDE(\.local)?\.md|AGENTS\.md|\.claude/.+|memory/.+\.md)$")
TEST_CMD = re.compile(
    r"\b(pytest|npm (run )?test|pnpm test|yarn test|go test|cargo test|jest|vitest)\b"
)

# decision_kind is the highest-ranked capability present
KIND_RANK = [
    ("agent.memory", "harness.update"),
    ("code.release", "code.release"),
    ("code.commit", "code.commit"),
    ("code.edit", "code.edit"),
    ("agent.delegate", "research.delegate"),
    ("research.web", "research.web"),
    ("code.test", "code.test"),
    ("shell.exec", "shell.exec"),
    ("code.read", "code.search"),
    ("planning", "planning.update"),
]


def _ts(event: dict[str, Any]) -> str:
    return str(event["ts"]).split("#", 1)[0]


def _order(event: dict[str, Any]) -> int:
    raw = str(event.get("ts", ""))
    return int(raw.split("#", 1)[1]) if "#" in raw else 0


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def capability(event: dict[str, Any]) -> str:
    """Capability label for one tool call, inferred from what it did (never declared)."""
    tool = str(event.get("tool_name", ""))
    target = str(event.get("target", ""))
    command = str(event.get("command", ""))
    if tool in EDIT_TOOLS:
        return "agent.memory" if MEMORY_FILE.search(target) else "code.edit"
    if tool in READ_TOOLS:
        return "code.read"
    if tool in WEB_TOOLS:
        return "research.web"
    if tool in DELEGATE_TOOLS:
        return "agent.delegate"
    if tool in PLAN_TOOLS:
        return "planning"
    if tool == "Bash":
        if re.search(r"\bgit push\b", command):
            return "code.release"
        if re.search(r"\bgit commit\b", command):
            return "code.commit"
        if TEST_CMD.search(command):
            return "code.test"
        return "shell.exec"
    if tool.startswith("mcp__"):
        server = re.sub(r"[^a-z0-9_]", "_", tool.split("__")[1].lower()) or "server"
        return f"mcp.{server}"
    return "tool." + (re.sub(r"[^a-z0-9_]", "_", tool.lower()) or "unknown")


def _action_type(event: dict[str, Any], cap: str) -> str:
    if cap == "agent.memory":
        return "memory_write"
    if event.get("tool_name") in EDIT_TOOLS:
        return "file_write"
    if str(event.get("tool_name", "")).startswith("mcp__"):
        return "api_call"
    return "tool_call"


def _summary(event: dict[str, Any], cwd: str | None = None) -> str | None:
    tool = event.get("tool_name")
    if event.get("command"):
        return str(event["command"])
    if tool in DELEGATE_TOOLS:
        parts = [event.get("subagent_type"), event.get("description")]
        return " — ".join(str(p) for p in parts if p) or None
    target = _target(event, cwd)
    if target:
        return f"{tool} {target}"
    return None


def _target(event: dict[str, Any], cwd: str | None) -> str | None:
    target = event.get("target")
    if not isinstance(target, str):
        return None
    if cwd and target.startswith(cwd.rstrip("/") + "/"):
        return target[len(cwd.rstrip("/")) + 1 :]
    return target


@dataclass
class Usage:
    model: str | None = None
    version: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0


def read_usage(transcript: str | None, start: str, end: str, sidechain: bool = False) -> Usage:
    """Model, Claude Code version and token totals from the transcript between two times."""
    usage = Usage()
    if not transcript:
        return usage
    path = Path(transcript)
    if not path.is_file():
        return usage
    per_message: dict[str, dict[str, Any]] = {}
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if '"assistant"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant" or bool(entry.get("isSidechain")) != sidechain:
                    continue
                when = str(entry.get("timestamp", ""))[:19]
                if not (start[:19] <= when <= end[:19]):
                    continue
                message = entry.get("message") or {}
                usage.model = message.get("model") or usage.model
                usage.version = entry.get("version") or usage.version
                key = str(message.get("id") or entry.get("requestId") or entry.get("uuid"))
                if isinstance(message.get("usage"), dict):
                    per_message[key] = message["usage"]
    except OSError:
        return usage
    for u in per_message.values():
        usage.input_tokens += int(u.get("input_tokens") or 0) + int(
            u.get("cache_creation_input_tokens") or 0
        )
        usage.output_tokens += int(u.get("output_tokens") or 0)
        usage.cache_read_input_tokens += int(u.get("cache_read_input_tokens") or 0)
    return usage


@dataclass
class Group:
    """Events of one prompt, for the main agent or one subagent."""

    session_id: str
    prompt_key: str
    agent_id: str | None
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def closed(self) -> bool:
        names = {e.get("hook_event_name") for e in self.events}
        if self.agent_id:
            return "SubagentStop" in names
        return bool(names & {"Stop", "StopFailure", "SessionEnd"})


def group_events(events: Iterable[dict[str, Any]]) -> list[Group]:
    """Split events into per-prompt groups; subagent events get their own group."""
    groups: dict[tuple[str, str, str | None], Group] = {}
    current: dict[str, str] = {}
    counter: dict[str, int] = defaultdict(int)
    for event in sorted(events, key=_order):
        session = str(event.get("session_id", "unknown"))
        name = event.get("hook_event_name")
        if name == "UserPromptSubmit" or session not in current:
            counter[session] += 1
            current[session] = str(event.get("prompt_id") or f"n{counter[session]}:{_order(event)}")
        prompt_key = str(event.get("prompt_id") or current[session])
        if event.get("prompt_id"):
            current[session] = prompt_key
        agent = event.get("agent_id")
        key = (session, prompt_key, str(agent) if agent else None)
        group = groups.setdefault(key, Group(session, prompt_key, key[2]))
        group.events.append(event)
    return list(groups.values())


def decision_id(group: Group) -> str:
    first = group.events[0]
    seed = f"{ADAPTER}:{group.session_id}:{group.prompt_key}:{group.agent_id or 'main'}"
    return stable_ulid(_ms(_ts(first)), seed)


def build_decision(
    group: Group,
    parent_prompt: dict[str, Any] | None = None,
    children: list[tuple[str, str | None]] | None = None,
    namespace: str = "local",
    user: str | None = None,
) -> dict[str, Any]:
    """Build one DecisionTrace dict from a closed group."""
    events = sorted(group.events, key=_order)
    first, last = events[0], events[-1]
    prompt = next((e for e in events if e.get("hook_event_name") == "UserPromptSubmit"), None)
    prompt = prompt or parent_prompt
    cwd = next((e["cwd"] for e in events if e.get("cwd")), None)
    start, end = _ts(first), _ts(last)

    pre: dict[str, dict[str, Any]] = {}
    post: dict[str, dict[str, Any]] = {}
    failed: dict[str, dict[str, Any]] = {}
    asked: list[dict[str, Any]] = []
    auto_denied: list[dict[str, Any]] = []
    for e in events:
        name = e.get("hook_event_name")
        tid = e.get("tool_use_id")
        if name == "PreToolUse" and tid:
            pre[tid] = e
        elif name == "PostToolUse" and tid:
            post[tid] = e
        elif name == "PostToolUseFailure" and tid:
            failed[tid] = e
        elif name == "PermissionRequest":
            asked.append(e)
        elif name == "PermissionDenied":
            auto_denied.append(e)

    def was_asked(e: dict[str, Any]) -> dict[str, Any] | None:
        for req in asked:
            if req.get("tool_name") == e.get("tool_name") and req.get("input_hash") == e.get(
                "input_hash"
            ):
                return req
        return None

    def was_auto_denied(e: dict[str, Any]) -> bool:
        return any(
            d.get("tool_name") == e.get("tool_name")
            and (not d.get("input_hash") or d.get("input_hash") == e.get("input_hash"))
            for d in auto_denied
        )

    caps: list[str] = []
    actions: list[dict[str, Any]] = []
    alternatives: list[dict[str, Any]] = []
    human: list[dict[str, Any]] = []
    policy_outcomes: dict[str, set[str]] = defaultdict(set)
    inputs: list[dict[str, Any]] = []
    human_actor = {"type": "human", "id": f"user:{user or _user()}"}
    agent_actor = {
        "type": "agent",
        "id": f"claude-code:{group_agent_type(events) or 'main'}"
        if group.agent_id
        else "claude-code:main",
        "name": "Claude Code"
        if not group.agent_id
        else f"Claude Code {group_agent_type(events) or 'subagent'}",
    }

    call_ids = list(dict.fromkeys([*pre, *post, *failed]))
    for tid in call_ids:
        e = post.get(tid) or failed.get(tid) or pre[tid]
        base = {**pre.get(tid, {}), **e}
        cap = capability(base)
        action: dict[str, Any] = {
            "type": _action_type(base, cap),
            "name": str(base.get("tool_name") or "unknown")[:256],
            "call_id": tid,
        }
        target = _target(base, cwd)
        if target:
            action["target"] = target[:1024]
        summary = _summary(base, cwd)
        if summary:
            action["summary"] = summary[:2000]
        if base.get("input_hash"):
            action["parameters_hash"] = base["input_hash"]
        req = was_asked(base)
        tool = str(base.get("tool_name"))
        if tid in post:
            caps.append(cap)
            actions.append(action)
            policy_outcomes[tool].add("asked-approved" if req else "allowed")
            if req:
                human.append(_human("requested", agent_actor, req, f"Permission asked for {tool}"))
                human.append(_human("approved", human_actor, post[tid], None, latency_from=req))
            if cap == "code.read" and target:
                inputs.append({"type": "file", "ref": target[:1024]})
            elif cap == "research.web" and target:
                inputs.append({"type": "web", "ref": target[:1024]})
        elif tid in failed and not failed[tid].get("is_interrupt"):
            action["status"] = "failed"
            if failed[tid].get("error"):
                action["summary"] = (f"{summary} — " if summary else "") + str(failed[tid]["error"])
                action["summary"] = action["summary"][:2000]
            caps.append(cap)
            actions.append(action)
            policy_outcomes[tool].add("asked-approved" if req else "allowed")
        else:
            action["status"] = "cancelled"
            if tid in failed:  # interrupted by the user
                alternatives.append(
                    {"action": action, "rejected_by": "human", "reason": "Interrupted by user"}
                )
                human.append(_human("rejected", human_actor, failed[tid], "Interrupted"))
            elif was_auto_denied(base):
                policy_outcomes[tool].add("auto-denied")
                alternatives.append(
                    {
                        "action": action,
                        "rejected_by": "policy",
                        "policy_id": f"permission:{tool}",
                        "reason": "Denied by auto mode",
                    }
                )
            elif req:
                policy_outcomes[tool].add("asked-denied")
                alternatives.append(
                    {"action": action, "rejected_by": "human", "reason": "Permission denied"}
                )
                human.append(_human("requested", agent_actor, req, f"Permission asked for {tool}"))
                human.append(_human("rejected", human_actor, req, f"Denied {tool}"))
            else:
                policy_outcomes[tool].add("blocked")
                alternatives.append(
                    {"action": action, "rejected_by": "system", "reason": "Not executed"}
                )

    capabilities = list(dict.fromkeys(caps))
    kind = next((k for c, k in KIND_RANK if c in capabilities), None)
    if kind is None:
        kind = capabilities[0] if capabilities else "conversation.answer"

    mode = next((e.get("permission_mode") for e in events if e.get("permission_mode")), None)
    policies = [_policy(tool, outcomes, mode) for tool, outcomes in policy_outcomes.items()]

    record: dict[str, Any] = {
        "record_type": "decision",
        "schema_version": SCHEMA_VERSION,
        "id": decision_id(group),
        "namespace": namespace,
        "decision_kind": kind,
        "intent": _intent(prompt, group, events),
    }
    if capabilities:
        record["capabilities"] = capabilities
    context: dict[str, Any] = {"workflow": "claude_code.session"}
    prompt_item: dict[str, Any] | None = None
    if prompt and prompt.get("prompt_hash"):
        prompt_item = {
            "type": "user_prompt",
            "ref": f"claude-code:{group.session_id}:{group.prompt_key}"[:1024],
            "hash": prompt["prompt_hash"],
        }
        if prompt.get("prompt_summary"):
            prompt_item["summary"] = str(prompt["prompt_summary"])[:2000]
    context["inputs"] = ([prompt_item] if prompt_item else []) + _dedupe(inputs)
    if not context["inputs"]:
        del context["inputs"]
    head_before = next(
        (
            e.get("git_head")
            for e in events
            if e.get("hook_event_name") == "UserPromptSubmit" and e.get("git_head")
        ),
        None,
    )
    if head_before and not group.agent_id:
        context["state_before"] = {"type": "git.commit", "ref": head_before}
    record["context"] = context
    if policies:
        record["policies"] = policies
    if actions:
        record["actions"] = actions
    if alternatives:
        record["alternatives"] = alternatives
    if human:
        record["human_path"] = human

    transcript = next(
        (
            e.get("agent_transcript_path") if group.agent_id else e.get("transcript_path")
            for e in reversed(events)
            if e.get("agent_transcript_path" if group.agent_id else "transcript_path")
        ),
        None,
    )
    usage = read_usage(transcript, start, end, sidechain=False)
    actor_time: dict[str, Any] = {
        "actor": agent_actor,
        "on_behalf_of": human_actor,
        "session_id": group.session_id[:256],
        "started_at": start,
    }
    if end != start:
        actor_time["ended_at"] = end
    if usage.model:
        actor_time["model"] = {"provider": "anthropic", "name": usage.model}
    actor_time["client"] = {"name": "claude-code"}
    if usage.version:
        actor_time["client"]["version"] = str(usage.version)[:64]
    if usage.input_tokens or usage.output_tokens:
        actor_time["cost"] = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": usage.cache_read_input_tokens,
        }
    record["actor_time"] = actor_time

    head_after = next(
        (
            e.get("git_head")
            for e in reversed(events)
            if e.get("hook_event_name") in ("Stop", "StopFailure") and e.get("git_head")
        ),
        None,
    )
    attributes: dict[str, Any] = {"decisiontrace.adapter": ADAPTER}
    if head_after and not group.agent_id:
        record["state_after"] = {"type": "git.commit", "ref": head_after}
        if head_before and head_after != head_before:
            attributes["decisiontrace.git_commit_created"] = True
    if mode:
        attributes["claude_code.permission_mode"] = str(mode)
    if any(e.get("hook_event_name") == "StopFailure" for e in events):
        attributes["claude_code.stop_failure"] = True
    record["attributes"] = attributes

    if (
        any(a.get("type") in ("file_write", "memory_write") for a in actions)
        or "code.commit" in capabilities
    ):
        record["outcome"] = {"status": "pending"}
    links = [{"type": "delegation", "target_id": cid} for cid, _ in (children or [])]
    if links:
        record["links"] = links
    return record


def group_agent_type(events: list[dict[str, Any]]) -> str | None:
    for e in events:
        if e.get("agent_type"):
            return re.sub(r"[^A-Za-z0-9_.-]", "-", str(e["agent_type"]))[:64]
    return None


def _intent(prompt: dict[str, Any] | None, group: Group, events: list[dict[str, Any]]) -> str:
    if group.agent_id:
        desc = next((e.get("description") for e in events if e.get("description")), None)
        kind = group_agent_type(events) or "subagent"
        base = f"{kind} subagent" + (f": {desc}" if desc else "")
        return base[:500]
    if prompt and prompt.get("prompt_summary"):
        text = " ".join(str(prompt["prompt_summary"]).split())
        return (text[:497] + "…") if len(text) > 500 else text or "Claude Code turn"
    return "Claude Code turn"


def _human(
    kind: str,
    actor: dict[str, Any],
    event: dict[str, Any],
    detail: str | None,
    latency_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {"type": kind, "actor": actor, "at": _ts(event)}
    if detail:
        step["detail"] = detail[:2000]
    if latency_from is not None:
        step["latency_ms"] = max(0, (_order(event) - _order(latency_from)) // 1_000_000)
    return step


def _policy(tool: str, outcomes: set[str], mode: Any) -> dict[str, Any]:
    result = "fail" if outcomes & {"asked-denied", "auto-denied", "blocked"} else "pass"
    labels = {
        "allowed": "allowed without asking",
        "asked-approved": "asked the user, approved",
        "asked-denied": "asked the user, denied",
        "auto-denied": "denied by auto mode",
        "blocked": "not executed",
    }
    detail = "; ".join(labels[o] for o in sorted(outcomes))
    if mode:
        detail += f" (mode: {mode})"
    return {
        "policy_id": f"permission:{tool}"[:256],
        "engine": "claude_code_permissions",
        "result": result,
        "enforced": True,
        "detail": detail[:2000],
    }


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out = []
    for item in items:
        key = (item["type"], item["ref"])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _user() -> str:
    try:
        name = getpass.getuser()
    except Exception:  # pragma: no cover - no login name available
        name = "local"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", name) or "local"


def build_all(
    groups: list[Group], namespace: str = "local", user: str | None = None
) -> list[dict[str, Any]]:
    """Build decisions for closed groups: subagents first, then parents linking to them."""
    by_prompt: dict[tuple[str, str], list[Group]] = defaultdict(list)
    for g in groups:
        by_prompt[(g.session_id, g.prompt_key)].append(g)
    records: list[dict[str, Any]] = []
    for (_, _), members in by_prompt.items():
        main = next((g for g in members if g.agent_id is None), None)
        subs = [g for g in members if g.agent_id is not None]
        prompt_event = None
        if main:
            prompt_event = next(
                (e for e in main.events if e.get("hook_event_name") == "UserPromptSubmit"), None
            )
        children = []
        for sub in subs:
            rec = build_decision(sub, parent_prompt=prompt_event, namespace=namespace, user=user)
            records.append(rec)
            children.append((rec["id"], sub.agent_id))
        if main:
            records.append(build_decision(main, children=children, namespace=namespace, user=user))
    return records
