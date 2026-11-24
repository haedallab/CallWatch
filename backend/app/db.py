"""Tiny storage layer: SQLite by default, PostgreSQL (e.g. Supabase) when DATABASE_URL is set.

Only portable SQL is used (ON CONFLICT upserts work on SQLite >= 3.24 and PostgreSQL).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from .config import settings

_lock = threading.Lock()
_IS_PG = settings.database_url.startswith(("postgres://", "postgresql://"))

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS kv_cache (
        key TEXT PRIMARY KEY, value TEXT NOT NULL, fetched_at DOUBLE PRECISION NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS holdings (
        ticker TEXT PRIMARY KEY, weight DOUBLE PRECISION, shares DOUBLE PRECISION, note TEXT)""",
    """CREATE TABLE IF NOT EXISTS transcripts (
        id TEXT PRIMARY KEY, ticker TEXT NOT NULL, call_date TEXT NOT NULL,
        source TEXT NOT NULL, text TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL,
        user_id TEXT NOT NULL DEFAULT 'local', source_url TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS reports (
        ticker TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at DOUBLE PRECISION NOT NULL)""",
]


def _connect():
    if _IS_PG:
        import psycopg  # type: ignore

        # prepare_threshold=None: safe behind Supabase's pgbouncer/supavisor poolers
        return psycopg.connect(settings.database_url, autocommit=True, prepare_threshold=None, connect_timeout=10)
    conn = sqlite3.connect(settings.data_dir / "callwatch.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


_conn = None


@contextmanager
def cursor() -> Iterator[Any]:
    global _conn
    with _lock:
        if _conn is not None and _IS_PG and getattr(_conn, "closed", False):
            _conn = None  # dropped by the pooler or a restart: reconnect
        if _conn is None:
            _conn = _connect()
            cur = _conn.cursor()
            for stmt in SCHEMA:
                cur.execute(stmt)
            for col in ("user_id TEXT NOT NULL DEFAULT 'local'", "source_url TEXT NOT NULL DEFAULT ''"):
                try:  # migrate databases created by earlier versions
                    cur.execute(f"ALTER TABLE transcripts ADD COLUMN {col}")
                except Exception:
                    pass  # column already exists
            if not _IS_PG:
                _conn.commit()
        cur = _conn.cursor()
        try:
            yield cur
            if not _IS_PG:
                _conn.commit()
        except Exception as e:
            if _IS_PG and e.__class__.__name__ in ("OperationalError", "InterfaceError"):
                _conn = None  # next call opens a fresh connection
            raise
        finally:
            try:
                cur.close()
            except Exception:
                pass


def _q(sql: str) -> str:
    return sql.replace("?", "%s") if _IS_PG else sql


def execute(sql: str, params: tuple = ()) -> None:
    with cursor() as cur:
        cur.execute(_q(sql), params)


def fetchall(sql: str, params: tuple = ()) -> list[dict]:
    with cursor() as cur:
        cur.execute(_q(sql), params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, r)) for r in rows]


# ---- key/value cache ---------------------------------------------------------

def cache_get(key: str, max_age_hours: float | None = None) -> Any | None:
    rows = fetchall("SELECT value, fetched_at FROM kv_cache WHERE key = ?", (key,))
    if not rows:
        return None
    age_h = (time.time() - rows[0]["fetched_at"]) / 3600
    if max_age_hours is not None and age_h > max_age_hours:
        return None
    return json.loads(rows[0]["value"])


def cache_set(key: str, value: Any) -> None:
    execute(
        "INSERT INTO kv_cache (key, value, fetched_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, fetched_at = excluded.fetched_at",
        (key, json.dumps(value, default=str), time.time()),
    )


# ---- holdings ------------------------------------------------------------------

def get_holdings() -> list[dict]:
    return fetchall("SELECT ticker, weight, shares, note FROM holdings ORDER BY weight DESC, ticker")


def replace_holdings(items: list[dict]) -> None:
    execute("DELETE FROM holdings")
    for it in items:
        execute(
            "INSERT INTO holdings (ticker, weight, shares, note) VALUES (?, ?, ?, ?)",
            (it["ticker"].upper(), it.get("weight"), it.get("shares"), it.get("note") or ""),
        )


# ---- transcripts (owned by a user) -------------------------------------------------

def save_transcript(ticker: str, call_date: str, source: str, text: str, user_id: str = "local",
                    source_url: str = "") -> str:
    tid = f"{user_id}:{ticker.upper()}:{call_date}:{source}"
    execute(
        "INSERT INTO transcripts (id, ticker, call_date, source, text, created_at, user_id, source_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET text = excluded.text, created_at = excluded.created_at, "
        "source_url = excluded.source_url",
        (tid, ticker.upper(), call_date, source, text, time.time(), user_id, source_url or ""),
    )
    return tid


def list_transcripts(ticker: str, user_id: str | None = "local") -> list[dict]:
    if user_id is None:
        return []
    return fetchall(
        "SELECT id, ticker, call_date, source, text, source_url, user_id FROM transcripts "
        "WHERE ticker = ? AND user_id = ? ORDER BY call_date",
        (ticker.upper(), user_id),
    )


def delete_transcript(tid: str, user_id: str = "local") -> None:
    execute("DELETE FROM transcripts WHERE id = ? AND user_id = ?", (tid, user_id))


def delete_user(user_id: str) -> None:
    """Remove everything stored for one user (holdings, transcripts, personal reports, usage counters)."""
    execute("DELETE FROM transcripts WHERE user_id = ?", (user_id,))
    for prefix in (f"holdings:demo:{user_id}", f"holdings:live:{user_id}", f"broker:last:demo:{user_id}",
                   f"broker:last:live:{user_id}", f"corpus:demo:{user_id}:", f"corpus:live:{user_id}:", f"usage:{user_id}:"):
        execute("DELETE FROM kv_cache WHERE key LIKE ?", (prefix + "%",))
    for prefix in (f"DEMO:{user_id.upper()}:", f"LIVE:{user_id.upper()}:"):
        execute("DELETE FROM reports WHERE ticker LIKE ?", (prefix + "%",))


def bump_usage(user_id: str, day: str) -> int:
    key = f"usage:{user_id}:{day}"
    n = (cache_get(key) or 0) + 1
    cache_set(key, n)
    return n


# ---- reports --------------------------------------------------------------------

def save_report(ticker: str, report: dict) -> None:
    execute(
        "INSERT INTO reports (ticker, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(ticker) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (ticker.upper(), json.dumps(report, default=str), time.time()),
    )


def report_updated(ticker: str) -> float | None:
    rows = fetchall("SELECT updated_at FROM reports WHERE ticker = ?", (ticker.upper(),))
    return rows[0]["updated_at"] if rows else None


def count_usage(key: str, day: str) -> int:
    return cache_get(f"usage:{key}:{day}") or 0


def get_report(ticker: str) -> dict | None:
    rows = fetchall("SELECT value FROM reports WHERE ticker = ?", (ticker.upper(),))
    return json.loads(rows[0]["value"]) if rows else None
