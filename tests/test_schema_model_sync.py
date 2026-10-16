"""The JSON Schema is canonical; the Pydantic models must not drift from it."""

from __future__ import annotations

import types
import typing
from typing import Any

import pytest
from pydantic import BaseModel

from decisiontrace import model as m
from decisiontrace.schema import load_schema

DEFS: dict[str, Any] = load_schema()["$defs"]

PAIRS: dict[str, type[BaseModel]] = {
    "Integrity": m.Integrity,
    "Actor": m.Actor,
    "Model": m.Model,
    "Cost": m.Cost,
    "StateRef": m.StateRef,
    "ContextItem": m.ContextItem,
    "Context": m.Context,
    "PolicyEvaluation": m.PolicyEvaluation,
    "PolicyException": m.PolicyException,
    "Action": m.Action,
    "Alternative": m.Alternative,
    "HumanEvent": m.HumanEvent,
    "ActorTime": m.ActorTime,
    "Outcome": m.Outcome,
    "Link": m.Link,
    "DecisionTrace": m.DecisionTrace,
    "OutcomeRecord": m.OutcomeRecord,
    "CorrectionRecord": m.CorrectionRecord,
}


def _objects() -> list[tuple[str, dict[str, Any], type[BaseModel]]]:
    out = [(name, DEFS[name], cls) for name, cls in PAIRS.items()]
    out.append(("ActorTime.client", DEFS["ActorTime"]["properties"]["client"], m.Client))
    return out


def _literals(annotation: Any) -> set[Any]:
    if typing.get_origin(annotation) is typing.Literal:
        return set(typing.get_args(annotation))
    found: set[Any] = set()
    if typing.get_origin(annotation) in (typing.Union, types.UnionType, typing.Annotated):
        for arg in typing.get_args(annotation):
            found |= _literals(arg)
    return found


def _enum(prop: dict[str, Any]) -> set[Any] | None:
    if "enum" in prop:
        return set(prop["enum"])
    if "const" in prop:
        return {prop["const"]}
    ref = prop.get("$ref", "")
    if ref.startswith("#/$defs/"):
        return _enum(DEFS[ref.removeprefix("#/$defs/")])
    return None


@pytest.mark.parametrize(
    ("name", "schema", "cls"), _objects(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_fields_match(name: str, schema: dict[str, Any], cls: type[BaseModel]) -> None:
    assert set(schema["properties"]) == set(cls.model_fields), name
    assert schema.get("additionalProperties") is False, f"{name} must forbid unknown fields"


@pytest.mark.parametrize(
    ("name", "schema", "cls"), _objects(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_required_match(name: str, schema: dict[str, Any], cls: type[BaseModel]) -> None:
    # record_type / schema_version are required in JSON but defaulted (fixed) in Python.
    fixed = {"record_type", "schema_version"}
    model_required = {k for k, f in cls.model_fields.items() if f.is_required()} | (
        fixed & set(cls.model_fields)
    )
    assert set(schema.get("required", [])) == model_required, name


@pytest.mark.parametrize(
    ("name", "schema", "cls"), _objects(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_enums_match(name: str, schema: dict[str, Any], cls: type[BaseModel]) -> None:
    for field, prop in schema["properties"].items():
        expected = _enum(prop)
        if expected is not None:
            assert _literals(cls.model_fields[field].annotation) == expected, f"{name}.{field}"


def test_schema_version_matches() -> None:
    assert load_schema()["x-schema-version"] == m.SCHEMA_VERSION
    assert DEFS["SchemaVersion"]["const"] == m.SCHEMA_VERSION
