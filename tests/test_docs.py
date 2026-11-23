"""Docs must not drift from the CLI, and the files they point at must exist."""

from __future__ import annotations

import importlib.metadata
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


def test_changelog_dates_the_installed_version() -> None:
    # A version that is out must not sit under "unreleased".
    version = importlib.metadata.version("liquicent-decisiontrace")
    text = (ROOT / "CHANGELOG.md").read_text()
    heading = rf"^## {re.escape(version)} — \d{{4}}-\d{{2}}-\d{{2}}$"
    assert re.search(heading, text, flags=re.MULTILINE), f"date {version} in CHANGELOG.md"


def test_docs_site_address_is_linked() -> None:
    # Without site_url the page-not-found page loses its styles and the sitemap is empty.
    found = re.search(r"^site_url: (\S+)$", (ROOT / "mkdocs.yml").read_text(), flags=re.MULTILINE)
    assert found, "mkdocs.yml has no site_url"
    address = found.group(1)
    assert address.endswith("/"), address
    for name in ("README.md", "pyproject.toml"):
        assert address in (ROOT / name).read_text(), f"{name} should link to {address}"


def test_code_of_conduct_names_a_contact() -> None:
    # A template left with its placeholder gives people nobody to write to.
    text = (ROOT / "CODE_OF_CONDUCT.md").read_text()
    assert "[INSERT" not in text, "fill in the contact method"
    assert re.search(r"responsible for enforcement at \S+@\S+\.\w+", text), "name a contact address"
    assert "](CODE_OF_CONDUCT.md)" in (ROOT / "CONTRIBUTING.md").read_text()
