"""Docs must not drift from the CLI."""

from __future__ import annotations

import typer.main

from decisiontrace.cli import app
from tests.conftest import ROOT


def test_every_command_is_in_the_cli_reference() -> None:
    text = (ROOT / "docs" / "cli.md").read_text()
    commands = typer.main.get_command(app).commands  # type: ignore[attr-defined]
    missing = [name for name in commands if f"`dt {name}`" not in text]
    assert not missing, f"add to docs/cli.md: {missing}"


def test_readme_links_exist() -> None:
    import re

    text = (ROOT / "README.md").read_text()
    for target in re.findall(r"\]\(((?:docs|schema)/[^)#]+)", text):
        assert (ROOT / target).exists(), target
