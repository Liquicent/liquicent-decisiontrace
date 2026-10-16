"""The ``dt`` command."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from pydantic import ValidationError

from decisiontrace import __version__
from decisiontrace.config import Config, default_home, init_home, load_config
from decisiontrace.ids import new_ulid
from decisiontrace.model import SCHEMA_VERSION, DecisionTrace, parse_record, to_json_dict
from decisiontrace.schema import schema_errors, schema_path
from decisiontrace.store import Store, StoreError
from decisiontrace.views import current_outcome, render_trace, short

app = typer.Typer(
    help="DecisionTrace: record why your AI made a decision, and recall it later.",
    no_args_is_help=True,
    add_completion=False,
)

HomeOption = Annotated[
    Path | None,
    typer.Option("--home", envvar="DT_HOME", help="Store directory [default: ~/.decisiontrace]"),
]


class _State:
    home: Path | None = None


state = _State()


@app.callback()
def main(home: HomeOption = None) -> None:
    state.home = home


def _config() -> Config:
    return load_config(state.home or default_home())


def _open_store(drain_first: bool = False) -> Store:
    config = _config()
    if not config.db_path.exists():
        typer.echo(f"No store at {config.home}. Run: dt init", err=True)
        raise typer.Exit(code=2)
    if drain_first:
        from decisiontrace.adapters.claude_code.drain import drain

        drain(config.home)
    return Store.open(config)


def _fail(message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Show the package and schema versions."""
    typer.echo(f"decisiontrace {__version__} (schema {SCHEMA_VERSION})")


@app.command()
def schema() -> None:
    """Print the path of the DecisionTrace JSON Schema."""
    typer.echo(str(schema_path()))


@app.command()
def init() -> None:
    """Create the local store (safe to run again)."""
    config = init_home(state.home or default_home())
    with Store.open(config) as store:
        count = store.count()
    typer.echo(f"DecisionTrace store ready at {config.db_path} ({count} records)")
    typer.echo(f"Config: {config.config_path}  (bodies stored: {str(config.store_bodies).lower()})")


@app.command()
def validate(
    paths: Annotated[list[Path], typer.Argument(help=".json or .jsonl files of records")],
) -> None:
    """Check records against the schema and the Python models (without storing them)."""
    failures = 0
    count = 0
    for path in paths:
        for label, data in _read_records(path):
            count += 1
            problems = _problems(data)
            if problems:
                failures += 1
                typer.echo(f"FAIL {label}", err=True)
                for problem in problems:
                    typer.echo(f"  {problem}", err=True)
    typer.echo(f"{count - failures}/{count} records valid")
    if failures:
        raise typer.Exit(code=1)


@app.command()
def append(
    paths: Annotated[list[Path], typer.Argument(help=".json or .jsonl files of records")],
) -> None:
    """Validate, redact and append records to the store (all or nothing)."""
    batch: list[dict[str, Any]] = []
    for path in paths:
        for label, data in _read_records(path):
            problems = _problems(data)
            if problems:
                _fail(f"{label}: {problems[0]}")
            batch.append(data)
    with _open_store() as store:
        try:
            results = store.append_many(batch)
        except StoreError as exc:
            _fail(str(exc))
    redacted = sum(r.redactions for r in results)
    note = f" ({redacted} values redacted)" if redacted else ""
    typer.echo(f"Appended {len(results)} records{note}")


@app.command()
def log(
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many decisions")] = 20,
    kind: Annotated[str | None, typer.Option(help="Filter by decision kind prefix")] = None,
    since: Annotated[str | None, typer.Option(help="Only after this date (YYYY-MM-DD)")] = None,
) -> None:
    """List recent decisions, newest first."""
    with _open_store(drain_first=True) as store:
        rows = list(
            store.records(record_type="decision", decision_kind=kind, since=since, limit=limit)
        )
        if not rows:
            typer.echo("No decisions recorded yet.")
            return
        for rec in rows:
            assert isinstance(rec, DecisionTrace)
            outcome = current_outcome(rec, store.related(rec.id))
            when = rec.actor_time.started_at.strftime("%Y-%m-%d %H:%M")
            intent = rec.intent if len(rec.intent) <= 60 else rec.intent[:59] + "…"
            typer.echo(f"{when}  {short(rec.id)}  {rec.decision_kind:<22} {intent}  [{outcome}]")


