"""Golden-set evaluation for ``dt why`` (Phase 4 exit test: 8 of 10 correct).

A golden file is JSON Lines, one hand-checked case per line::

    {"target": "c1a90b2", "expect_id": "01M4ZEB9E0…", "must_mention": ["due_dates.py", "pytest"],
     "must_not_mention": ["refund"], "note": "timezone fix"}

``target`` is what you'd type after ``dt why`` (id, file or commit). A case passes when the
right decision is resolved and the explanation mentions every ``must_mention`` phrase and
none of the ``must_not_mention`` ones (case-insensitive).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from decisiontrace.model import DecisionTrace
from decisiontrace.recall.why import explain, resolve_target
from decisiontrace.store import Store, StoreError


@dataclass
class CaseResult:
    target: str
    passed: bool
    problems: list[str] = field(default_factory=list)


def evaluate(store: Store, cases: list[dict[str, Any]]) -> list[CaseResult]:
    results = []
    for case in cases:
        target = str(case["target"])
        problems: list[str] = []
        try:
            trace = resolve_target(store, target)
            text = explain(store, trace, precedents=0).lower()
        except StoreError as exc:
            results.append(CaseResult(target, False, [str(exc)]))
            continue
        expect = case.get("expect_id")
        if expect and not trace.id.startswith(str(expect).upper()):
            problems.append(f"resolved {trace.id[:10]}, expected {expect}")
        problems += [
            f"missing '{p}'" for p in case.get("must_mention", []) if p.lower() not in text
        ]
        problems += [
            f"should not mention '{p}'"
            for p in case.get("must_not_mention", [])
            if p.lower() in text
        ]
        results.append(CaseResult(target, not problems, problems))
    return results


def load(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def sample(store: Store, n: int = 20, seed: int | None = None) -> list[dict[str, Any]]:
    """Draft cases from real decisions; a human fills in must_mention after reading each."""
    decisions = [
        r for r in store.records(record_type="decision", limit=5000) if isinstance(r, DecisionTrace)
    ]
    rng = random.Random(seed)
    picked = rng.sample(decisions, min(n, len(decisions)))
    cases = []
    for t in picked:
        target = t.id[:10]
        if (
            t.state_after
            and t.state_after.type == "git.commit"
            and (t.attributes or {}).get("decisiontrace.git_commit_created")
        ):
            target = t.state_after.ref[:10]
        cases.append(
            {
                "target": target,
                "expect_id": t.id[:10],
                "must_mention": [],
                "must_not_mention": [],
                "note": t.intent[:80],
            }
        )
    return cases
