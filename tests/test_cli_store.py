from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from decisiontrace.cli import app
from tests.conftest import EXAMPLES

runner = CliRunner()


def dt(home: Path, *args: str) -> tuple[int, str]:
    result = runner.invoke(app, ["--home", str(home), *args])
    return result.exit_code, result.output


def seeded(tmp_path: Path) -> Path:
    home = tmp_path / "dt"
    assert dt(home, "init")[0] == 0
    code, out = dt(home, "append", *map(str, EXAMPLES))
    assert code == 0, out
    return home


def test_commands_need_init(tmp_path: Path) -> None:
    code, out = dt(tmp_path / "nothing", "log")
    assert code == 2
    assert "dt init" in out


def test_init_is_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "dt"
    assert dt(home, "init")[0] == 0
    config = (home / "config.toml").read_text()
    code, out = dt(home, "init")
    assert code == 0 and "0 records" in out
    assert (home / "config.toml").read_text() == config
    assert "bodies = false" in config


def test_log_and_show(tmp_path: Path) -> None:
    home = seeded(tmp_path)
    code, out = dt(home, "log")
    assert code == 0
    assert out.count("\n") == 10
    assert "[reverted]" in out  # outcome record applied to the code edit
    code, out = dt(home, "log", "--kind", "refund")
    assert out.count("\n") == 2
    code, out = dt(home, "show", "01M4ZCMB")
    assert code == 0
    for heading in (
        "Rules checked (P)",
        "Exceptions (E)",
        "Rejected options (X)",
        "Human path (H)",
    ):
        assert heading in out


def test_show_applies_corrections(tmp_path: Path) -> None:
    home = seeded(tmp_path)
    _, out = dt(home, "show", "01M4ZDRZ")
    assert "ci.required_checks: not_applicable" in out
    assert "Corrections applied" in out
    _, out = dt(home, "show", "01M4ZDRZ", "--json")
    records = json.loads(out)
    assert records[0]["policies"][0]["result"] == "pass", "stored record is unchanged"


def test_outcome(tmp_path: Path) -> None:
    home = seeded(tmp_path)
    code, out = dt(home, "outcome", "01M4ZCMB", "--accepted", "--note", "Customer happy")
    assert code == 0, out
    assert "[accepted]" in dt(home, "log", "--kind", "refund.approve")[1]
    assert dt(home, "outcome", "01M4ZCMB")[0] == 1
    assert dt(home, "outcome", "01M4ZCMB", "--accepted", "--reverted")[0] == 1


def test_verify_and_tamper(tmp_path: Path) -> None:
    home = seeded(tmp_path)
    code, out = dt(home, "verify")
    assert code == 0 and f"{len(EXAMPLES)} records, chain intact" in out
    conn = sqlite3.connect(home / "traces.db")
    conn.execute("DROP TRIGGER records_no_update")
    conn.execute("UPDATE records SET body = replace(body, '850', '85') WHERE seq = 1")
    conn.commit()
    conn.close()
    code, out = dt(home, "verify")
    assert code == 1
    assert "TAMPERED" in out


def test_export(tmp_path: Path) -> None:
    home = seeded(tmp_path)
    target = tmp_path / "out.jsonl"
    assert dt(home, "export", "-o", str(target))[0] == 0
    lines = target.read_text().splitlines()
    assert len(lines) == len(EXAMPLES)
    dt(tmp_path / "other", "init")
    _, out = dt(tmp_path / "other", "validate", str(target))
    assert f"{len(EXAMPLES)}/{len(EXAMPLES)} records valid" in out


def test_append_rejects_invalid_and_redacts(tmp_path: Path) -> None:
    home = tmp_path / "dt"
    dt(home, "init")
    record = json.loads(EXAMPLES[0].read_text())
    record["intent"] = "Refund for jane.doe@example.com"
    good = tmp_path / "good.json"
    good.write_text(json.dumps(record))
    code, out = dt(home, "append", str(good))
    assert code == 0 and "1 values redacted" in out
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**record, "id": "x"}))
    assert dt(home, "append", str(bad))[0] == 1
    assert dt(home, "append", str(good))[0] == 1, "duplicate id"
