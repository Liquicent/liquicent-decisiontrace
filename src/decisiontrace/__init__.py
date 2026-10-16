"""DecisionTrace: record why an AI-assisted decision was made, at the moment it is made.

Exports are loaded lazily so that light entry points (the Claude Code hook) can import
``decisiontrace.redact`` without paying for pydantic or jsonschema at start-up.
"""

from __future__ import annotations

from importlib import import_module

TYPE_CHECKING = False
if TYPE_CHECKING:  # keep `typing` out of the hook's import path
    from typing import Any

    from decisiontrace.model import (
        SCHEMA_VERSION,
        CorrectionRecord,
        DecisionTrace,
        OutcomeRecord,
        parse_record,
        to_json_dict,
    )

_LAZY = {
    "SCHEMA_VERSION": "decisiontrace.model",
    "CorrectionRecord": "decisiontrace.model",
    "DecisionTrace": "decisiontrace.model",
    "OutcomeRecord": "decisiontrace.model",
    "parse_record": "decisiontrace.model",
    "to_json_dict": "decisiontrace.model",
}

__all__ = [
    "SCHEMA_VERSION",
    "CorrectionRecord",
    "DecisionTrace",
    "OutcomeRecord",
    "__version__",
    "parse_record",
    "to_json_dict",
]


def __getattr__(name: str) -> Any:
    if name == "__version__":
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("liquicent-decisiontrace")
        except PackageNotFoundError:  # pragma: no cover - unbuilt checkout
            return "0.0.0"
    if name in _LAZY:
        return getattr(import_module(_LAZY[name]), name)
    raise AttributeError(f"module 'decisiontrace' has no attribute {name!r}")
