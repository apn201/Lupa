"""SQLite schema and connection. One file, no ORM."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS permission (
  id TEXT PRIMARY KEY, source TEXT NOT NULL, external_ref TEXT NOT NULL,
  merchant_alias TEXT NOT NULL, merchant_category TEXT, kind TEXT NOT NULL,
  status TEXT NOT NULL, first_seen TEXT, last_payment_at TEXT, last_amount INTEGER,
  currency TEXT NOT NULL, created_at TEXT NOT NULL, policy_id TEXT, delegation_id TEXT,
  attention TEXT NOT NULL DEFAULT '[]', marker TEXT NOT NULL, suggestion TEXT,
  UNIQUE (source, external_ref)
);
CREATE TABLE IF NOT EXISTS profile (
  permission_id TEXT PRIMARY KEY REFERENCES permission(id), n_payments INTEGER,
  amount_min INTEGER, amount_max INTEGER, amount_median INTEGER, amount_p95 INTEGER,
  interval_days_median REAL, interval_days_mad REAL, months_since_last REAL,
  amount_trend REAL, computed_at TEXT
);
CREATE TABLE IF NOT EXISTS payment (
  id TEXT PRIMARY KEY, permission_id TEXT NOT NULL REFERENCES permission(id),
  paypal_txn_id TEXT, amount INTEGER NOT NULL, currency TEXT NOT NULL, at TEXT NOT NULL,
  event_code TEXT, status TEXT, source TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS payment_txn ON payment(source, paypal_txn_id)
  WHERE paypal_txn_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS policy (
  id TEXT PRIMARY KEY, permission_id TEXT, max_amount INTEGER NOT NULL, currency TEXT NOT NULL,
  recurring TEXT NOT NULL, amount_increase TEXT NOT NULL, increase_tolerance_pct INTEGER NOT NULL,
  new_merchant TEXT NOT NULL, max_per_month INTEGER, expires_at TEXT, created_by TEXT NOT NULL,
  intent_text TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS delegation (
  id TEXT PRIMARY KEY, permission_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  authority TEXT NOT NULL, max_amount INTEGER NOT NULL, recurring_allowed INTEGER NOT NULL,
  amount_change_pct INTEGER NOT NULL, min_confidence REAL NOT NULL, expires_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS payment_request (
  id TEXT PRIMARY KEY, permission_id TEXT NOT NULL, amount INTEGER NOT NULL, currency TEXT NOT NULL,
  merchant_alias TEXT NOT NULL, is_recurring INTEGER NOT NULL, requested_at TEXT NOT NULL,
  source TEXT NOT NULL, agent_id TEXT, purpose TEXT, paypal_order_id TEXT,
  paypal_authorization_id TEXT, state TEXT NOT NULL, hold_until TEXT
);
CREATE TABLE IF NOT EXISTS decision (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL, ai_verdict TEXT, ai_confidence REAL,
  ai_reason_codes TEXT, ai_model TEXT, ai_prompt_version TEXT, policy_verdict TEXT NOT NULL,
  rule_hits TEXT, final TEXT NOT NULL, resolved_by TEXT NOT NULL, resolved_at TEXT NOT NULL,
  paypal_action TEXT NOT NULL, sentences TEXT
);
CREATE TABLE IF NOT EXISTS event (
  id TEXT PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, ref_id TEXT, marker TEXT NOT NULL,
  payload TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class Database:
    """A connection plus a lock. FastAPI runs sync routes on a thread pool."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.lock = threading.RLock()
        self.migrate()

    def migrate(self) -> None:
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
            )

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def transaction(self):
        return _Tx(self)

    def close(self) -> None:
        self.conn.close()


class _Tx:
    def __init__(self, db: Database) -> None:
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.conn.execute("BEGIN")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            self.db.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db.lock.release()
        return False
