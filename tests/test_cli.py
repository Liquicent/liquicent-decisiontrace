from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from decisiontrace.cli import app
from tests.conftest import EXAMPLES

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "validate" in result.output


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "schema 0.1.0" in result.output


def test_schema_path_exists() -> None:
    result = runner.invoke(app, ["schema"])
    assert Path(result.output.strip()).is_file()


def test_validate_examples() -> None:
    result = runner.invoke(app, ["validate", *map(str, EXAMPLES)])
    assert result.exit_code == 0, result.output
    assert f"{len(EXAMPLES)}/{len(EXAMPLES)} records valid" in result.output


def test_validate_jsonl_reports_bad_line(tmp_path: Path, refund_example: dict[str, Any]) -> None:
    bad = {**refund_example, "id": "nope"}
    path = tmp_path / "traces.jsonl"
    path.write_text(json.dumps(refund_example) + "\n\n" + json.dumps(bad) + "\n")
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 1
    assert "1/2 records valid" in result.output
    assert "traces.jsonl:3" in result.output
