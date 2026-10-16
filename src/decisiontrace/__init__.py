"""DecisionTrace: record why an AI-assisted decision was made, at the moment it is made."""

from importlib.metadata import PackageNotFoundError, version

from decisiontrace.model import (
    SCHEMA_VERSION,
    CorrectionRecord,
    DecisionTrace,
    OutcomeRecord,
    parse_record,
    to_json_dict,
)

try:
    __version__ = version("liquicent-decisiontrace")
except PackageNotFoundError:  # pragma: no cover - running from an unbuilt checkout
    __version__ = "0.0.0"

__all__ = [
    "SCHEMA_VERSION",
    "CorrectionRecord",
    "DecisionTrace",
    "OutcomeRecord",
    "__version__",
    "parse_record",
    "to_json_dict",
]
