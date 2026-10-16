"""The ``dt`` command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from decisiontrace import __version__
from decisiontrace.model import parse_record
from decisiontrace.schema import schema_errors, schema_path

app = typer.Typer(
    help="DecisionTrace: record why your AI made a decision, and recall it later.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def version() -> None:
    """Show the package and schema versions."""
    from decisiontrace.model import SCHEMA_VERSION

    typer.echo(f"decisiontrace {__version__} (schema {SCHEMA_VERSION})")


@app.command()
def schema() -> None:
    """Print the path of the DecisionTrace JSON Schema."""
    typer.echo(str(schema_path()))


@app.command()
def validate(
    paths: Annotated[list[Path], typer.Argument(help=".json or .jsonl files of records")],
) -> None:
    """Check records against the schema and the Python models."""
    failures = 0
    count = 0
    for path in paths:
        for label, data in _read_records(path):
            count += 1
            problems = schema_errors(data)
            if not problems:
                try:
                    parse_record(data)
                except ValidationError as exc:
                    problems = [f"model: {e['msg']} at {e['loc']}" for e in exc.errors()]
            if problems:
                failures += 1
                typer.echo(f"FAIL {label}", err=True)
                for problem in problems:
                    typer.echo(f"  {problem}", err=True)
    typer.echo(f"{count - failures}/{count} records valid")
    if failures:
        raise typer.Exit(code=1)


def _read_records(path: Path) -> list[tuple[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [
            (f"{path}:{n}", json.loads(line))
            for n, line in enumerate(text.splitlines(), start=1)
            if line.strip()
        ]
    return [(str(path), json.loads(text))]
