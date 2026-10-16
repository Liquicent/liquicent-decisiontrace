"""SQLite backend: append-only, hash-chained, redacted before write."""

from __future__ import annotations

import gc
import json
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from decisiontrace.config import Config, load_config
from decisiontrace.model import (
    CorrectionRecord,
    DecisionTrace,
    Integrity,
    OutcomeRecord,
    parse_record,
    to_json_dict,
)
from decisiontrace.recall.text import fts_query, index_text, refs_for
from decisiontrace.redact import Redactor
from decisiontrace.store.chain import GENESIS, canonical, link_hash
from decisiontrace.store.migrations import migrate

AnyRecord = DecisionTrace | OutcomeRecord | CorrectionRecord
INDEX_VERSION = "2"  # bump when index_text / refs_for change; triggers a rebuild on open


class StoreError(Exception):
    """Base class for store errors."""


class DuplicateRecord(StoreError):
    pass


class UnknownRecord(StoreError):
    pass


class AmbiguousId(StoreError):
    pass


@dataclass
class VerifyResult:
    ok: bool
    count: int
    head: str
    problems: list[str] = field(default_factory=list)


@dataclass
class AppendResult:
    record: AnyRecord
    redactions: int


def _occurred_at(data: dict[str, Any]) -> str:
    if data["record_type"] == "decision":
        return str(data["actor_time"]["started_at"])
    if data["record_type"] == "outcome":
        return str(data["recorded_at"])
    return str(data["corrected_at"])


