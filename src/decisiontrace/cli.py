"""The ``dt`` command."""

from __future__ import annotations

import contextlib
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


def _embedder(config: Config) -> Any:
    from decisiontrace.recall.embeddings import get_embedder

    try:
        return get_embedder(config.home)
    except Exception as exc:  # optional dependency missing or model unavailable
        typer.echo(f"(embeddings unavailable: {exc}; using full-text search)", err=True)
        return None


@app.command()
def why(
    target: Annotated[str, typer.Argument(help="Decision id/prefix, file path, or git commit")],
    precedents: Annotated[int, typer.Option(help="How many similar decisions to list")] = 3,
) -> None:
    """Explain, in plain English, why a decision was made."""
    from decisiontrace.recall.why import explain, resolve_target

    with _open_store(drain_first=True) as store:
        try:
            trace = resolve_target(store, target, Path.cwd())
        except StoreError as exc:
            _fail(str(exc))
        typer.echo(explain(store, trace, precedents=precedents))


@app.command()
def similar(
    query: Annotated[str, typer.Argument(help="Decision id/prefix, or a description")],
    limit: Annotated[int, typer.Option("--limit", "-n")] = 5,
) -> None:
    """Rank past decisions by similarity, with the score breakdown (P, X, C, A, T, Δt)."""
    from decisiontrace.recall.precedent import search
    from decisiontrace.recall.precedent import similar as rank_similar

    with _open_store(drain_first=True) as store:
        embedder = _embedder(store.config)
        base = None
        with contextlib.suppress(StoreError):
            base = store.get(query)
        if isinstance(base, DecisionTrace):
            hits = rank_similar(store, base, limit=limit, embedder=embedder)
            typer.echo(f"Precedents for {short(base.id)}: {base.intent}")
        else:
            hits = search(store, query, limit=limit, embedder=embedder)
            typer.echo(f"Decisions matching: {query}")
        if not hits:
            typer.echo("  none found")
            return
        for h in hits:
            when = h.trace.actor_time.started_at.strftime("%Y-%m-%d")
            label = f"{h.strength} {h.score:.2f}" if h.components else f"{h.score:.2f}"
            typer.echo(f"  {when}  {short(h.trace.id)}  [{label}]  {h.trace.intent[:70]}")
            if h.components:
                c = h.components
                typer.echo(
                    f"      P {c['P']:.2f}  X {c['X']:.2f}  C {c['C']:.2f}  A {c['A']:.2f}"
                    f"  T {c['T']:.2f}  Δt {c['dt']:.2f}y"
                )


@app.command()
def ask(
    question: Annotated[
        str, typer.Argument(help="e.g. 'which refunds needed an exception last week?'")
    ],
    llm: Annotated[
        bool,
        typer.Option(
            "--llm", help="Have Claude write the answer (sends matching redacted records)"
        ),
    ] = False,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 10,
) -> None:
    """Ask a question about your decisions. Works offline; --llm uses Claude."""
    from decisiontrace.recall.ask import answer_llm, answer_offline

    with _open_store(drain_first=True) as store:
        if llm:
            try:
                typer.echo(answer_llm(store, question, limit))
                return
            except ImportError:
                _fail("--llm needs: pip install 'liquicent-decisiontrace[llm]'")
            except Exception as exc:  # no credentials, network, API error
                typer.echo(
                    f"(Claude unavailable: {type(exc).__name__}; answering offline)", err=True
                )
        typer.echo(answer_offline(store, question, limit))


@app.command()
def reindex() -> None:
    """Rebuild search indexes and compute missing embeddings (if enabled)."""
    from decisiontrace.recall.embeddings import embed_missing

    config = _config()
    with _open_store() as store:
        store._conn.execute("DELETE FROM meta WHERE key = 'index_version'")
    with _open_store() as store:  # reopening rebuilds the full-text and file/commit index
        embedder = _embedder(config)
        added = embed_missing(store, embedder) if embedder else 0
        typer.echo(
            f"Indexed {store.count()} records"
            + (f"; {added} new embeddings ({embedder.name})" if embedder else "")
        )


