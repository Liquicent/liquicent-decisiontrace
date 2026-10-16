"""The hook must be fast, silent and harmless."""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import decisiontrace

HOOK = Path(decisiontrace.__file__).resolve().parent / "adapters" / "claude_code" / "hook.py"
PKG_PARENT = str(Path(decisiontrace.__file__).resolve().parent.parent)


def _run(home: Path, payload: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", "-S", str(HOOK), PKG_PARENT],
        input=payload,
        env={**os.environ, "DT_HOME": str(home)},
        capture_output=True,
        timeout=10,
    )


EVENT = json.dumps(
    {
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "prompt_id": "p",
        "cwd": "/tmp",
        "tool_name": "Bash",
        "tool_input": {"command": "export API_KEY=abcdef123456 && npm test"},
        "tool_use_id": "t",
    }
).encode()


def test_hook_latency_under_50ms(config: Any) -> None:
    _run(config.home, EVENT)  # warm the OS file cache
    times = []
    for _ in range(20):
        start = time.perf_counter()
        result = _run(config.home, EVENT)
        times.append((time.perf_counter() - start) * 1000)
        assert result.returncode == 0
    median = statistics.median(times)
    print(f"\nhook median {median:.1f} ms, max {max(times):.1f} ms")
    assert median < 50


def test_hook_is_silent_and_redacts(config: Any) -> None:
    result = _run(config.home, EVENT)
    assert result.returncode == 0 and result.stdout == b"" and result.stderr == b""
    queued = (config.home / "queue" / "s.jsonl").read_text()
    assert "abcdef123456" not in queued
    assert "[REDACTED:secret_assignment]" in queued


def test_hook_survives_garbage(config: Any) -> None:
    for payload in (b"", b"not json", b"[1,2,3]", b'{"hook_event_name": 5}'):
        result = _run(config.home, payload)
        assert result.returncode == 0
        assert result.stdout == b""


def test_hook_does_nothing_without_init(tmp_path: Path) -> None:
    result = _run(tmp_path / "missing", EVENT)
    assert result.returncode == 0
    assert not (tmp_path / "missing").exists()


def test_hook_does_not_import_heavy_modules(config: Any) -> None:
    code = (
        f"import sys; sys.path.insert(0, {PKG_PARENT!r}); "
        "import decisiontrace.adapters.claude_code.hook as h; "
        "heavy = ('pydantic', 'jsonschema', 'typer', 'sqlite3', 'typing'); "
        "print(sorted(m for m in heavy if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
