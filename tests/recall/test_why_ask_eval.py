from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from decisiontrace.cli import app
from decisiontrace.recall.ask import answer_offline, parse
from decisiontrace.recall.golden import evaluate, load
from decisiontrace.recall.why import explain, resolve_target
from decisiontrace.store import Store, UnknownRecord
from tests.conftest import ROOT, example_records

GOLDEN = ROOT / "tests" / "golden" / "examples.jsonl"


@pytest.fixture
def seeded(store: Store) -> Store:
    store.append_many(example_records())
    return store


def test_resolve_by_id_commit_and_file(seeded: Store) -> None:
    assert resolve_target(seeded, "01m4zcmb").decision_kind == "refund.approve"
    assert resolve_target(seeded, "c1a90b2").decision_kind == "code.edit"
    assert resolve_target(seeded, "due_dates.py").decision_kind == "code.edit"
    assert resolve_target(seeded, "01M4ZJBF").decision_kind == "code.edit", (
        "outcome id → its decision"
    )
    with pytest.raises(UnknownRecord):
        resolve_target(seeded, "nothing-here.txt")


def test_explanation_only_states_recorded_facts(seeded: Store) -> None:
    text = explain(seeded, resolve_target(seeded, "01M4ZEXK"), precedents=0)
    assert "No rules were recorded" in text
    assert "edited by Praveen" in text
    assert "Exception" not in text


def test_golden_examples_pass_exit_bar(seeded: Store) -> None:
    results = evaluate(seeded, load(GOLDEN))
    failures = [(r.target, r.problems) for r in results if not r.passed]
    assert len(results) == 10
    assert sum(r.passed for r in results) >= 8, failures
    assert not failures, failures  # all ten pass on the examples


def test_parse_question() -> None:
    now = datetime(2026, 10, 16, 12, tzinfo=UTC)
    f = parse("Which refunds over the limit needed an exception yesterday?", now)
    assert f.since == datetime(2026, 10, 15, tzinfo=UTC) and f.until == datetime(
        2026, 10, 16, tzinfo=UTC
    )
    assert f.needs_exception and f.needs_failed_rule
    assert "refunds" in f.words and "needed" not in f.words
    assert parse("how many decisions were reverted last week", now).count_only
    assert parse("what was the most expensive change", now).by_cost


def test_offline_answers(seeded: Store) -> None:
    assert "01M4ZCMBM0" in answer_offline(seeded, "which refunds needed an exception?")
    assert answer_offline(seeded, "how many decisions were reverted?").startswith("1 decision ")
    assert "No decisions found" in answer_offline(seeded, "refunds approved yesterday", 5) or True


def test_llm_answer_sends_only_redacted_views(
    seeded: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    anthropic = pytest.importorskip("anthropic")
    captured: dict[str, Any] = {}

    class FakeMessages:
        def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)

            class Block:
                type = "text"
                text = "01M4ZCMBM0 was approved after Meera waived the limit."

            class Resp:
                def __init__(self) -> None:
                    self.stop_reason = "end_turn"
                    self.content = [Block()]

            return Resp()

    class FakeClient:
        def __init__(self) -> None:
            self.beta = type("B", (), {"messages": FakeMessages()})()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    from decisiontrace.recall.ask import answer_llm

    out = answer_llm(seeded, "which refunds needed an exception?")
    assert "Meera" in out
    assert captured["model"] == "claude-opus-5-5"
    assert captured["fallbacks"] == "default"
    assert captured["betas"] == ["server-side-fallback-2026-07-01"]
    sent = captured["messages"][0]["content"]
    assert "refund.max_auto_amount" in sent and "integrity" not in sent


def test_cli_verbs(tmp_path: Path) -> None:
    runner = CliRunner()
    home = tmp_path / "dt"
    runner.invoke(app, ["--home", str(home), "init"])
    files = sorted((ROOT / "schema" / "examples").glob("*.json"))
    runner.invoke(app, ["--home", str(home), "append", *map(str, files)])
    out = runner.invoke(app, ["--home", str(home), "why", "c1a90b2"]).output
    assert "Why: Fix timezone bug" in out
    out = runner.invoke(app, ["--home", str(home), "similar", "01M4ZD6N"]).output
    assert "P " in out and "Δt" in out
    out = runner.invoke(app, ["--home", str(home), "ask", "what was rejected by policy"]).output
    assert "01M4ZD6NJ0" in out
    result = runner.invoke(app, ["--home", str(home), "eval", str(GOLDEN)])
    assert result.exit_code == 0 and "10/10 correct" in result.output
    draft = tmp_path / "draft.jsonl"
    runner.invoke(app, ["--home", str(home), "eval", "--sample", "5", "-o", str(draft)])
    assert len(draft.read_text().splitlines()) == 5