@app.command(name="eval")
def eval_golden(
    golden: Annotated[Path | None, typer.Argument(help="Golden set (.jsonl)")] = None,
    sample_n: Annotated[
        int, typer.Option("--sample", help="Draft a golden set from N real decisions instead")
    ] = 0,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Score `dt why` against a hand-checked golden set (or draft one with --sample)."""
    from decisiontrace.recall.golden import evaluate, load, sample

    with _open_store(drain_first=True) as store:
        if sample_n:
            cases = sample(store, sample_n)
            text = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)
            if output:
                output.write_text(text, encoding="utf-8")
                typer.echo(f"Drafted {len(cases)} cases in {output}; fill in must_mention by hand.")
            else:
                typer.echo(text, nl=False)
            return
        if golden is None:
            _fail("give a golden .jsonl file, or --sample N to draft one")
        results = evaluate(store, load(golden))
    passed = sum(r.passed for r in results)
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        typer.echo(f"{mark}  {r.target}" + ("" if r.passed else "  — " + "; ".join(r.problems)))
    score = passed / len(results) if results else 0.0
    typer.echo(f"\n{passed}/{len(results)} correct ({score:.0%}); target 80%")
    if score < 0.8:
        raise typer.Exit(code=1)


@app.command(name="ingest-otel")
def ingest_otel(
    port: Annotated[int, typer.Option(help="OTLP/HTTP port to listen on")] = 4318,
    host: Annotated[
        str, typer.Option(help="Interface (keep 127.0.0.1 unless you mean it)")
    ] = "127.0.0.1",
    file: Annotated[
        list[Path] | None, typer.Option("--file", "-f", help="Ingest OTLP JSON file(s) and exit")
    ] = None,
    settle: Annotated[
        float, typer.Option(help="Seconds a trace must be quiet before it's stored")
    ] = 2.0,
) -> None:
    """Receive OpenTelemetry GenAI spans (OTLP/HTTP) and store them as decisions."""
    import threading
    import time

    from decisiontrace.adapters.otel.ingest import (
        Buffer,
        decisions_from_spans,
        make_server,
        parse_otlp_json,
        store_decisions,
    )

    config = _config()
    if not config.db_path.exists():
        config = init_home(config.home)
    if file:
        spans = []
        for path in file:
            text = path.read_text(encoding="utf-8").strip()
            payloads = (
                [json.loads(line) for line in text.splitlines() if line.strip()]
                if path.suffix == ".jsonl"
                else [json.loads(text)]
            )
            for payload in payloads:
                spans += parse_otlp_json(payload)
        with Store.open(config) as store:
            added = store_decisions(store, decisions_from_spans(spans, config.namespace))
        typer.echo(f"{added} decisions from {len(spans)} spans")
        return
    buffer = Buffer(lambda: Store.open(config), config.namespace, settle)
    server = make_server(buffer, host, port)
    stop = threading.Event()

    def flusher() -> None:
        while not stop.is_set():
            time.sleep(0.5)
            try:
                if n := buffer.flush():
                    typer.echo(f"stored {n} decision(s)", err=True)
            except Exception as exc:
                typer.echo(f"flush failed: {exc}", err=True)

    threading.Thread(target=flusher, daemon=True).start()
    typer.echo(
        f"Listening for OTLP/HTTP on http://{host}:{port}/v1/traces  (Ctrl-C to stop)", err=True
    )
    typer.echo(
        "Point your exporter at it: OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318", err=True
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        buffer.flush(force=True)
        typer.echo(f"{buffer.added} decisions stored", err=True)


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


outcomes_app = typer.Typer(
    help="Fill in outcomes from signals that already exist.", no_args_is_help=True
)
app.add_typer(outcomes_app, name="outcomes")


@outcomes_app.command("detect")
def outcomes_detect(
    git: Annotated[
        list[Path] | None,
        typer.Option("--git", help="Git repository to read reverts and merges from (repeatable)"),
    ] = None,
    events: Annotated[
        list[Path] | None,
        typer.Option("--events", help="JSON Lines of business-system events (repeatable)"),
    ] = None,
    preset: Annotated[
        str, typer.Option(help="Event format: generic, stripe, zendesk, jira, github, pagerduty")
    ] = "generic",
    assume_accepted_after: Annotated[
        float | None,
        typer.Option(
            help="Opt-in: take a decision with no negative signal after N days as accepted"
        ),
    ] = None,
    settle_days: Annotated[
        float, typer.Option(help="Days a merged commit must survive to count as accepted")
    ] = 3.0,
    since: Annotated[
        str | None, typer.Option(help="Only decisions after this date (YYYY-MM-DD)")
    ] = None,
    no_chain: Annotated[
        bool, typer.Option("--no-chain", help="Skip signals inside the store itself")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be recorded; write nothing")
    ] = False,
) -> None:
    """Detect outcomes: overrides and reversals in the store, git reverts/merges, business events.

    Never overrides an outcome a person recorded; safe to run repeatedly (e.g. daily from cron).
    """
    from decisiontrace.outcomes import apply, plan
    from decisiontrace.outcomes import base as ob
    from decisiontrace.outcomes import chain as chain_mod
    from decisiontrace.outcomes import events as events_mod
    from decisiontrace.outcomes import git as git_mod
    from decisiontrace.outcomes import silence as silence_mod

    if preset not in events_mod.PRESETS:
        _fail(f"unknown preset {preset!r}: choose from {', '.join(events_mod.PRESETS)}")
    with _open_store(drain_first=True) as store:
        traces = ob.decisions(store, since)
        signals: list[ob.Signal] = []
        if not no_chain:
            signals += chain_mod.detect(traces)
        for repo in git or []:
            try:
                signals += git_mod.detect(traces, repo, settle_days=settle_days)
            except git_mod.GitError as exc:
                _fail(f"{repo}: {exc}")
        if events:
            evs, skipped = events_mod.read(events, preset)
            signals += events_mod.detect(traces, evs, preset)
            if skipped:
                typer.echo(
                    f"({skipped} event line(s) not understood by the {preset} preset were skipped)",
                    err=True,
                )
        if assume_accepted_after is not None:
            signals += silence_mod.detect(traces, assume_accepted_after)
        todo = plan(store, signals)
        for s in todo:
            typer.echo(f"{short(s.trace_id)}  {s.status:<11} {s.source:<16} {s.note[:90]}")
        if not todo:
            typer.echo("No new outcomes.")
            return
        if dry_run:
            typer.echo(f"\n{len(todo)} outcome(s) would be recorded (dry run).")
            return
        n = apply(store, todo)
        typer.echo(f"\nRecorded {n} outcome(s). Human-recorded outcomes were left as they are.")
