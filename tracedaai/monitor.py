"""Resource monitor: periodically snapshot CPU/RAM of known AI processes."""
from __future__ import annotations

import time

import psutil

from . import db
from .config import KNOWN_AI_PROCESSES


def _match_agent(process_name: str) -> str | None:
    name = process_name.lower()
    for needle, label in KNOWN_AI_PROCESSES.items():
        if needle in name:
            return label
    return None


def snapshot_once() -> int:
    """Take one snapshot of all known AI processes. Returns count recorded."""
    count = 0
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
        try:
            info = proc.info
            agent = _match_agent(info.get("name") or "")
            if not agent:
                continue
            mem = info.get("memory_info")
            db.insert_snapshot(
                agent=agent,
                pid=info["pid"],
                process_name=info.get("name") or "",
                cpu_percent=proc.cpu_percent(interval=None),
                rss_bytes=mem.rss if mem else 0,
            )
            count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return count


def run_loop(interval: float = 5.0) -> None:
    db.init_db()
    # First cpu_percent() call always returns 0.0 (needs a baseline); warm it up.
    for proc in psutil.process_iter():
        try:
            proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    while True:
        time.sleep(interval)
        n = snapshot_once()
        print(f"[monitor] recorded {n} process snapshot(s)")
