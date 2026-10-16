from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from decisiontrace.adapters.claude_code.install import (
    EVENTS,
    install,
    installed_scopes,
    settings_path,
    uninstall,
)
from decisiontrace.cli import app


@pytest.fixture(autouse=True)
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    return tmp_path / "home"


EXISTING = {
    "model": "opus",
    "permissions": {"allow": ["Bash(npm test:*)"]},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-linter"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "notify-me"}]}],
    },
}


def _write_existing(scope: str) -> Path:
    path = settings_path(scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(EXISTING))
    return path


def test_install_preserves_existing_settings() -> None:
    path = _write_existing("user")
    install("user")
    data = json.loads(path.read_text())
    assert data["model"] == "opus"
    assert data["permissions"] == EXISTING["permissions"]
    assert set(EVENTS) <= set(data["hooks"])
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "my-linter"
    ours = data["hooks"]["PreToolUse"][1]
    assert ours["matcher"] == "*"
    assert "-I -S" in ours["hooks"][0]["command"]
    assert "matcher" not in data["hooks"]["UserPromptSubmit"][0]
    assert path.with_name("settings.json.dt-backup").exists()


def test_install_is_idempotent() -> None:
    install("user")
    install("user")
    data = json.loads(settings_path("user").read_text())
    assert all(len(groups) == 1 for groups in data["hooks"].values())


def test_uninstall_removes_only_ours() -> None:
    path = _write_existing("project")
    install("project")
    _, removed = uninstall("project")
    assert removed == len(EVENTS)
    assert json.loads(path.read_text()) == EXISTING


def test_uninstall_on_clean_settings_is_harmless() -> None:
    path, removed = uninstall("local")
    assert removed == 0
    assert not path.exists()


def test_installed_scopes() -> None:
    install("local")
    assert installed_scopes() == ["local"]


def test_cli_install_and_uninstall(tmp_path: Path) -> None:
    runner = CliRunner()
    home = tmp_path / "dt"
    result = runner.invoke(
        app, ["--home", str(home), "install", "claude-code", "--scope", "project"]
    )
    assert result.exit_code == 0, result.output
    assert (home / "traces.db").exists(), "install initialises the store"
    assert installed_scopes() == ["project"]
    result = runner.invoke(
        app, ["--home", str(home), "uninstall", "claude-code", "--scope", "project"]
    )
    assert "Removed 11" in result.output
    assert runner.invoke(app, ["install", "cursor"]).exit_code == 1
