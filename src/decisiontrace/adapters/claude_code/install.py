"""Add or remove DecisionTrace hooks in Claude Code settings, leaving everything else alone."""

from __future__ import annotations

import json
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

import decisiontrace

MARKER = "decisiontrace/adapters/claude_code/hook.py"
TOOL_EVENTS = [
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "PermissionDenied",
]
OTHER_EVENTS = [
    "UserPromptSubmit",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "StopFailure",
    "SessionEnd",
]
EVENTS = TOOL_EVENTS + OTHER_EVENTS
TIMEOUT_SECONDS = 10


def settings_path(scope: str, project_dir: Path | None = None) -> Path:
    project = project_dir or Path.cwd()
    if scope == "user":
        return Path.home() / ".claude" / "settings.json"
    if scope == "project":
        return project / ".claude" / "settings.json"
    if scope == "local":
        return project / ".claude" / "settings.local.json"
    raise ValueError(f"unknown scope {scope!r} (user, project or local)")


def hook_command() -> str:
    """Absolute python + hook script, run isolated (-I) without site (-S) for speed."""
    package_dir = Path(decisiontrace.__file__).resolve().parent
    hook = package_dir / "adapters" / "claude_code" / "hook.py"
    return " ".join(
        shlex.quote(p) for p in (sys.executable, "-I", "-S", str(hook), str(package_dir.parent))
    )


def _is_ours(handler: Any) -> bool:
    return isinstance(handler, dict) and MARKER in str(handler.get("command", ""))


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    data = json.loads(text) if text else {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".dt-backup"))
    tmp = path.with_name(path.name + ".dt-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def remove_hooks(data: dict[str, Any]) -> int:
    """Strip our handlers from a settings dict in place; return how many were removed."""
    removed = 0
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            handlers = group.get("hooks", []) if isinstance(group, dict) else []
            kept = [h for h in handlers if not _is_ours(h)]
            removed += len(handlers) - len(kept)
            if kept:
                kept_groups.append({**group, "hooks": kept})
            elif not handlers:
                kept_groups.append(group)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not hooks:
        del data["hooks"]
    return removed


def install(scope: str = "user", project_dir: Path | None = None) -> Path:
    path = settings_path(scope, project_dir)
    data = _load(path)
    remove_hooks(data)  # idempotent: replace any previous install
    hooks = data.setdefault("hooks", {})
    command = hook_command()
    handler = {"type": "command", "command": command, "timeout": TIMEOUT_SECONDS}
    for event in EVENTS:
        group: dict[str, Any] = {"hooks": [dict(handler)]}
        if event in TOOL_EVENTS:
            group = {"matcher": "*", **group}
        hooks.setdefault(event, []).append(group)
    _write(path, data)
    return path


def uninstall(scope: str = "user", project_dir: Path | None = None) -> tuple[Path, int]:
    path = settings_path(scope, project_dir)
    data = _load(path)
    removed = remove_hooks(data)
    if removed:
        _write(path, data)
    return path, removed


def installed_scopes(project_dir: Path | None = None) -> list[str]:
    found = []
    for scope in ("user", "project", "local"):
        try:
            data = _load(settings_path(scope, project_dir))
        except (ValueError, json.JSONDecodeError):
            continue
        for groups in (data.get("hooks") or {}).values():
            if any(_is_ours(h) for g in groups if isinstance(g, dict) for h in g.get("hooks", [])):
                found.append(scope)
                break
    return found
