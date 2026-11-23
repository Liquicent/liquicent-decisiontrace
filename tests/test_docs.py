"""Docs must not drift from the CLI, and the files they point at must exist."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import typer.main

from decisiontrace.cli import app
from tests.conftest import ROOT

RAW = "https://raw.githubusercontent.com/Liquicent/liquicent-decisiontrace/main/"


def test_every_command_is_in_the_cli_reference() -> None:
    text = (ROOT / "docs" / "cli.md").read_text()
    commands = typer.main.get_command(app).commands  # type: ignore[attr-defined]
    missing = [name for name in commands if f"`dt {name}`" not in text]
    assert not missing, f"add to docs/cli.md: {missing}"


def test_readme_links_exist() -> None:
    text = (ROOT / "README.md").read_text()
    for target in re.findall(r"\]\(((?:docs|schema)/[^)#]+)", text):
        assert (ROOT / target).exists(), target


def test_readme_logo_files_exist() -> None:
    # The README loads its logo by full address, because PyPI cannot follow relative paths.
    text = (ROOT / "README.md").read_text()
    targets = re.findall(re.escape(RAW) + r'([^"\s)]+)', text)
    assert targets, "the README should show the logo"
    for target in targets:
        assert (ROOT / target).exists(), target


def test_docs_site_logo_and_favicon_exist() -> None:
    text = (ROOT / "mkdocs.yml").read_text()
    for key in ("logo", "favicon"):
        found = re.search(rf"^  {key}: (\S+)$", text, flags=re.MULTILINE)
        assert found, f"mkdocs.yml theme has no {key}"
        assert (ROOT / "docs" / found.group(1)).exists(), found.group(1)


def test_logo_svgs_need_no_font_or_network() -> None:
    # GitHub and PyPI show these as plain images: text would need a font, and links are not followed.
    svgs = sorted((ROOT / "docs" / "assets").glob("*.svg"))
    assert svgs, "docs/assets should hold the logo"
    for path in svgs:
        root = ET.parse(path).getroot()
        tags = {element.tag.rsplit("}", 1)[-1] for element in root.iter()}
        assert root.get("viewBox"), path.name
        assert not tags & {"text", "image", "script", "style", "use", "foreignObject"}, path.name
