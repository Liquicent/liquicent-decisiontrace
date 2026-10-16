"""Claude Code hook: record one event to the local queue, fast, and never interfere.

Run as ``python -I -S hook.py <package-parent-dir>``. Uses only the standard library plus
``decisiontrace.redact`` (itself stdlib-only), so start-up stays well under 50 ms.

Guarantees: always exits 0, never prints to stdout (stdout on UserPromptSubmit would become
model context), never returns a decision. Secrets and PII are redacted before anything
touches disk. Model reasoning and assistant messages are never recorded.
"""

from __future__ import annotations

import json
import os
import sys
import time

DRAIN_EVENTS = frozenset({"Stop", "StopFailure", "SessionEnd"})
GIT_EVENTS = frozenset({"UserPromptSubmit", "Stop", "StopFailure"})
KEEP = (
    "hook_event_name",
    "session_id",
    "prompt_id",
    "cwd",
    "permission_mode",
    "agent_id",
    "agent_type",
    "tool_name",
    "tool_use_id",
    "duration_ms",
    "is_interrupt",
    "notification_type",
    "reason",
    "source",
)
TRANSCRIPT_EVENTS = frozenset({"Stop", "StopFailure", "SubagentStop", "SessionEnd"})
TARGET_KEYS = ("file_path", "notebook_path", "path", "url", "pattern", "query")


def _home() -> str:
    return os.environ.get("DT_HOME") or os.path.join(os.path.expanduser("~"), ".decisiontrace")


def _settings(home: str) -> tuple[bytes, bool]:
    """(salt, store_bodies) read from config.toml without importing tomllib."""
    salt, bodies = b"decisiontrace", False
    try:
        with open(os.path.join(home, "config.toml"), encoding="utf-8") as fh:
            for line in fh:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.split("#")[0].strip().strip('"')
                if key == "salt" and value:
                    salt = value.encode()
                elif key == "bodies":
                    bodies = value.lower() == "true"
    except OSError:
        pass
    return salt, bodies


def _sha(text: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _clip(text: str, limit: int = 240) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def slim(event: dict, salt: bytes, store_bodies: bool) -> dict:  # type: ignore[type-arg]
    """Reduce a hook payload to the redacted fields DecisionTrace needs."""
    from decisiontrace.redact import Redactor

    red = Redactor(salt=salt)
    out = {k: event[k] for k in KEEP if k in event and event[k] is not None}
    out["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + f"#{time.time_ns()}"
    name = event.get("hook_event_name", "")
    if "cwd" in out:
        out["cwd"] = red.text(str(out["cwd"]))
    prompt = event.get("prompt")
    if isinstance(prompt, str):
        out["prompt_summary"] = red.text(_clip(prompt, 400))
        out["prompt_hash"] = _sha(prompt)
        if store_bodies:
            out["prompt_body"] = red.text(prompt)
    tool_input = event.get("tool_input")
    if isinstance(tool_input, dict):
        out["input_hash"] = _sha(json.dumps(tool_input, sort_keys=True, default=str))
        for key in TARGET_KEYS:
            if isinstance(tool_input.get(key), str):
                out["target"] = red.text(_clip(tool_input[key], 400))
                break
        if isinstance(tool_input.get("command"), str):
            out["command"] = red.text(_clip(tool_input["command"]))
        for key in ("subagent_type", "description"):
            if isinstance(tool_input.get(key), str):
                out[key] = red.text(_clip(tool_input[key], 200))
    if "tool_response" in event:
        out["response_hash"] = _sha(json.dumps(event["tool_response"], sort_keys=True, default=str))
    if isinstance(event.get("error"), str):
        out["error"] = red.text(_clip(event["error"], 300))
    if name in TRANSCRIPT_EVENTS:
        for key in ("transcript_path", "agent_transcript_path"):
            if isinstance(event.get(key), str):
                out[key] = event[key]
    if name in GIT_EVENTS and isinstance(event.get("cwd"), str):
        from decisiontrace.gitstate import head_commit

        commit = head_commit(event["cwd"])
        if commit:
            out["git_head"] = commit
    return out


def _spawn_drain(home: str) -> None:
    import subprocess

    subprocess.Popen(
        [sys.executable, "-I", "-m", "decisiontrace.adapters.claude_code.drain", home],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def run(raw: str, home: str | None = None, drain: bool = True) -> dict | None:  # type: ignore[type-arg]
    home = home or _home()
    if not os.path.exists(os.path.join(home, "traces.db")):
        return None  # not initialised: record nothing
    event = json.loads(raw)
    if not isinstance(event, dict):
        return None
    salt, bodies = _settings(home)
    entry = slim(event, salt, bodies)
    queue = os.path.join(home, "queue")
    os.makedirs(queue, mode=0o700, exist_ok=True)
    session = "".join(
        c for c in str(event.get("session_id", "unknown")) if c.isalnum() or c in "-_"
    )
    line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(
        os.path.join(queue, f"{session or 'unknown'}.jsonl"),
        os.O_WRONLY | os.O_APPEND | os.O_CREAT,
        0o600,
    )
    try:
        os.write(fd, line)
    finally:
        os.close(fd)
    if drain and event.get("hook_event_name") in DRAIN_EVENTS:
        _spawn_drain(home)
    return entry


def main() -> None:
    try:
        if len(sys.argv) > 1 and sys.argv[1] not in sys.path:
            sys.path.insert(0, sys.argv[1])
        run(sys.stdin.read())
    except Exception as exc:  # never let a recorder break Claude Code
        try:
            with open(os.path.join(_home(), "hook-errors.log"), "a", encoding="utf-8") as fh:
                fh.write(
                    f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {type(exc).__name__}\n"
                )
        except OSError:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
