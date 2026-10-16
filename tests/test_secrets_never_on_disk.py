"""Exit test: nothing secret ever reaches disk (DB file, WAL, or anything in the home dir)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from decisiontrace.store import Store
from decisiontrace.synthetic import synthetic_decisions

PLANTED = [
    "sk-ant-api03-PLANTEDsecretPLANTEDsecret00",
    "ghp_PLANTEDsecretPLANTEDsecretPLANTED0123",
    "AKIAPLANTEDSECRET123",
    "planted.person@example.com",
    "hunter2PLANTED",
    "9876543210",
    "ABCPE1234F",
]


def _all_bytes(home: Path) -> bytes:
    return b"".join(p.read_bytes() for p in home.rglob("*") if p.is_file())


def test_planted_secrets_never_written(config: Any) -> None:
    rec = synthetic_decisions(1)[0]
    rec["intent"] = f"Rotate {PLANTED[0]} and notify {PLANTED[3]}"
    rec["context"]["inputs"][0]["summary"] = f"token {PLANTED[1]}, aws {PLANTED[2]}"
    rec["actions"][0]["summary"] = f"password={PLANTED[4]} phone {PLANTED[5]} PAN {PLANTED[6]}"
    rec["actor_time"]["on_behalf_of"] = {"type": "human", "id": PLANTED[3]}
    with Store.open(config) as s:
        result = s.append(rec, bodies={"prompt": " ".join(PLANTED)})
        assert result.redactions >= 7
        # also check readable copies held by SQLite before checkpoint
        raw = _all_bytes(config.home)
        assert s.verify().ok
    raw += _all_bytes(config.home)
    for secret in PLANTED:
        assert secret.encode() not in raw, f"{secret} reached disk"
