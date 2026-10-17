from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from decisiontrace.cli import app
from decisiontrace.ids import new_ulid
from decisiontrace.model import OutcomeRecord
from decisiontrace.outcomes import apply, chain, events, git, plan, silence
from decisiontrace.outcomes.base import decisions
from decisiontrace.views import current_outcome

NOW = datetime.now(UTC).replace(microsecond=0)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def decision(
    at: datetime, actor: str = "agent:refunds", kind: str = "refund.approve", **parts: Any
) -> dict[str, Any]:
    atype = "human" if actor.startswith("user:") else "agent"
    return {
        "record_type": "decision",
        "schema_version": "0.1.0",
        "id": new_ulid(int(at.timestamp() * 1000)),
        "namespace": "local",
        "decision_kind": kind,
        "intent": parts.pop("intent", "Refund order"),
        "actor_time": {"actor": {"type": atype, "id": actor}, "started_at": iso(at)},
        **parts,
    }


def statuses(store: Any) -> dict[str, str]:
    return {t.id: current_outcome(t, store.related(t.id)) for t in decisions(store)}


def run(store: Any, signals: list[Any]) -> int:
    return apply(store, plan(store, signals))


def test_chain_signals(store: Any) -> None:
    t0 = NOW - timedelta(days=2)
    over = decision(
        t0,
        human_path=[
            {
                "type": "overrode",
                "actor": {"type": "human", "id": "user:meera", "name": "Meera"},
                "at": iso(t0 + timedelta(minutes=5)),
            }
        ],
    )
    failed = decision(
        t0, actions=[{"type": "api_call", "name": "stripe.refunds.create", "status": "failed"}]
    )
    first = decision(t0, context={"inputs": [{"type": "order", "ref": "shop:7731"}]})
    redo = decision(
        t0 + timedelta(hours=2),
        actor="user:meera",
        context={"inputs": [{"type": "order", "ref": "shop:7731"}]},
    )
    old = decision(t0)
    rev = decision(t0 + timedelta(hours=3), links=[{"type": "reversal", "target_id": old["id"]}])
    store.append_many([over, failed, first, redo, old, rev])
    assert run(store, chain.detect(decisions(store))) == 4
    got = statuses(store)
    assert got[over["id"]] == "overridden" and got[failed["id"]] == "failed"
    assert got[first["id"]] == "overridden" and got[old["id"]] == "reverted"
    assert run(store, chain.detect(decisions(store))) == 0  # idempotent


def test_human_outcome_always_wins(store: Any) -> None:
    d = decision(
        NOW - timedelta(days=1), actions=[{"type": "api_call", "name": "x", "status": "failed"}]
    )
    store.append(d)
    store.append(
        {
            "record_type": "outcome",
            "schema_version": "0.1.0",
            "id": new_ulid(),
            "namespace": "local",
            "trace_id": d["id"],
            "status": "accepted",
            "recorded_by": {"type": "human", "id": "user:meera"},
            "recorded_at": iso(NOW),
        }
    )
    assert run(store, chain.detect(decisions(store))) == 0
    assert statuses(store)[d["id"]] == "accepted"


def test_bad_news_replaces_assumed_good(store: Any) -> None:
    d = decision(
        NOW - timedelta(days=20),
        actions=[{"type": "api_call", "name": "stripe.refunds.create"}],
        context={"inputs": [{"type": "ticket", "ref": "zendesk:88412"}]},
    )
    store.append(d)
    assert run(store, silence.detect(decisions(store), 14)) == 1
    assert statuses(store)[d["id"]] == "accepted"
    ev = [events.Event(("zendesk:88412",), "complained", NOW - timedelta(days=1), "reopened")]
    assert run(store, events.detect(decisions(store), ev)) == 1
    assert statuses(store)[d["id"]] == "complained"
    assert run(store, silence.detect(decisions(store), 14)) == 0  # never back to accepted
    rec = [r for r in store.related(d["id"]) if isinstance(r, OutcomeRecord)][-1]
    assert (
        rec.recorded_by.type == "system"
        and rec.attributes
        and rec.attributes["decisiontrace.detector"] == "events:generic"
    )


