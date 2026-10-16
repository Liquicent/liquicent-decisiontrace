"""Move queued hook events into the store. Safe to run any time, from any process.

The hook spawns ``python -m decisiontrace.adapters.claude_code.drain <home>`` after each
turn; ``dt log`` and ``dt show`` also drain first. A lock keeps drains from overlapping,
decision ids are derived from the events (re-draining never duplicates), events of turns
still in progress go back to the queue, and anything that fails to build is kept in
``queue/failed/`` instead of being lost.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from decisiontrace.adapters.claude_code.builder import Group, build_all, group_events
from decisiontrace.config import load_config
from decisiontrace.store import Store

STALE_SECONDS = 3600


@dataclass
class DrainResult:
    added: int = 0
    events: int = 0
    kept: int = 0
    failed: int = 0
    skipped_locked: bool = False


class _Lock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fh: Any = None

    def acquire(self) -> bool:
        self.fh = self.path.open("a")
        try:
            import fcntl

            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:  # pragma: no cover - Windows: best effort, no lock
            return True
        except OSError:
            self.fh.close()
            return False
        return True

    def release(self) -> None:
        if self.fh:
            self.fh.close()


def _read(path: Path) -> list[dict[str, Any]]:
    events = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("ts"):
                events.append(event)
    return events


def _age_seconds(group: Group, now: float) -> float:
    newest = max(int(str(e["ts"]).split("#", 1)[1]) for e in group.events if "#" in str(e["ts"]))
    return now - newest / 1e9


def drain(home: Path, now: float | None = None) -> DrainResult:
    result = DrainResult()
    queue = home / "queue"
    if not queue.is_dir() or not (home / "traces.db").exists():
        return result
    lock = _Lock(queue / ".lock")
    if not lock.acquire():
        result.skipped_locked = True
        return result
    try:
        now = time.time() if now is None else now
        config = load_config(home)
        work = sorted(queue.glob("*.jsonl")) + sorted(queue.glob("*.draining"))
        with Store.open(config) as store:
            for path in work:
                taking = path
                if path.suffix == ".jsonl":
                    taking = path.with_suffix(".draining")
                    if taking.exists():  # left over from a crash: merge
                        with taking.open("a", encoding="utf-8") as out:
                            out.write(path.read_text(encoding="utf-8"))
                        path.unlink()
                    else:
                        os.replace(path, taking)
                elif not taking.exists():
                    continue
                _drain_file(store, taking, queue, now, config.namespace, result)
    finally:
        lock.release()
    return result


def _drain_file(
    store: Store, path: Path, queue: Path, now: float, namespace: str, result: DrainResult
) -> None:
    events = _read(path)
    result.events += len(events)
    groups = group_events(events)
    bundles: dict[tuple[str, str], list[Group]] = {}
    for g in groups:
        bundles.setdefault((g.session_id, g.prompt_key), []).append(g)
    ready: list[Group] = []
    keep: list[dict[str, Any]] = []
    for members in bundles.values():
        main = next((g for g in members if g.agent_id is None), None)
        done = (main is not None and main.closed) or all(
            _age_seconds(g, now) > STALE_SECONDS for g in members
        )
        if done:
            ready += members
        else:
            for g in members:
                keep += g.events
    try:
        records = build_all(ready, namespace=namespace)
        fresh = [r for r in records if not store.has(r["id"])]
        if fresh:
            store.append_many(fresh)
        result.added += len(fresh)
    except Exception as exc:
        failed = queue / "failed"
        failed.mkdir(exist_ok=True)
        os.replace(path, failed / f"{path.stem}.{int(now)}.jsonl")
        with (queue.parent / "hook-errors.log").open("a", encoding="utf-8") as fh:
            fh.write(f"drain failed: {type(exc).__name__}: {str(exc)[:300]}\n")
        result.failed += len(events)
        return
    if keep:
        original = path.with_suffix(".jsonl")
        lines = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in keep)
        fd = os.open(original, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, lines.encode("utf-8"))
        finally:
            os.close(fd)
        result.kept += len(keep)
    path.unlink()


def main() -> None:
    home = Path(sys.argv[1]) if len(sys.argv) > 1 else load_config().home
    try:
        drain(home)
    except Exception as exc:  # background process: log, never raise
        with (home / "hook-errors.log").open("a", encoding="utf-8") as fh:
            fh.write(f"drain crashed: {type(exc).__name__}\n")


if __name__ == "__main__":
    main()
