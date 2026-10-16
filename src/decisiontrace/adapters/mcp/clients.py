"""MCP client configuration for Claude Desktop, Cursor and Claude Code."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

SERVER_NAME = "decisiontrace"
CLIENTS = ("claude-desktop", "cursor", "claude-code")


def server_entry(home: Path | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"command": sys.executable, "args": ["-m", "decisiontrace", "mcp"]}
    if home is not None:
        entry["env"] = {"DT_HOME": str(home)}
    return entry


def config_path(client: str) -> Path:
    if client == "claude-desktop":
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        elif sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return base / "Claude" / "claude_desktop_config.json"
    if client == "cursor":
        return Path.home() / ".cursor" / "mcp.json"
    if client == "claude-code":
        return Path.cwd() / ".mcp.json"
    raise ValueError(f"unknown MCP client {client!r}; choose from {', '.join(CLIENTS)}")


def snippet(client: str, home: Path | None = None) -> str:
    if client not in CLIENTS:
        raise ValueError(f"unknown MCP client {client!r}; choose from {', '.join(CLIENTS)}")
    entry = server_entry(home)
    if client == "claude-code":
        env = "".join(f" -e {k}={shlex.quote(v)}" for k, v in entry.get("env", {}).items())
        cmd = " ".join(shlex.quote(p) for p in [entry["command"], *entry["args"]])
        return f"claude mcp add --scope user{env} {SERVER_NAME} -- {cmd}"
    return json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2)


def install(client: str, home: Path | None = None) -> Path:
    """Merge our server into the client's config file, keeping everything else."""
    path = config_path(client)
    data: dict[str, Any] = {}
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        data = json.loads(text) if text else {}
        shutil.copy2(path, path.with_name(path.name + ".dt-backup"))
    data.setdefault("mcpServers", {})[SERVER_NAME] = server_entry(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".dt-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def uninstall(client: str) -> tuple[Path, bool]:
    path = config_path(client)
    if not path.exists():
        return path, False
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    servers = data.get("mcpServers") or {}
    if SERVER_NAME not in servers:
        return path, False
    del servers[SERVER_NAME]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path, True