def test_silence_needs_an_action_and_time(store: Any) -> None:
    acted = decision(NOW - timedelta(days=20), actions=[{"type": "api_call", "name": "x"}])
    thought = decision(NOW - timedelta(days=20))
    recent = decision(NOW - timedelta(days=2), actions=[{"type": "api_call", "name": "x"}])
    store.append_many([acted, thought, recent])
    sig = silence.detect(decisions(store), 14)
    assert [s.trace_id for s in sig] == [acted["id"]]


@pytest.mark.parametrize(
    ("preset", "payload", "ref", "status"),
    [
        (
            "generic",
            {"ref": "zendesk:88412", "event": "ticket.reopened", "at": "{at}"},
            "zendesk:88412",
            "complained",
        ),
        (
            "generic",
            {"ref": "88412", "status": "solved", "at": "{at}"},
            "zendesk:88412",
            "accepted",
        ),
        (
            "stripe",
            {
                "type": "charge.dispute.created",
                "created": "{ts}",
                "data": {"object": {"id": "dp_1", "charge": "ch_9001", "amount": 85000}},
            },
            "stripe:ch_9001",
            "complained",
        ),
        (
            "stripe",
            {
                "type": "refund.updated",
                "created": "{ts}",
                "data": {"object": {"id": "re_5555", "status": "failed"}},
            },
            "stripe:re_5555",
            "failed",
        ),
        (
            "zendesk",
            {
                "ticket": {
                    "id": 88412,
                    "status": "open",
                    "previous_status": "solved",
                    "updated_at": "{at}",
                }
            },
            "zendesk:88412",
            "complained",
        ),
        (
            "zendesk",
            {"ticket": {"id": 88412, "satisfaction_rating": {"score": "bad"}}, "time": "{at}"},
            "zendesk:88412",
            "complained",
        ),
        (
            "jira",
            {
                "issue": {"key": "OPS-1234"},
                "timestamp": "{ms}",
                "changelog": {"items": [{"field": "status", "toString": "Reopened"}]},
            },
            "jira:OPS-1234",
            "complained",
        ),
        (
            "github",
            {
                "action": "closed",
                "repository": {"full_name": "acme/app"},
                "pull_request": {
                    "number": 42,
                    "merged": False,
                    "closed_at": "{at}",
                    "head": {"sha": "abc123def"},
                },
            },
            "github:acme/app#42",
            "reverted",
        ),
        (
            "github",
            {
                "action": "closed",
                "repository": {"full_name": "acme/app"},
                "pull_request": {"number": 43, "merged": True, "merged_at": "{at}"},
            },
            "github:acme/app#43",
            "accepted",
        ),
        (
            "pagerduty",
            {
                "event": {
                    "event_type": "incident.triggered",
                    "occurred_at": "{at}",
                    "data": {"title": "Refund API down", "custom_details": {"ref": "shop:7731"}},
                }
            },
            "shop:7731",
            "failed",
        ),
    ],
)
def test_presets(
    store: Any, tmp_path: Path, preset: str, payload: dict[str, Any], ref: str, status: str
) -> None:
    d = decision(NOW - timedelta(days=3), context={"inputs": [{"type": "item", "ref": ref}]})
    store.append(d)
    at = NOW - timedelta(days=1)
    text = (
        json.dumps(payload)
        .replace('"{at}"', json.dumps(iso(at)))
        .replace('"{ts}"', str(int(at.timestamp())))
    )
    text = text.replace('"{ms}"', str(int(at.timestamp() * 1000)))
    f = tmp_path / "events.jsonl"
    f.write_text(text + "\n" + "not json\n")
    evs, skipped = events.read([f], preset)
    assert skipped == 1 and len(evs) == 1
    assert run(store, events.detect(decisions(store), evs, preset)) == 1
    assert statuses(store)[d["id"]] == status


def test_events_never_match_later_decisions(store: Any) -> None:
    d = decision(NOW, context={"inputs": [{"type": "ticket", "ref": "zendesk:88412"}]})
    store.append(d)
    ev = [events.Event(("zendesk:88412",), "complained", NOW - timedelta(days=1), "reopened")]
    assert events.detect(decisions(store), ev) == []


