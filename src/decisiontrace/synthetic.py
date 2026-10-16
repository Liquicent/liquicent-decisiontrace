"""Synthetic DecisionTraces for benchmarks, demos and tests."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from decisiontrace.ids import new_ulid

_KINDS = [
    ("refund.approve", "Refund ${n} for order {o}", "refund.max_auto_amount"),
    ("code.edit", "Fix bug {o} in billing module", "Edit(src/**)"),
    ("pr.merge", "Merge PR #{o}", "ci.required_checks"),
    ("procurement.approve", "Approve PO {o} for ${n}", "authority.procurement_agent"),
    ("email.draft", "Reply to customer about order {o}", "email.tone"),
]


def synthetic_decision(i: int, rng: random.Random, start: datetime | None = None) -> dict[str, Any]:
    kind, intent, policy = _KINDS[i % len(_KINDS)]
    when = (start or datetime(2026, 10, 1, tzinfo=UTC)) + timedelta(seconds=i * 7)
    amount = rng.randint(20, 5000)
    passed = amount < 500 or rng.random() < 0.7
    record: dict[str, Any] = {
        "record_type": "decision",
        "schema_version": "0.1.0",
        "id": new_ulid(int(when.timestamp() * 1000)),
        "namespace": "local",
        "decision_kind": kind,
        "intent": intent.format(n=amount, o=10_000 + i),
        "context": {
            "workflow": kind.split(".")[0],
            "inputs": [{"type": "ticket", "ref": f"ticket:{i}", "summary": f"Customer issue {i}"}],
        },
        "policies": [
            {"policy_id": policy, "result": "pass" if passed else "fail", "enforced": True}
        ],
        "actions": [{"type": "api_call", "name": f"{kind}.execute", "summary": f"Executed {i}"}],
        "actor_time": {
            "actor": {"type": "agent", "id": f"agent:{kind.split('.')[0]}"},
            "model": {"provider": "anthropic", "name": "claude-sonnet-5-5"},
            "started_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cost": {"usd": round(rng.random() / 10, 4), "input_tokens": rng.randint(500, 9000)},
        },
        "outcome": {"status": "accepted" if passed else "pending"},
    }
    if not passed:
        record["human_path"] = [
            {
                "type": "approved",
                "actor": {"type": "human", "id": "user:lead"},
                "at": (when + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ]
    return record


def synthetic_decisions(n: int, seed: int = 7) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    return [synthetic_decision(i, rng) for i in range(n)]
