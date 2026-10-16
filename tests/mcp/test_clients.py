from __future__ import annotations

import json
from pathlib import Path

import pytest

from decisiontrace.adapters.mcp.clients import config_path, install, snippet, uninstall


@pytest.fixture(autouse=True)
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))


@pytest.mark.parametrize("client", ["claude-desktop", "cursor"])
def test_install_merges_and_uninstall_restores(client: str) -> None:
    path = config_path(client)
    path.parent.mkdir(parents=True)
    existing = {"mcpServers": {"github": {"command": "gh-mcp"}}, "theme": "dark"}
    path.write_text(json.dumps(existing))
    install(client, Path("/custom/home"))
    data = json.loads(path.read_text())
    assert data["theme"] == "dark" and "github" in data["mcpServers"]
    entry = data["mcpServers"]["decisiontrace"]
    assert entry["args"] == ["-m", "decisiontrace", "mcp"]
    assert entry["env"] == {"DT_HOME": "/custom/home"}
    assert uninstall(client)[1] is True
    assert json.loads(path.read_text()) == existing


def test_snippets() -> None:
    assert snippet("claude-code").startswith("claude mcp add --scope user decisiontrace -- ")
    assert '"decisiontrace"' in snippet("cursor")
    with pytest.raises(ValueError):
        snippet("vim")
