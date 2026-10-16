"""Record types for DecisionTrace, mirroring ``schema/decisiontrace.schema.json``.

A store holds three kinds of append-only record:

* :class:`DecisionTrace` -- a decision ``DT = <C, P, E, X, H, T, O>``
* :class:`OutcomeRecord` -- an outcome learned later, linked to a decision
* :class:`CorrectionRecord` -- a correction to a decision, linked to it

Records are immutable. Serialise with :func:`to_json_dict`, which omits unset optional
fields so that a record round-trips byte-for-byte through the JSON form.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

SCHEMA_VERSION: Final = "0.1.0"

Ulid = Annotated[str, StringConstraints(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")]
Label = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)*$", max_length=128)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Namespace = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")]
Text = Annotated[str, StringConstraints(max_length=2000)]
Ref = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=256)]

AttributeValue = str | bool | int | float | None

_ATTRIBUTE_KEY = r"^[a-z0-9_]+(\.[a-z0-9_]+)+$"
_CHANGE_PATH = r"^[a-z_]+(\[\d+\])?(\.[a-z_]+(\[\d+\])?)*$"

ActorType = Literal["human", "agent", "system"]
PolicyEngine = Literal[
    "cel", "opa", "cedar", "yaml", "claude_code_permissions", "authority_envelope", "custom"
]
PolicyResult = Literal["pass", "fail", "not_applicable", "error"]
ActionType = Literal[
    "tool_call", "api_call", "message", "file_write", "memory_write", "state_change", "other"
]
ActionStatus = Literal["proposed", "executed", "failed", "cancelled"]
RejectedBy = Literal["model", "human", "policy", "system"]
HumanEventType = Literal[
    "requested", "approved", "rejected", "edited", "escalated", "commented", "overrode"
]
OutcomeStatus = Literal[
    "pending", "accepted", "reverted", "overridden", "escalated", "failed", "complained", "other"
]
LinkType = Literal[
    "context", "precedent", "reversal", "exec", "delegation", "hand_off", "supersedes"
]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=False)


def _check_keys(value: dict[str, Any], pattern: str, what: str) -> dict[str, Any]:
    import re

    bad = [k for k in value if not re.fullmatch(pattern, k)]
    if bad:
        raise ValueError(f"invalid {what} key(s): {', '.join(sorted(bad))}")
    return value


class Integrity(_Record):
    prev_hash: Sha256
    hash: Sha256


class Actor(_Record):
    type: ActorType
    id: Name
    name: Annotated[str, StringConstraints(max_length=256)] | None = None
    role: Annotated[str, StringConstraints(max_length=128)] | None = None


class Model(_Record):
    provider: str
    name: str


class Cost(_Record):
    usd: Annotated[float, Field(ge=0)] | None = None
    input_tokens: Annotated[int, Field(ge=0)] | None = None
    output_tokens: Annotated[int, Field(ge=0)] | None = None
    cache_read_input_tokens: Annotated[int, Field(ge=0)] | None = None


class StateRef(_Record):
    type: Label
    ref: Ref
    hash: Sha256 | None = None


class ContextItem(_Record):
    type: Label
    ref: Ref
    summary: Text | None = None
    hash: Sha256 | None = None


class Context(_Record):
    """C -- the inputs the decision was made on."""

    workflow: Label | None = None
    inputs: list[ContextItem] | None = None
    state_before: StateRef | None = None


class PolicyEvaluation(_Record):
    """One rule evaluated for the decision (P). ``enforced`` absent means False."""

    policy_id: Name
    result: PolicyResult
    version: Annotated[str, StringConstraints(max_length=64)] | None = None
    hash: Sha256 | None = None
    engine: PolicyEngine | None = None
    enforced: bool | None = None
    detail: Text | None = None


class PolicyException(_Record):
    """E -- a rule overridden, and by whom."""

    policy_id: Name
    reason: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    granted_by: Actor
    at: AwareDatetime


class Action(_Record):
    """An action proposed or taken (a_t). ``status`` absent means executed."""

    type: ActionType
    name: Name
    call_id: Annotated[str, StringConstraints(max_length=256)] | None = None
    target: Annotated[str, StringConstraints(max_length=1024)] | None = None
    summary: Text | None = None
    parameters_hash: Sha256 | None = None
    status: ActionStatus | None = None


class Alternative(_Record):
    """X -- an option considered and not taken."""

    action: Action
    rejected_by: RejectedBy
    policy_id: Annotated[str, StringConstraints(max_length=256)] | None = None
    reason: Text | None = None


class HumanEvent(_Record):
    """H -- one step on the human path."""

    type: HumanEventType
    actor: Actor
    at: AwareDatetime
    latency_ms: Annotated[int, Field(ge=0)] | None = None
    detail: Text | None = None
    diff_hash: Sha256 | None = None


class Client(_Record):
    name: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    version: Annotated[str, StringConstraints(max_length=64)] | None = None


class ActorTime(_Record):
    """T -- who or what decided, when, with what, at what cost."""

    actor: Actor
    started_at: AwareDatetime
    on_behalf_of: Actor | None = None
    model: Model | None = None
    client: Client | None = None
    session_id: Annotated[str, StringConstraints(max_length=256)] | None = None
    ended_at: AwareDatetime | None = None
    cost: Cost | None = None


class Outcome(_Record):
    """O as known at record time. Later outcomes are :class:`OutcomeRecord`."""

    status: OutcomeStatus
    note: Text | None = None


class Link(_Record):
    type: LinkType
    target_id: Ulid
    note: Text | None = None


class DecisionTrace(_Record):
    record_type: Literal["decision"] = "decision"
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    id: Ulid
    namespace: Namespace
    decision_kind: Label
    intent: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    actor_time: ActorTime
    capabilities: list[Label] | None = None
    context: Context | None = None
    policies: list[PolicyEvaluation] | None = None
    exceptions: list[PolicyException] | None = None
    actions: list[Action] | None = None
    alternatives: list[Alternative] | None = None
    human_path: list[HumanEvent] | None = None
    outcome: Outcome | None = None
    state_after: StateRef | None = None
    links: list[Link] | None = None
    attributes: dict[str, AttributeValue] | None = None
    integrity: Integrity | None = None

    @field_validator("capabilities")
    @classmethod
    def _unique_capabilities(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("capabilities must be unique")
        return value

    @field_validator("attributes")
    @classmethod
    def _attribute_keys(
        cls, value: dict[str, AttributeValue] | None
    ) -> dict[str, AttributeValue] | None:
        return None if value is None else _check_keys(value, _ATTRIBUTE_KEY, "attribute")


class OutcomeRecord(_Record):
    record_type: Literal["outcome"] = "outcome"
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    id: Ulid
    namespace: Namespace
    trace_id: Ulid
    status: OutcomeStatus
    recorded_by: Actor
    recorded_at: AwareDatetime
    note: Text | None = None
    value_usd: float | None = None
    attributes: dict[str, AttributeValue] | None = None
    integrity: Integrity | None = None

    @field_validator("attributes")
    @classmethod
    def _attribute_keys(
        cls, value: dict[str, AttributeValue] | None
    ) -> dict[str, AttributeValue] | None:
        return None if value is None else _check_keys(value, _ATTRIBUTE_KEY, "attribute")


class CorrectionRecord(_Record):
    record_type: Literal["correction"] = "correction"
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    id: Ulid
    namespace: Namespace
    trace_id: Ulid
    changes: Annotated[dict[str, JsonValue], Field(min_length=1)]
    reason: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    corrected_by: Actor
    corrected_at: AwareDatetime
    integrity: Integrity | None = None

    @field_validator("changes")
    @classmethod
    def _change_paths(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return _check_keys(value, _CHANGE_PATH, "change path")


Record = Annotated[
    DecisionTrace | OutcomeRecord | CorrectionRecord, Field(discriminator="record_type")
]

_record_adapter: TypeAdapter[DecisionTrace | OutcomeRecord | CorrectionRecord] = TypeAdapter(Record)


def parse_record(data: Any) -> DecisionTrace | OutcomeRecord | CorrectionRecord:
    """Parse a JSON-compatible dict into the matching record type."""
    return _record_adapter.validate_python(data)


def to_json_dict(record: DecisionTrace | OutcomeRecord | CorrectionRecord) -> dict[str, Any]:
    """Serialise a record to its canonical JSON form (unset optional fields omitted)."""
    return record.model_dump(mode="json", exclude_none=True)
