"""Transactional SQLite persistence, isolated from domain and HTTP concerns."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from .domain import AppError, Json

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES (1);
CREATE TABLE IF NOT EXISTS sessions (
 id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 last_claim_id TEXT, lease_token TEXT, lease_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id),
 role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS batches (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
 state TEXT NOT NULL, mode TEXT NOT NULL, knowledge_version TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS results (
 batch_id TEXT NOT NULL REFERENCES batches(id), row_index INTEGER NOT NULL,
 claim_id TEXT NOT NULL, evidence TEXT NOT NULL,
 PRIMARY KEY(batch_id,row_index)
);
CREATE INDEX IF NOT EXISTS results_claim ON results(claim_id);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL REFERENCES batches(id),
 sequence INTEGER NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(batch_id,sequence)
);
CREATE TABLE IF NOT EXISTS history (
 policy_number TEXT NOT NULL, claim_id TEXT NOT NULL, claim_type TEXT NOT NULL,
 loss_date TEXT NOT NULL, flagged INTEGER NOT NULL CHECK(flagged IN (0,1)), note TEXT NOT NULL,
 source TEXT NOT NULL, PRIMARY KEY(policy_number,claim_id)
);
CREATE TABLE IF NOT EXISTS reviews (
 batch_id TEXT NOT NULL, row_index INTEGER NOT NULL, decision TEXT NOT NULL,
 note TEXT NOT NULL, reviewer TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(batch_id,row_index), FOREIGN KEY(batch_id,row_index) REFERENCES results(batch_id,row_index)
);
CREATE TABLE IF NOT EXISTS agent_threads (
 session_id TEXT NOT NULL REFERENCES sessions(id), role TEXT NOT NULL, thread_id TEXT NOT NULL,
 PRIMARY KEY(session_id,role)
);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_lease: ContextVar[tuple[str, str] | None] = ContextVar("session_lease", default=None)


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)


class SQLiteRepository:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as db:
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
            ).fetchone():
                versions = [r[0] for r in db.execute("SELECT version FROM schema_version")]
                if versions != [1]:
                    raise AppError("schema_mismatch", "Database schema version is not supported.", 503)
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            versions = [r[0] for r in db.execute("SELECT version FROM schema_version")]
            if versions != [1]:
                raise AppError("schema_mismatch", "Database schema version is not supported.", 503)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        with self.connection() as db:
            db.execute("INSERT INTO sessions(id) VALUES (?)", (session_id,))
        return session_id

    def session(self, session_id: str) -> Json:
        with self.connection() as db:
            row = db.execute(
                "SELECT id,created_at,last_claim_id FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        if row is None:
            raise AppError("not_found", "Session not found.", 404)
        return dict(row)

    @contextmanager
    def session_lock(self, session_id: str) -> Iterator[None]:
        self.session(session_id)
        token = str(uuid.uuid4())
        with self.connection() as db:
            changed = db.execute(
                "UPDATE sessions SET lease_token=?,lease_until=? WHERE id=? AND lease_until<?",
                (token, time.time() + 600, session_id, time.time()),
            ).rowcount
        if not changed:
            raise AppError("session_busy", "Session is processing another request; retry later.", 409)
        context_token = _lease.set((session_id, token))
        try:
            yield
        finally:
            _lease.reset(context_token)
            with self.connection() as db:
                db.execute(
                    "UPDATE sessions SET lease_token=NULL,lease_until=0 WHERE id=? AND lease_token=?",
                    (session_id, token),
                )

    def renew_lease(self, session_id: str) -> None:
        held = _lease.get()
        if held is None or held[0] != session_id:
            raise AppError("lease_lost", "Session processing lease is not held.", 409)
        with self.connection() as db:
            changed = db.execute(
                "UPDATE sessions SET lease_until=? WHERE id=? AND lease_token=? AND lease_until>?",
                (time.time() + 600, session_id, held[1], time.time()),
            ).rowcount
            if not changed:
                raise AppError("lease_lost", "Session processing lease expired or was replaced.", 409)

    def add_message(self, session_id: str, role: str, content: str, claim_id: str | None = None) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO messages(session_id,role,content) VALUES (?,?,?)", (session_id, role, content)
            )
            if claim_id:
                db.execute("UPDATE sessions SET last_claim_id=? WHERE id=?", (claim_id, session_id))

    def messages(self, session_id: str) -> list[Json]:
        self.session(session_id)
        with self.connection() as db:
            rows = db.execute(
                "SELECT role,content,created_at FROM (SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 100) ORDER BY id",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def seen_ids(self, session_id: str) -> set[str]:
        with self.connection() as db:
            return {
                r[0]
                for r in db.execute(
                    "SELECT r.claim_id FROM results r JOIN batches b ON b.id=r.batch_id WHERE b.session_id=?",
                    (session_id,),
                )
            }

    def history(self, policy_number: str) -> list[Json]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM history WHERE policy_number=? ORDER BY loss_date DESC,claim_id",
                (policy_number,),
            ).fetchall()
        return [dict(row, flagged=bool(row["flagged"])) for row in rows]

    def seed_history(self, records: list[Json]) -> None:
        with self.connection() as db:
            for record in records:
                db.execute(
                    "INSERT OR IGNORE INTO history VALUES (?,?,?,?,?,?,?)",
                    (
                        record["policy_number"],
                        record["claim_id"],
                        record["claim_type"],
                        record["loss_date"],
                        int(record["flagged"]),
                        record["note"],
                        "synthetic_seed",
                    ),
                )

    def save_batch(self, batch: Json, history: list[Json]) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            held = _lease.get()
            if held is None or held[0] != batch["session_id"]:
                raise AppError("lease_lost", "Batch persistence requires a session lease.", 409)
            owner = db.execute(
                "SELECT lease_token,lease_until FROM sessions WHERE id=?", (batch["session_id"],)
            ).fetchone()
            if owner is None or owner[0] != held[1] or owner[1] <= time.time():
                raise AppError("lease_lost", "Batch persistence lease expired or was replaced.", 409)
            db.execute(
                "INSERT INTO batches(id,session_id,state,mode,knowledge_version) VALUES (?,?,?,?,?)",
                tuple(batch[k] for k in ("id", "session_id", "state", "mode", "knowledge_version")),
            )
            for row in batch["results"]:
                db.execute(
                    "INSERT INTO results VALUES (?,?,?,?)",
                    (batch["id"], row["row_index"], row["claim_id"], dump(row)),
                )
            for sequence, event in enumerate(batch["events"]):
                db.execute(
                    "INSERT INTO events(batch_id,sequence,state,detail) VALUES (?,?,?,?)",
                    (batch["id"], sequence, event["state"], dump(event.get("detail", {}))),
                )
            for record in history:
                # Preserve a prior flag; replaying a clean claim must not erase past evidence.
                db.execute(
                    """INSERT INTO history VALUES (?,?,?,?,?,?,?) ON CONFLICT(policy_number,claim_id)
                    DO UPDATE SET flagged=MAX(history.flagged,excluded.flagged)""",
                    (
                        record["policy_number"],
                        record["claim_id"],
                        record["claim_type"],
                        record["loss_date"],
                        int(record["flagged"]),
                        record["note"],
                        batch["id"],
                    ),
                )

    def batch(self, session_id: str, batch_id: str) -> Json:
        self.session(session_id)
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM batches WHERE id=? AND session_id=?", (batch_id, session_id)
            ).fetchone()
            if row is None:
                raise AppError("not_found", "Batch not found in this session.", 404)
            result = dict(row)
            result["results"] = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT evidence FROM results WHERE batch_id=? ORDER BY row_index", (batch_id,)
                )
            ]
            result["events"] = [
                {"state": r[0], "detail": json.loads(r[1])}
                for r in db.execute(
                    "SELECT state,detail FROM events WHERE batch_id=? ORDER BY sequence", (batch_id,)
                )
            ]
            reviews = {
                r["row_index"]: dict(r)
                for r in db.execute("SELECT * FROM reviews WHERE batch_id=?", (batch_id,))
            }
            for item in result["results"]:
                if item["row_index"] in reviews:
                    item["review"] = reviews[item["row_index"]]
                    item["brief"]["review_status"] = "reviewed"
            result["synthetic"] = True
        return result

    def batches(self, session_id: str) -> list[Json]:
        self.session(session_id)
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,state,mode,created_at FROM batches WHERE session_id=? ORDER BY rowid DESC LIMIT 100",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_results(self, session_id: str, claim_id: str) -> list[Json]:
        with self.connection() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT r.evidence FROM results r JOIN batches b ON b.id=r.batch_id WHERE b.session_id=? AND r.claim_id=? ORDER BY b.rowid DESC,r.row_index",
                    (session_id, claim_id),
                )
            ]

    def review(
        self, session_id: str, batch_id: str, row_index: int, decision: str, note: str, reviewer: str
    ) -> Json:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.evidence FROM results r JOIN batches b ON b.id=r.batch_id WHERE b.id=? AND b.session_id=? AND r.row_index=?",
                (batch_id, session_id, row_index),
            ).fetchone()
            if row is None:
                raise AppError("not_found", "Claim row not found in this session.", 404)
            evidence = json.loads(row[0])
            if decision == "approve" and evidence["brief"]["recommended_action"] != "auto_approve":
                raise AppError(
                    "unsafe_approval",
                    "Flagged or incomplete evidence cannot be approved; obtain corrected evidence in a new session.",
                    409,
                )
            try:
                db.execute(
                    "INSERT INTO reviews(batch_id,row_index,decision,note,reviewer) VALUES (?,?,?,?,?)",
                    (batch_id, row_index, decision, note, reviewer),
                )
            except sqlite3.IntegrityError as exc:
                raise AppError(
                    "already_reviewed", "A human decision has already been recorded.", 409
                ) from exc
            remaining = db.execute(
                "SELECT COUNT(*) FROM results r WHERE batch_id=? AND NOT EXISTS (SELECT 1 FROM reviews v WHERE v.batch_id=r.batch_id AND v.row_index=r.row_index)",
                (batch_id,),
            ).fetchone()[0]
            if remaining == 0:
                db.execute("UPDATE batches SET state='REVIEWED' WHERE id=?", (batch_id,))
            sequence = db.execute(
                "SELECT COALESCE(MAX(sequence),-1)+1 FROM events WHERE batch_id=?", (batch_id,)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO events(batch_id,sequence,state,detail) VALUES (?,?,?,?)",
                (
                    batch_id,
                    sequence,
                    "HUMAN_DECISION",
                    dump({"row_index": row_index, "decision": decision, "reviewer": reviewer}),
                ),
            )
        return {
            "batch_id": batch_id,
            "row_index": row_index,
            "decision": decision,
            "reviewer": reviewer,
            "note": note,
        }

    def thread(self, session_id: str, role: str) -> str | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT thread_id FROM agent_threads WHERE session_id=? AND role=?", (session_id, role)
            ).fetchone()
        return row[0] if row else None

    def set_thread(self, session_id: str, role: str, thread_id: str) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO agent_threads VALUES (?,?,?) ON CONFLICT(session_id,role) DO UPDATE SET thread_id=excluded.thread_id",
                (session_id, role, thread_id),
            )

    def metadata(self, key: str) -> Json | None:
        with self.connection() as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_metadata(self, key: str, value: Json) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, dump(value)),
            )
