"""Verified work units: the record, its validation, its derived state and the CLI."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from decisiontrace.cli import app
from decisiontrace.ids import new_ulid
from decisiontrace.model import OutcomeRecord, parse_record, to_json_dict
from decisiontrace.schema import schema_errors
from decisiontrace.vwu import state_of, summary, units
from tests.conftest import ROOT, load

runner = CliRunner()
NOW = datetime.now(UTC).replace(microsecond=0)
PR_MERGE = ROOT / "schema" / "examples" / "03-pr-merge.json"
VWU_EXAMPLE = ROOT / "schema" / "examples" / "outcome-pr-merge-vwu.json"


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def unit_outcome(
    trace_id: str,
    at: datetime,
    status: str = "accepted",
    window_days: float = 7,
    **vwu: Any,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_type": "outcome",
        "schema_version": "0.1.0",
        "id": new_ulid(int(at.timestamp() * 1000)),
        "namespace": "local",
        "trace_id": trace_id,
        "status": status,
        "recorded_by": {"type": "human", "id": "user:meera"},
        "recorded_at": iso(at),
    }
    if status == "accepted" or vwu:
        record["vwu"] = {
            "unit": "code.change",
            "verification": {"method": "automated", "at": iso(at), "ref": "ci:run/77"},
            "reversal": {"window_ends_at": iso(at + timedelta(days=window_days))},
            **vwu,
        }
    return record


def plain_outcome(trace_id: str, at: datetime, status: str) -> dict[str, Any]:
    record = unit_outcome(trace_id, at, status)
    record.pop("vwu", None)
    return record


# -- the record --------------------------------------------------------------------------


def test_example_is_valid_and_round_trips() -> None:
    data = load(VWU_EXAMPLE)
    assert schema_errors(data) == []
    record = parse_record(data)
    assert isinstance(record, OutcomeRecord) and record.vwu is not None
    assert record.vwu.executor is not None and record.vwu.executor.org == "acme-dev-agency"
    assert to_json_dict(record) == data


def _both_reject(data: dict[str, Any], what: str = "") -> None:
    assert schema_errors(data), f"schema accepted it {what}"
    with pytest.raises(ValidationError):
        parse_record(data)


def test_only_an_accepted_outcome_carries_a_unit() -> None:
    data = load(VWU_EXAMPLE)
    data["status"] = "reverted"
    _both_reject(data)
    with pytest.raises(ValidationError, match="needs status 'accepted'"):
        parse_record(data)


@pytest.mark.parametrize(
    ("changes", "where"),
    [
        ({"quantity": 0}, "quantity"),
        ({"verification": {"method": "vibes", "at": "2026-10-16T12:00:00Z"}}, "method"),
        ({"surprise": True}, "unknown field"),
        ({"unit": "Not A Label"}, "unit"),
        ({"reversal": {"window_ends_at": "2026-10-23T12:00:00Z", "max_cost_usd": -1}}, "cost"),
    ],
)
def test_schema_and_model_reject_the_same_shapes(changes: dict[str, Any], where: str) -> None:
    data = load(VWU_EXAMPLE)
    data["vwu"].update(changes)
    _both_reject(data, where)


@pytest.mark.parametrize(
    ("quality", "words"),
    [
        ({"metric": "ci.coverage/v1", "threshold": 80, "value": 70}, "higher is better"),
        (
            {
                "metric": "support.reopen_rate/v1",
                "threshold": 0.05,
                "value": 0.08,
                "direction": "lower",
            },
            "lower is better",
        ),
    ],
)
def test_a_missed_threshold_is_not_a_unit(
    quality: dict[str, Any], words: str, tmp_path: Path
) -> None:
    data = load(VWU_EXAMPLE)
    data["vwu"]["quality"] = quality
    _rejected_by_model_and_dt_validate(data, words, tmp_path)


def test_a_met_threshold_in_either_direction_is_fine() -> None:
    data = load(VWU_EXAMPLE)
    data["vwu"]["quality"] = {
        "metric": "m/v1",
        "threshold": 0.05,
        "value": 0.02,
        "direction": "lower",
    }
    assert parse_record(data)
    data["vwu"]["quality"] = {"metric": "m/v1", "threshold": 80, "value": 80}
    assert parse_record(data)


def test_reversal_window_cannot_end_before_verification(tmp_path: Path) -> None:
    data = load(VWU_EXAMPLE)
    data["vwu"]["reversal"]["window_ends_at"] = "2026-10-15T00:00:00Z"
    _rejected_by_model_and_dt_validate(data, "before verification.at", tmp_path)


def test_measured_window_must_be_ordered(tmp_path: Path) -> None:
    data = load(VWU_EXAMPLE)
    data["vwu"]["measured"] = {
        "started_at": "2026-10-16T00:00:00Z",
        "ended_at": "2026-10-01T00:00:00Z",
    }
    _rejected_by_model_and_dt_validate(data, "before measured.started_at", tmp_path)


def _rejected_by_model_and_dt_validate(data: dict[str, Any], words: str, tmp_path: Path) -> None:
    """JSON Schema cannot compare two values, so these rules live in the reference
    implementation; ``dt validate`` checks both and must reject."""
    with pytest.raises(ValidationError, match=words):
        parse_record(data)
    path = tmp_path / "unit.json"
    path.write_text(json.dumps(data))
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 1 and "0/1 records valid" in result.output


def test_actor_org_and_version_are_optional() -> None:
    data = load(PR_MERGE)
    assert "org" not in json.dumps(data["actor_time"])
    data["actor_time"]["actor"] = {
        "type": "agent",
        "id": "agent:reviewer",
        "org": "acme-dev-agency",
        "version": "reviewer-2026.10+claude",
    }
    assert schema_errors(data) == []
    assert to_json_dict(parse_record(data)) == data


# -- derived state -------------------------------------------------------------------------


def _decision(store: Any, at: datetime) -> str:
    data = copy.deepcopy(load(PR_MERGE))
    data["id"] = new_ulid(int(at.timestamp() * 1000))
    data["actor_time"]["started_at"] = iso(at)
    data["actor_time"]["ended_at"] = iso(at + timedelta(minutes=5))
    store.append(data)
    return str(data["id"])


def test_states(store: Any) -> None:
    t0 = NOW - timedelta(days=10)
    provisional = _decision(store, t0)
    final = _decision(store, t0)
    reverted = _decision(store, t0)
    late_cancel = _decision(store, t0)
    complained = _decision(store, t0)
    store.append(unit_outcome(provisional, NOW - timedelta(days=1)))
    store.append(unit_outcome(final, NOW - timedelta(days=9)))
    store.append(unit_outcome(reverted, NOW - timedelta(days=3)))
    store.append(plain_outcome(reverted, NOW - timedelta(days=2), "reverted"))
    store.append(unit_outcome(late_cancel, NOW - timedelta(days=9), window_days=2))
    store.append(plain_outcome(late_cancel, NOW - timedelta(days=1), "failed"))
    store.append(unit_outcome(complained, NOW - timedelta(days=3)))
    store.append(plain_outcome(complained, NOW - timedelta(days=2), "complained"))
    got = {u.trace_id: u.state for u in units(store, now=NOW)}
    assert got == {
        provisional: "provisional",
        final: "final",
        reverted: "reverted",
        late_cancel: "final",
        complained: "provisional",
    }
    assert store.verify().ok


def test_units_resolve_the_executor_and_weigh_quantity(store: Any) -> None:
    t0 = NOW - timedelta(days=4)
    trace = _decision(store, t0)
    vendor = {"type": "agent", "id": "agent:fixer", "org": "acme-dev-agency", "version": "v3"}
    store.append(unit_outcome(trace, NOW - timedelta(days=3), quantity=3, executor=vendor))
    human = unit_outcome(trace, NOW - timedelta(days=2))
    human["vwu"]["verification"] = {
        "method": "human",
        "at": human["recorded_at"],
        "verifier": {"type": "human", "id": "user:meera"},
    }
    store.append(human)
    found = units(store, now=NOW)
    assert [u.executor.id if u.executor else None for u in found] == [
        "agent:fixer",
        "user:praveen",
    ]
    assert found[0].executor is not None and found[0].executor.org == "acme-dev-agency"
    s = summary(found)
    assert s["units"] == 4 and s["provisional"] == 4
    assert s["verified_without_a_person"] == pytest.approx(0.75)
    assert summary([])["verified_without_a_person"] == 0


def test_state_of_needs_a_unit(store: Any) -> None:
    trace = _decision(store, NOW - timedelta(days=1))
    plain = parse_record(plain_outcome(trace, NOW, "accepted"))
    assert isinstance(plain, OutcomeRecord)
    with pytest.raises(ValueError, match="no verified work unit"):
        state_of(plain, [], NOW)


# -- CLI -----------------------------------------------------------------------------------


def test_cli_round_trip(config: Any) -> None:
    from decisiontrace.store import Store

    home = ["--home", str(config.home)]
    with Store.open(config) as s:
        trace = _decision(s, NOW - timedelta(days=1))
    r = runner.invoke(
        app,
        [
            *home,
            "outcome",
            trace,
            "--accepted",
            "--vwu",
            "support.ticket",
            "--verified-by",
            "automated",
            "--reversal-days",
            "3",
            "--reversal-cost",
            "40",
            "--quantity",
            "2",
            "--quality-metric",
            "support.csat/v1",
            "--quality-threshold",
            "4",
            "--quality-value",
            "4.6",
            "--value-usd",
            "120",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "Verified work unit: support.ticket x2, verified by automated" in r.output
    r = runner.invoke(app, [*home, "vwu", "--json"])
    assert r.exit_code == 0, r.output
    (unit,) = json.loads(r.output)
    assert unit["unit"] == "support.ticket" and unit["quantity"] == 2
    assert unit["method"] == "automated" and unit["state"] == "provisional"
    assert unit["value_usd"] == 120 and unit["executor"]["id"] == "user:praveen"
    r = runner.invoke(app, [*home, "vwu"])
    assert "2 unit(s): 0 final, 2 provisional, 0 reverted" in r.output
    assert "Verified without a person: 100%" in r.output
    assert runner.invoke(app, [*home, "vwu", "--state", "final", "--json"]).output.strip() == "[]"
    r = runner.invoke(app, [*home, "show", trace])
    assert "verified work unit: support.ticket x2, automated" in r.output
    with Store.open(config) as s:
        assert s.verify().ok


@pytest.mark.parametrize(
    ("args", "words"),
    [
        (["--vwu", "code.change"], "--vwu needs --accepted"),
        (["--accepted", "--quality-metric", "m/v1"], "add --vwu"),
        (["--accepted", "--vwu", "code.change", "--verified-by", "vibes"], "--verified-by must be"),
        (
            ["--accepted", "--vwu", "code.change", "--quality-threshold", "3"],
            "need --quality-metric",
        ),
        (
            [
                *("--accepted", "--vwu", "code.change", "--quality-metric", "m/v1"),
                *("--quality-threshold", "80", "--quality-value", "70"),
            ],
            "misses the threshold",
        ),
        (["--accepted", "--vwu", "Code Change"], "string should match pattern"),
    ],
)
def test_cli_rejects_bad_units(config: Any, args: list[str], words: str) -> None:
    from decisiontrace.store import Store

    with Store.open(config) as s:
        trace = _decision(s, NOW - timedelta(days=1))
    r = runner.invoke(app, ["--home", str(config.home), "outcome", trace, *args])
    assert r.exit_code == 1
    assert words.lower() in r.output.lower()
    r = runner.invoke(app, ["--home", str(config.home), "vwu"])
    assert "No verified work units yet" in r.output
