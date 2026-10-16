"""Read the current git commit without spawning git (fast enough for hooks)."""

from __future__ import annotations

from pathlib import Path


def _git_dir(start: Path) -> Path | None:
    for d in (start, *start.parents):
        candidate = d / ".git"
        if candidate.is_dir():
            return candidate
        if candidate.is_file():  # worktree or submodule: "gitdir: <path>"
            text = candidate.read_text(encoding="utf-8").strip()
            if text.startswith("gitdir:"):
                target = Path(text[7:].strip())
                return target if target.is_absolute() else (d / target).resolve()
    return None


def head_commit(cwd: str | Path) -> str | None:
    """Full SHA of HEAD for the repository containing ``cwd``, or None."""
    try:
        git = _git_dir(Path(cwd).resolve())
        if git is None:
            return None
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head or None
        ref = head[4:].strip()
        common = git
        commondir = git / "commondir"
        if commondir.is_file():
            common = (git / commondir.read_text(encoding="utf-8").strip()).resolve()
        for base in (git, common):
            ref_file = base / ref
            if ref_file.is_file():
                return ref_file.read_text(encoding="utf-8").strip() or None
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line.endswith(" " + ref):
                    return line.split(" ", 1)[0]
    except OSError:
        return None
    return None
