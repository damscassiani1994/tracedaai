"""SQLite storage for TracedAI: audit events and resource snapshots."""
import contextlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator, Optional

from .config import DB_PATH, ensure_data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    source TEXT NOT NULL,          -- 'mcp_proxy' | 'claude_hook'
    agent TEXT,                    -- e.g. 'claude-code', mcp server name
    event_type TEXT NOT NULL,      -- 'tool_call' | 'tool_result' | 'protocol' | 'warning'
    tool_name TEXT,
    target TEXT,                   -- file path / command / url summary
    decision TEXT,                 -- 'allow' | 'ask' | 'block'
    risk TEXT,                     -- 'low' | 'medium' | 'high'
    reason TEXT,
    request_id TEXT,
    raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);

CREATE TABLE IF NOT EXISTS resource_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    agent TEXT NOT NULL,
    pid INTEGER,
    process_name TEXT,
    cpu_percent REAL,
    rss_bytes INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON resource_snapshots(ts DESC);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    tool_name TEXT,
    target TEXT,
    status TEXT NOT NULL DEFAULT 'pending'  -- 'pending' | 'approved' | 'denied'
);
"""


@contextlib.contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    ensure_data_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def log_event(
    source: str,
    event_type: str,
    agent: Optional[str] = None,
    tool_name: Optional[str] = None,
    target: Optional[str] = None,
    decision: Optional[str] = None,
    risk: Optional[str] = None,
    reason: Optional[str] = None,
    request_id: Optional[str] = None,
    raw: Optional[Any] = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO events
               (ts, source, agent, event_type, tool_name, target, decision, risk, reason, request_id, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                source,
                agent,
                event_type,
                tool_name,
                target,
                decision,
                risk,
                reason,
                request_id,
                json.dumps(raw, default=str) if raw is not None else None,
            ),
        )
        return cur.lastrowid


def recent_events(limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def event_summary() -> list[dict]:
    """Per-agent counts and highest risk seen, for the AI Control Center table."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT agent,
                   COUNT(*) AS total_events,
                   SUM(CASE WHEN decision = 'block' THEN 1 ELSE 0 END) AS blocked,
                   SUM(CASE WHEN decision = 'ask' THEN 1 ELSE 0 END) AS asked,
                   MAX(ts) AS last_seen,
                   MAX(CASE risk WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END) AS risk_score
            FROM events
            WHERE agent IS NOT NULL
            GROUP BY agent
            ORDER BY last_seen DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def insert_snapshot(agent: str, pid: int, process_name: str, cpu_percent: float, rss_bytes: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO resource_snapshots (ts, agent, pid, process_name, cpu_percent, rss_bytes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (time.time(), agent, pid, process_name, cpu_percent, rss_bytes),
        )


def latest_snapshots(max_age_seconds: float = 30.0) -> list[dict]:
    """Latest snapshot per agent, only if recent enough to be considered 'active'."""
    cutoff = time.time() - max_age_seconds
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.* FROM resource_snapshots s
            INNER JOIN (
                SELECT agent, pid, MAX(ts) AS max_ts
                FROM resource_snapshots
                GROUP BY agent, pid
            ) latest
            ON s.agent = latest.agent AND s.pid = latest.pid AND s.ts = latest.max_ts
            WHERE s.ts >= ?
            ORDER BY s.agent
            """,
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]


def create_approval(tool_name: str, target: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO approvals (ts, tool_name, target, status) VALUES (?, ?, ?, 'pending')",
            (time.time(), tool_name, target),
        )
        return cur.lastrowid


def resolve_approval(approval_id: int, status: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE approvals SET status = ? WHERE id = ?", (status, approval_id))


def check_approval(tool_name: str, target: str, within_seconds: float = 300.0) -> Optional[str]:
    """Return 'approved'/'denied' if a matching decision was made recently, else None."""
    cutoff = time.time() - within_seconds
    with get_conn() as conn:
        row = conn.execute(
            """SELECT status FROM approvals
               WHERE tool_name = ? AND target = ? AND status != 'pending' AND ts >= ?
               ORDER BY ts DESC LIMIT 1""",
            (tool_name, target, cutoff),
        ).fetchone()
        return row["status"] if row else None


def pending_approvals() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM approvals WHERE status = 'pending' ORDER BY ts DESC"
        ).fetchall()
        return [dict(r) for r in rows]
