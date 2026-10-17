"""Signals from git history: reverts (bad) and commits merged into the main branch (good).

A decision is tied to a commit when it created one (``state_after`` git.commit) or, failing
that, to the first commit within ``carry_days`` after it that touched the files it edited.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from decisiontrace.model import DecisionTrace
from decisiontrace.outcomes.base import Signal


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Commit:
    sha: str
    at: datetime
    subject: str
    body: str
    files: tuple[str, ...]


def _git(repo: Path, *args: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitError(str(e)) from e
    if r.returncode != 0:
        raise GitError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


def commits(repo: Path, since: datetime | None = None) -> list[Commit]:
    args = ["log", "--all", "--no-color", "--name-only", "--format=%x1e%H%x1f%ct%x1f%s%x1f%b%x1f"]
    if since:
        args.append(f"--since={int(since.timestamp())}")
    out = []
    for chunk in _git(repo, *args).split("\x1e"):
        if not chunk.strip():
            continue
        parts = chunk.split("\x1f")
        if len(parts) < 5:
            continue
        sha, ct, subject, body, rest = parts[0].strip(), parts[1], parts[2], parts[3], parts[4]
        files = tuple(line.strip() for line in rest.splitlines() if line.strip())
        out.append(Commit(sha, datetime.fromtimestamp(int(ct), UTC), subject, body, files))
    return out


def main_branch(repo: Path) -> str | None:
    for ref in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
        try:
            _git(repo, "rev-parse", "--verify", "--quiet", ref)
            return ref
        except GitError:
            continue
    return None


def _is_ancestor(repo: Path, sha: str, ref: str) -> bool:
    try:
        _git(repo, "merge-base", "--is-ancestor", sha, ref)
        return True
    except GitError:
        return False


def _rel(path: str, root: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            return str(p.resolve().relative_to(root.resolve()))
        except ValueError:
            return path
    return path


def detect(
    traces: list[DecisionTrace],
    repo: Path,
    now: datetime | None = None,
    settle_days: float = 3.0,
    carry_days: float = 3.0,
) -> list[Signal]:
    now = now or datetime.now(UTC)
    root = Path(_git(repo, "rev-parse", "--show-toplevel").strip())
    earliest = min((t.actor_time.started_at for t in traces), default=now) - timedelta(days=1)
    log = commits(root, earliest)
    by_prefix = {c.sha: c for c in log}
    reverted_by: dict[str, Commit] = {}
    for c in log:
        for line in (c.body + "\n" + c.subject).splitlines():
            if "This reverts commit" in line:
                sha = line.split("This reverts commit", 1)[1].strip().rstrip(".").strip()
                for full in by_prefix:
                    if sha and full.startswith(sha):
                        reverted_by[full] = c
    main = main_branch(root)
    out: list[Signal] = []
    chrono = sorted(log, key=lambda c: c.at)
    for t in traces:
        commit: Commit | None = None
        how = ""
        if t.state_after and t.state_after.type == "git.commit":
            ref = t.state_after.ref.lower()
            commit = next((c for s, c in by_prefix.items() if s.startswith(ref)), None)
            how = "created by the decision"
        if commit is None:
            files = {
                _rel(a.target, root) for a in t.actions or [] if a.type == "file_write" and a.target
            }
            if files:
                start = t.actor_time.started_at
                commit = next(
                    (
                        c
                        for c in chrono
                        if start <= c.at <= start + timedelta(days=carry_days)
                        and files & set(c.files)
                    ),
                    None,
                )
                how = "first commit touching its files"
        if commit is None:
            continue
        rev = reverted_by.get(commit.sha)
        if rev is not None:
            out.append(
                Signal(
                    t.id,
                    "reverted",
                    "git",
                    rev.at,
                    f"Commit {commit.sha[:8]} ({how}) was reverted by {rev.sha[:8]}: {rev.subject[:200]}",
                    f"git:{commit.sha}←{rev.sha}",
                )
            )
            continue
        if (
            main
            and now - commit.at >= timedelta(days=settle_days)
            and _is_ancestor(root, commit.sha, main)
        ):
            out.append(
                Signal(
                    t.id,
                    "accepted",
                    "git",
                    commit.at + timedelta(days=settle_days),
                    f"Commit {commit.sha[:8]} ({how}) is on {main} with no revert after {settle_days:g} days",
                    f"git:{commit.sha}@{main}",
                )
            )
    return out
