"""Access to the canonical JSON Schema and validation against it."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_FILENAME = "decisiontrace.schema.json"


def schema_path() -> Path:
    """Path to the schema: packaged copy in a wheel, repo copy in a source checkout."""
    packaged = resources.files("decisiontrace") / "_schema" / _FILENAME
    if packaged.is_file():
        return Path(str(packaged))
    return Path(__file__).resolve().parents[2] / "schema" / _FILENAME


@cache
def load_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(schema_path().read_text(encoding="utf-8"))
    return schema


@cache
def _validator() -> Draft202012Validator:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_errors(data: Any) -> list[str]:
    """Return human-readable schema violations for one record ([] if valid)."""
    errors = sorted(_validator().iter_errors(data), key=lambda e: list(e.absolute_path))
    out: list[str] = []
    for error in errors:
        # oneOf failures hide the useful detail; report the branch matching record_type.
        if error.validator == "oneOf" and isinstance(data, dict):
            branch = _branch_for(data.get("record_type"))
            if branch is not None:
                sub = Draft202012Validator({"$defs": load_schema()["$defs"], "$ref": branch})
                out.extend(_format(e) for e in sub.iter_errors(data))
                continue
        out.append(_format(error))
    return out


def _branch_for(record_type: object) -> str | None:
    return {
        "decision": "#/$defs/DecisionTrace",
        "outcome": "#/$defs/OutcomeRecord",
        "correction": "#/$defs/CorrectionRecord",
    }.get(record_type if isinstance(record_type, str) else "")


def _format(error: Any) -> str:
    where = "/".join(str(p) for p in error.absolute_path) or "(record)"
    return f"{where}: {error.message}"