@app.command()
def show(
    record_id: Annotated[str, typer.Argument(help="Record id or unique prefix")],
    as_json: Annotated[bool, typer.Option("--json", help="Raw records as JSON")] = False,
) -> None:
    """Show one decision with its rules, exceptions, alternatives, approvals and outcome."""
    with _open_store(drain_first=True) as store:
        try:
            rec = store.get(record_id)
        except StoreError as exc:
            _fail(str(exc))
        if not isinstance(rec, DecisionTrace):
            rec = store.get(rec.trace_id)
        assert isinstance(rec, DecisionTrace)
        related = store.related(rec.id)
        if as_json:
            out = [to_json_dict(rec), *(to_json_dict(r) for r in related)]
            typer.echo(json.dumps(out, indent=2, ensure_ascii=False))
            return
        typer.echo(render_trace(rec, related, store.links_to(rec.id)))


@app.command()
def outcome(
    record_id: Annotated[str, typer.Argument(help="Decision id or unique prefix")],
    accepted: Annotated[bool, typer.Option("--accepted", help="It worked")] = False,
    reverted: Annotated[bool, typer.Option("--reverted", help="It was undone")] = False,
    overridden: Annotated[bool, typer.Option("--overridden", help="A human overrode it")] = False,
    escalated: Annotated[bool, typer.Option("--escalated", help="It had to go up a level")] = False,
    failed: Annotated[bool, typer.Option("--failed", help="It failed")] = False,
    complained: Annotated[bool, typer.Option("--complained", help="Someone complained")] = False,
    note: Annotated[str | None, typer.Option("--note", help="What happened")] = None,
    value_usd: Annotated[float | None, typer.Option(help="Money gained (+) or lost (-)")] = None,
    by: Annotated[str, typer.Option(help="Who is recording this")] = "user:local",
) -> None:
    """Record what happened after a decision (appended; the decision is never edited)."""
    flags = {
        "accepted": accepted,
        "reverted": reverted,
        "overridden": overridden,
        "escalated": escalated,
        "failed": failed,
        "complained": complained,
    }
    chosen = [k for k, v in flags.items() if v]
    if len(chosen) > 1:
        _fail("choose one outcome flag")
    status = chosen[0] if chosen else ("other" if note else None)
    if status is None:
        _fail("give an outcome flag (e.g. --accepted) or --note")
    with _open_store() as store:
        try:
            trace = store.get(record_id)
        except StoreError as exc:
            _fail(str(exc))
        if not isinstance(trace, DecisionTrace):
            _fail(f"{record_id} is not a decision")
        record: dict[str, Any] = {
            "record_type": "outcome",
            "schema_version": SCHEMA_VERSION,
            "id": new_ulid(),
            "namespace": trace.namespace,
            "trace_id": trace.id,
            "status": status,
            "recorded_by": {"type": "human", "id": by},
            "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if note:
            record["note"] = note
        if value_usd is not None:
            record["value_usd"] = value_usd
        store.append(record)
    typer.echo(f"Recorded outcome '{status}' for {short(trace.id)}: {trace.intent}")


@app.command()
def verify() -> None:
    """Recompute the hash chain and report any tampering."""
    with _open_store() as store:
        result = store.verify()
    if result.ok:
        typer.echo(f"OK: {result.count} records, chain intact")
        typer.echo(f"head {result.head}")
        return
    typer.echo(f"TAMPERED: {len(result.problems)} problem(s) in {result.count} records", err=True)
    for problem in result.problems[:50]:
        typer.echo(f"  {problem}", err=True)
    raise typer.Exit(code=1)


@app.command()
def export(
    jsonl: Annotated[
        bool, typer.Option("--jsonl", help="JSON Lines (the only format for now)")
    ] = True,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="File (default stdout)")
    ] = None,
) -> None:
    """Export every record, oldest first, with its hash-chain fields."""
    del jsonl
    with _open_store() as store:
        if output:
            with output.open("w", encoding="utf-8") as fh:
                n = store.export_jsonl(fh)
            typer.echo(f"Exported {n} records to {output}", err=True)
        else:
            store.export_jsonl(sys.stdout)