def test_status_words() -> None:
    assert (
        events.status_of("charge.dispute.created") is None
        or events.status_of("dispute") == "complained"
    )
    assert events.status_of("ticket.reopened") == "complained"
    assert events.status_of("Rolled-Back") == "reverted"
    assert events.status_of("hello") is None


def _git(repo: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
        "HOME": str(repo),
    }
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()


def test_git_reverts_and_merges(store: Any, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    start = NOW - timedelta(hours=1)
    (repo / "a.py").write_text("a = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "agent change A")
    sha_a = _git(repo, "rev-parse", "HEAD")
    (repo / "b.py").write_text("b = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "human commits B")
    _git(repo, "revert", "--no-edit", sha_a)
    made_commit = decision(
        start, kind="code.edit", state_after={"type": "git.commit", "ref": sha_a}
    )
    edited_b = decision(
        start,
        kind="code.edit",
        actions=[{"type": "file_write", "name": "Edit", "target": str(repo / "b.py")}],
    )
    no_git = decision(
        start,
        kind="code.edit",
        actions=[{"type": "file_write", "name": "Edit", "target": "elsewhere.py"}],
    )
    store.append_many([made_commit, edited_b, no_git])
    sig = git.detect(decisions(store), repo, settle_days=0)
    assert run(store, sig) == 2
    got = statuses(store)
    assert got[made_commit["id"]] == "reverted" and got[edited_b["id"]] == "accepted"
    assert got[no_git["id"]] == "-"
    assert git.detect(decisions(store), repo, settle_days=30) == [
        s for s in sig if s.status == "reverted"
    ]


def test_git_error_is_reported(store: Any, tmp_path: Path) -> None:
    with pytest.raises(git.GitError):
        git.detect([], tmp_path)


def test_cli(config: Any, tmp_path: Path) -> None:
    from decisiontrace.store import Store

    d = decision(
        NOW - timedelta(days=3),
        context={"inputs": [{"type": "ticket", "ref": "zendesk:88412"}]},
        actions=[{"type": "api_call", "name": "x"}],
    )
    with Store.open(config) as s:
        s.append(d)
    f = tmp_path / "ev.jsonl"
    f.write_text(
        json.dumps(
            {"ref": "zendesk:88412", "event": "reopened", "at": iso(NOW - timedelta(days=1))}
        )
        + "\n"
    )
    home = ["--home", str(config.home)]
    r = CliRunner().invoke(app, [*home, "outcomes", "detect", "--events", str(f), "--dry-run"])
    assert r.exit_code == 0 and "complained" in r.output and "dry run" in r.output
    r = CliRunner().invoke(app, [*home, "outcomes", "detect", "--events", str(f)])
    assert r.exit_code == 0 and "Recorded 1" in r.output
    r = CliRunner().invoke(app, [*home, "outcomes", "detect", "--events", str(f)])
    assert "No new outcomes" in r.output
    r = CliRunner().invoke(app, [*home, "outcomes", "detect", "--preset", "nope"])
    assert r.exit_code == 1
    with Store.open(config) as s:
        assert s.verify().ok


# -- verified work units (--vwu) ------------------------------------------------------------


def _units(store: Any) -> dict[str, Any]:
    from decisiontrace.vwu import units

    return {u.trace_id: u for u in units(store)}


def _git_repo_with_revert(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("a = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "agent change A")
    sha_a = _git(repo, "rev-parse", "HEAD")
    (repo / "b.py").write_text("b = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "human commits B")
    _git(repo, "revert", "--no-edit", sha_a)
    return repo, sha_a


def test_git_merges_become_units_reverts_do_not(store: Any, tmp_path: Path) -> None:
    repo, sha_a = _git_repo_with_revert(tmp_path)
    start = NOW - timedelta(hours=1)
    made_commit = decision(
        start, kind="code.edit", state_after={"type": "git.commit", "ref": sha_a}
    )
    edited_b = decision(
        start,
        kind="code.edit",
        actions=[{"type": "file_write", "name": "Edit", "target": str(repo / "b.py")}],
    )
    store.append_many([made_commit, edited_b])
    sig = git.detect(decisions(store), repo, settle_days=0)
    assert apply(store, plan(store, sig), vwu=True) == 2
    found = _units(store)
    assert set(found) == {edited_b["id"]}
    unit = found[edited_b["id"]]
    assert unit.unit == "code.change" and unit.method == "outcome_signal"
    assert unit.state == "final"  # git's settle window has already passed
    rec = next(r for r in store.related(edited_b["id"]) if isinstance(r, OutcomeRecord) and r.vwu)
    assert rec.vwu is not None and rec.vwu.verification.ref
    assert rec.vwu.verification.ref.startswith("git:")
    assert (
        apply(store, plan(store, git.detect(decisions(store), repo, settle_days=0)), vwu=True) == 0
    )
    assert store.verify().ok


def test_event_units_stay_provisional_until_their_window_ends(store: Any) -> None:
    d = decision(
        NOW - timedelta(days=3), context={"inputs": [{"type": "pr", "ref": "github:acme/app#43"}]}
    )
    store.append(d)
    merged = events.Event(("github:acme/app#43",), "accepted", NOW - timedelta(days=2), "PR merged")
    sig = events.detect(decisions(store), [merged], "github")
    assert apply(store, plan(store, sig), vwu=True, vwu_window_days=5) == 1
    unit = _units(store)[d["id"]]
    assert unit.unit == "github.pull_request" and unit.state == "provisional"
    assert unit.window_ends_at == merged.at + timedelta(days=5)
    rollback = events.Event(
        ("github:acme/app#43",), "reverted", NOW - timedelta(days=1), "rolled_back"
    )
    assert run(store, events.detect(decisions(store), [rollback])) == 1
    assert _units(store)[d["id"]].state == "reverted"
    assert run(store, events.detect(decisions(store), [merged, rollback], "github")) == 0


def test_generic_events_can_name_their_unit(tmp_path: Path) -> None:
    f = tmp_path / "ev.jsonl"
    lines = [
        {"ref": "shop:7731", "event": "delivered", "at": iso(NOW), "unit": "order.delivery"},
        {"ref": "shop:7732", "event": "delivered", "at": iso(NOW), "unit": "Not A Label"},
    ]
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    evs, skipped = events.read([f])
    assert skipped == 0
    assert [e.unit for e in evs] == ["order.delivery", None]


def test_assumptions_are_never_units(store: Any) -> None:
    d = decision(NOW - timedelta(days=20), actions=[{"type": "api_call", "name": "x"}])
    store.append(d)
    assert apply(store, plan(store, silence.detect(decisions(store), 14)), vwu=True) == 1
    assert statuses(store)[d["id"]] == "accepted"
    assert _units(store) == {}


def test_cli_vwu(config: Any, tmp_path: Path) -> None:
    from decisiontrace.store import Store

    d = decision(
        NOW - timedelta(days=3), context={"inputs": [{"type": "ticket", "ref": "zendesk:88412"}]}
    )
    with Store.open(config) as s:
        s.append(d)
    f = tmp_path / "ev.jsonl"
    f.write_text(
        json.dumps({"ref": "zendesk:88412", "event": "solved", "at": iso(NOW - timedelta(days=1))})
        + "\n"
    )
    home = ["--home", str(config.home)]
    base = [*home, "outcomes", "detect", "--events", str(f), "--preset", "generic"]
    r = CliRunner().invoke(app, [*base, "--vwu", "--dry-run"])
    assert r.exit_code == 0 and "[vwu work.item]" in r.output and "dry run" in r.output
    r = CliRunner().invoke(app, [*base, "--vwu", "--vwu-window-days", "2"])
    assert r.exit_code == 0 and "Recorded 1 outcome(s), 1 of them verified work units" in r.output
    r = CliRunner().invoke(app, [*base, "--vwu"])
    assert "No new outcomes" in r.output
    r = CliRunner().invoke(app, [*home, "vwu", "--json"])
    (unit,) = json.loads(r.output)
    assert unit["unit"] == "work.item" and unit["method"] == "outcome_signal"
    assert unit["state"] == "provisional"