class Store:
    """A local DecisionTrace store. Use as a context manager or call :meth:`close`."""

    def __init__(self, path: Path, config: Config | None = None) -> None:
        self.path = path
        self.config = config or load_config(path.parent)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, isolation_level=None, timeout=10.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        migrate(self._conn)
        self._ensure_index()

    @classmethod
    def open(cls, config: Config | None = None) -> Store:
        config = config or load_config()
        return cls(config.db_path, config)

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    # -- writing -------------------------------------------------------------------------

    def append(
        self, record: AnyRecord | dict[str, Any], bodies: dict[str, str] | None = None
    ) -> AppendResult:
        """Validate, redact, chain and write one record."""
        return self.append_many([record], [bodies] if bodies else None)[0]

    def append_many(
        self,
        records: Iterable[AnyRecord | dict[str, Any]],
        bodies: list[dict[str, str] | None] | None = None,
    ) -> list[AppendResult]:
        """Append records in one transaction (all or nothing)."""
        # Bulk appends allocate many short-lived dicts; the cyclic GC rescans everything held
        # in memory on each pass, which makes large batches quadratic. Nothing here is cyclic.
        gc_was_enabled = gc.isenabled()
        gc.disable()
        try:
            return self._append_many(records, bodies)
        finally:
            if gc_was_enabled:
                gc.enable()

    def _append_many(
        self,
        records: Iterable[AnyRecord | dict[str, Any]],
        bodies: list[dict[str, str] | None] | None,
    ) -> list[AppendResult]:
        prepared = [self._prepare(r) for r in records]
        results: list[AppendResult] = []
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            prev = self._head_hash()
            seen: set[str] = set()
            for i, (data, model, redactions) in enumerate(prepared):
                trace_id = data.get("trace_id")
                if trace_id and trace_id not in seen and not self._exists(trace_id):
                    raise UnknownRecord(f"{data['record_type']} refers to unknown trace {trace_id}")
                body = canonical(data)
                digest = link_hash(prev, body)
                try:
                    conn.execute(
                        "INSERT INTO records (id, record_type, namespace, trace_id, decision_kind,"
                        " intent, actor_id, occurred_at, body, prev_hash, hash, redactions)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            data["id"],
                            data["record_type"],
                            data["namespace"],
                            trace_id,
                            data.get("decision_kind"),
                            data.get("intent"),
                            (data.get("actor_time") or {}).get("actor", {}).get("id"),
                            _occurred_at(data),
                            body,
                            prev,
                            digest,
                            redactions,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise DuplicateRecord(f"record {data['id']} already exists") from exc
                if isinstance(model, DecisionTrace):
                    self._index(model)
                for link in data.get("links", []):
                    conn.execute(
                        "INSERT OR IGNORE INTO links VALUES (?,?,?)",
                        (data["id"], link["type"], link["target_id"]),
                    )
                if trace_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO links VALUES (?,?,?)",
                        (data["id"], data["record_type"], trace_id),
                    )
                if bodies and bodies[i] and self.config.store_bodies:
                    redactor = Redactor(salt=self.config.salt)
                    for name, content in bodies[i].items():  # type: ignore[union-attr]
                        conn.execute(
                            "INSERT OR REPLACE INTO bodies VALUES (?,?,?)",
                            (data["id"], name, redactor.text(content)),
                        )
                seen.add(data["id"])
                stored = model.model_copy(
                    update={"integrity": Integrity(prev_hash=prev, hash=digest)}
                )
                results.append(AppendResult(record=stored, redactions=redactions))
                prev = digest
            self._set_meta(conn, prev)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return results

    def _prepare(self, record: AnyRecord | dict[str, Any]) -> tuple[dict[str, Any], AnyRecord, int]:
        model = parse_record(record) if isinstance(record, dict) else record
        data = to_json_dict(model)
        data.pop("integrity", None)
        redactor = Redactor(salt=self.config.salt)
        redacted = redactor.record(data)
        if redactor.counts:
            model = parse_record(redacted)
            redacted = to_json_dict(model)
        elif model.integrity is not None:
            model = model.model_copy(update={"integrity": None})
        return redacted, model, sum(redactor.counts.values())

    def forget_bodies(self, record_id: str) -> int:
        """Erase stored bodies for a record. The record and the chain are untouched."""
        cur = self._conn.execute("DELETE FROM bodies WHERE record_id = ?", (record_id,))
        return cur.rowcount

    # -- reading -------------------------------------------------------------------------

    def get(self, id_or_prefix: str) -> AnyRecord:
        row = self._conn.execute(
            "SELECT body, prev_hash, hash FROM records WHERE id = ?",
            (self.resolve(id_or_prefix),),
        ).fetchone()
        return self._row_to_record(row)

    def resolve(self, id_or_prefix: str) -> str:
        """Full id for an id or unique prefix (case-insensitive)."""
        prefix = id_or_prefix.strip().upper()
        rows = self._conn.execute(
            "SELECT id FROM records WHERE id >= ? AND id < ? LIMIT 2",
            (prefix, prefix + "\U0010ffff"),
        ).fetchall()
        if not rows:
            raise UnknownRecord(f"no record matches {id_or_prefix!r}")
        if len(rows) > 1 and rows[0][0] != prefix:
            raise AmbiguousId(f"{id_or_prefix!r} matches more than one record")
        return str(rows[0][0])

    def records(
        self,
        record_type: str | None = None,
        decision_kind: str | None = None,
        since: str | None = None,
        limit: int | None = None,
        newest_first: bool = True,
    ) -> Iterator[AnyRecord]:
        where, args = [], []
        if record_type:
            where.append("record_type = ?")
            args.append(record_type)
        if decision_kind:
            where.append("(decision_kind = ? OR decision_kind LIKE ?)")
            args += [decision_kind, decision_kind + ".%"]
        if since:
            where.append("occurred_at >= ?")
            args.append(since)
        sql = "SELECT body, prev_hash, hash FROM records"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY seq {'DESC' if newest_first else 'ASC'}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        for row in self._conn.execute(sql, args):
            yield self._row_to_record(row)

    def related(self, trace_id: str) -> list[OutcomeRecord | CorrectionRecord]:
        """Outcomes and corrections recorded against a decision, oldest first."""
        rows = self._conn.execute(
            "SELECT body, prev_hash, hash FROM records WHERE trace_id = ? ORDER BY seq",
            (trace_id,),
        ).fetchall()
        out: list[OutcomeRecord | CorrectionRecord] = []
        for row in rows:
            rec = self._row_to_record(row)
            assert isinstance(rec, OutcomeRecord | CorrectionRecord)
            out.append(rec)
        return out

    def links_to(self, record_id: str) -> list[tuple[str, str]]:
        """(type, src_id) for every link pointing at a record."""
        rows = self._conn.execute(
            "SELECT type, src_id FROM links WHERE target_id = ? ORDER BY src_id", (record_id,)
        ).fetchall()
        return [(str(t), str(s)) for t, s in rows]

    def bodies(self, record_id: str) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT name, content FROM bodies WHERE record_id = ?", (record_id,)
        ).fetchall()
        return {str(n): str(c) for n, c in rows}

    def search(
        self, text: str, limit: int = 50, decision_kind: str | None = None
    ) -> list[tuple[DecisionTrace, float]]:
        """Decisions matching ``text`` with their BM25 rank (lower is better)."""
        query = fts_query(text)
        if query is None:
            return []
        sql = (
            "SELECT r.body, r.prev_hash, r.hash, bm25(search) AS rank FROM search"
            " JOIN records r ON r.id = search.record_id WHERE search MATCH ?"
        )
        args: list[Any] = [query]
        if decision_kind:
            sql += " AND (r.decision_kind = ? OR r.decision_kind LIKE ?)"
            args += [decision_kind, decision_kind + ".%"]
        sql += " ORDER BY rank LIMIT ?"
        args.append(limit)
        out = []
        for body, prev, digest, rank in self._conn.execute(sql, args):
            rec = self._row_to_record((body, prev, digest))
            assert isinstance(rec, DecisionTrace)
            out.append((rec, float(rank)))
        return out

    def _index(self, trace: DecisionTrace) -> None:
        self._conn.execute(
            "INSERT INTO search (record_id, text) VALUES (?, ?)", (trace.id, index_text(trace))
        )
        self._conn.executemany(
            "INSERT OR IGNORE INTO refs (record_id, kind, ref) VALUES (?,?,?)",
            [(trace.id, kind, ref) for kind, ref in refs_for(trace)],
        )

    def by_ref(self, kind: str, ref: str, prefix: bool = False) -> list[DecisionTrace]:
        """Decisions indexed under a file path or commit, newest first."""
        op, value = ("LIKE", ref.lower() + "%") if prefix else ("=", ref)
        rows = self._conn.execute(
            "SELECT r.body, r.prev_hash, r.hash FROM refs f JOIN records r ON r.id = f.record_id"
            f" WHERE f.kind = ? AND f.ref {op} ? ORDER BY r.seq DESC",
            (kind, value),
        ).fetchall()
        out = []
        for row in rows:
            rec = self._row_to_record(row)
            assert isinstance(rec, DecisionTrace)
            out.append(rec)
        return out

    def file_refs_like(self, suffix: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT ref FROM refs WHERE kind IN ('file', 'file_read') AND"
            " (ref = ? OR ref LIKE ?) LIMIT 20",
            (suffix, "%/" + suffix),
        ).fetchall()
        return [str(r[0]) for r in rows]

    def set_embeddings(self, model: str, items: list[tuple[str, list[float]]]) -> None:
        """Store vectors (derived data, outside the hash chain) in one transaction."""
        import array

        rows = [(rid, model, len(v), array.array("f", v).tobytes()) for rid, v in items]
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.executemany("INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?)", rows)
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise

    def _vec_loaded(self) -> bool:
        if not hasattr(self, "_vec"):
            self._vec = False
            try:
                import sqlite_vec  # optional

                self._conn.enable_load_extension(True)
                sqlite_vec.load(self._conn)
                self._conn.enable_load_extension(False)
                self._vec = True
            except Exception:  # not installed, or extensions disabled in this sqlite build
                self._vec = False
        return self._vec

    def nearest(self, model: str, vector: list[float], k: int = 20) -> list[tuple[str, float]]:
        """(record_id, cosine similarity) of the k closest decisions; sqlite-vec when available."""
        import array

        if self._vec_loaded():
            rows = self._conn.execute(
                "SELECT record_id, vec_distance_cosine(vector, ?) AS d FROM embeddings"
                " WHERE model = ? AND dim = ? ORDER BY d, record_id LIMIT ?",
                (array.array("f", vector).tobytes(), model, len(vector), k),
            ).fetchall()
            return [(str(rid), 1.0 - float(d)) for rid, d in rows]
        scored = [
            (sum(x * y for x, y in zip(vector, v, strict=False)), rid)
            for rid, v in self.embeddings(model).items()
        ]
        scored.sort(key=lambda p: (-round(p[0], 6), p[1]))
        return [(rid, sim) for sim, rid in scored[:k]]

    def embeddings(self, model: str) -> dict[str, list[float]]:
        import array

        out: dict[str, list[float]] = {}
        for rid, blob in self._conn.execute(
            "SELECT record_id, vector FROM embeddings WHERE model = ?", (model,)
        ):
            vec = array.array("f")
            vec.frombytes(blob)
            out[str(rid)] = vec.tolist()
        return out

    def _ensure_index(self) -> None:
        indexed = self._conn.execute("SELECT COUNT(*) FROM search").fetchone()[0]
        decisions = self._conn.execute(
            "SELECT COUNT(*) FROM records WHERE record_type = 'decision'"
        ).fetchone()[0]
        version = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'index_version'"
        ).fetchone()
        if indexed == decisions and version and version[0] == INDEX_VERSION:
            return
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute("DELETE FROM search")
            self._conn.execute("DELETE FROM refs")
            rows = self._conn.execute(
                "SELECT body, prev_hash, hash FROM records WHERE record_type = 'decision'"
            ).fetchall()
            for row in rows:
                rec = self._row_to_record(row)
                assert isinstance(rec, DecisionTrace)
                self._index(rec)
            self._conn.execute(
                "INSERT OR REPLACE INTO meta VALUES ('index_version', ?)", (INDEX_VERSION,)
            )
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise

    def has(self, record_id: str) -> bool:
        return self._exists(record_id)

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])

    def head(self) -> tuple[int, str]:
        """(record count, head hash) -- publish the head hash to anchor the chain."""
        return self.count(), self._head_hash()

    def export_jsonl(self, out: IO[str]) -> int:
        n = 0
        for rec in self.records(newest_first=False):
            out.write(json.dumps(to_json_dict(rec), ensure_ascii=False) + "\n")
            n += 1
        return n

    # -- integrity -----------------------------------------------------------------------

    def verify(self) -> VerifyResult:
        """Recompute the whole chain. Detects edited, inserted, reordered or removed rows."""
        problems: list[str] = []
        expected_prev = GENESIS
        count = 0
        rows = self._conn.execute(
            "SELECT seq, id, record_type, body, prev_hash, hash FROM records ORDER BY seq"
        )
        for seq, rid, rtype, body, prev_hash, digest in rows:
            count += 1
            where = f"seq {seq} ({rid})"
            if prev_hash != expected_prev:
                problems.append(f"{where}: chain broken (previous record missing or altered)")
            if link_hash(prev_hash, body) != digest:
                problems.append(f"{where}: content does not match its hash")
            try:
                data = json.loads(body)
                if data.get("id") != rid or data.get("record_type") != rtype:
                    problems.append(f"{where}: indexed columns disagree with record body")
                if canonical(data) != body:
                    problems.append(f"{where}: body is not in canonical form")
            except json.JSONDecodeError:
                problems.append(f"{where}: body is not valid JSON")
            expected_prev = digest
        meta = dict(self._conn.execute("SELECT key, value FROM meta").fetchall())
        if "count" in meta:
            if int(meta.get("count", -1)) != count:
                problems.append(
                    f"store holds {count} records but recorded {meta.get('count')} "
                    "(records removed from the end?)"
                )
            if meta.get("head") != expected_prev:
                problems.append("head hash differs from the last recorded head")
        return VerifyResult(ok=not problems, count=count, head=expected_prev, problems=problems)

    # -- internals -----------------------------------------------------------------------

    def _head_hash(self) -> str:
        row = self._conn.execute("SELECT hash FROM records ORDER BY seq DESC LIMIT 1").fetchone()
        return str(row[0]) if row else GENESIS

    def _exists(self, record_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM records WHERE id = ?", (record_id,)).fetchone()
        return row is not None

    @staticmethod
    def _set_meta(conn: sqlite3.Connection, head: str) -> None:
        count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('count', ?)", (str(count),))
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('head', ?)", (head,))

    @staticmethod
    def _row_to_record(row: tuple[str, str, str]) -> AnyRecord:
        body, prev_hash, digest = row
        data = json.loads(body)
        data["integrity"] = {"prev_hash": prev_hash, "hash": digest}
        return parse_record(data)