TARGETS = ("claude-code", "claude-desktop", "cursor")
MCP_TARGETS = ("claude-desktop", "cursor")
ScopeOption = Annotated[
    str, typer.Option("--scope", help="user (all projects), project, or local (not committed)")
]


@app.command()
def install(
    target: Annotated[str, typer.Argument(help="What to hook into: claude-code")],
    scope: ScopeOption = "user",
) -> None:
    """Start recording: claude-code (hooks), or claude-desktop / cursor (MCP server)."""
    if target not in TARGETS:
        _fail(f"unknown target {target!r}; choose from: {', '.join(TARGETS)}")
    config = init_home(state.home or default_home())
    Store.open(config).close()
    custom_home = config.home if config.home != default_home() else None
    if target in MCP_TARGETS:
        from decisiontrace.adapters.mcp.clients import install as mcp_install

        path = mcp_install(target, custom_home)
        typer.echo(f"DecisionTrace MCP server added to {path}")
        typer.echo("Restart the app; it will show tools record, recall and outcome.")
        return
    from decisiontrace.adapters.claude_code.install import install as do_install

    try:
        path = do_install(scope)
    except ValueError as exc:
        _fail(str(exc))
    typer.echo(f"Claude Code hooks installed in {path}")
    typer.echo(f"Decisions go to {config.db_path}. Remove with: dt uninstall claude-code")
    if config.home != default_home():
        typer.echo(f"Note: set DT_HOME={config.home} in the environment Claude Code runs in.")


@app.command()
def uninstall(
    target: Annotated[str, typer.Argument(help="What to unhook: claude-code")],
    scope: ScopeOption = "user",
) -> None:
    """Stop recording (recorded decisions are kept)."""
    if target not in TARGETS:
        _fail(f"unknown target {target!r}; choose from: {', '.join(TARGETS)}")
    if target in MCP_TARGETS:
        from decisiontrace.adapters.mcp.clients import uninstall as mcp_uninstall

        mcp_path, found = mcp_uninstall(target)
        typer.echo(
            f"Removed DecisionTrace from {mcp_path}" if found else f"Not configured in {mcp_path}"
        )
        return
    from decisiontrace.adapters.claude_code.install import uninstall as do_uninstall

    path, removed = do_uninstall(scope)
    if removed:
        typer.echo(f"Removed {removed} DecisionTrace hooks from {path}")
    else:
        typer.echo(f"No DecisionTrace hooks found in {path}")


@app.command()
def mcp(
    config_for: Annotated[
        str | None,
        typer.Option(
            "--config", help="Print setup for a client instead: claude-desktop, cursor, claude-code"
        ),
    ] = None,
) -> None:
    """Run the local MCP server (stdio), or print the snippet to configure a client."""
    if config_for:
        from decisiontrace.adapters.mcp.clients import snippet

        cfg = _config()
        try:
            typer.echo(snippet(config_for, cfg.home if cfg.home != default_home() else None))
        except ValueError as exc:
            _fail(str(exc))
        return
    from decisiontrace.mcp_server import main as serve

    serve()


@app.command()
def drain() -> None:
    """Move queued hook events into the store now (normally automatic)."""
    from decisiontrace.adapters.claude_code.drain import drain as do_drain

    config = _config()
    result = do_drain(config.home)
    if result.skipped_locked:
        typer.echo("Another drain is running.")
        return
    typer.echo(
        f"{result.added} decisions added from {result.events} events"
        + (f"; {result.kept} events wait for their turn to finish" if result.kept else "")
        + (f"; {result.failed} events kept in queue/failed" if result.failed else "")
    )


def _problems(data: Any) -> list[str]:
    problems = schema_errors(data)
    if not problems:
        try:
            parse_record(data)
        except ValidationError as exc:
            problems = [f"model: {e['msg']} at {e['loc']}" for e in exc.errors()]
    return problems


def _read_records(path: Path) -> list[tuple[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [
            (f"{path}:{n}", json.loads(line))
            for n, line in enumerate(text.splitlines(), start=1)
            if line.strip()
        ]
    data = json.loads(text)
    if isinstance(data, list):
        return [(f"{path}[{i}]", item) for i, item in enumerate(data)]
    return [(str(path), data)]
