"""FastAPI backend serving the TraceDaAI dashboard."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db, monitor
from .config import PROJECT_ROOT

app = FastAPI(title="TraceDaAI")

DASHBOARD_DIR = PROJECT_ROOT / "dashboard"

MONITOR_INTERVAL_ENV = "TRACEDAAI_MONITOR_INTERVAL"
MONITOR_DISABLE_ENV = "TRACEDAAI_DISABLE_MONITOR"


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    if not os.environ.get(MONITOR_DISABLE_ENV):
        interval = float(os.environ.get(MONITOR_INTERVAL_ENV, "5.0"))
        threading.Thread(target=monitor.run_loop, kwargs={"interval": interval}, daemon=True).start()


@app.get("/api/events")
def api_events(limit: int = 200):
    return db.recent_events(limit=limit)


@app.get("/api/summary")
def api_summary():
    return db.event_summary()


@app.get("/api/processes")
def api_processes():
    return db.latest_snapshots()


@app.get("/api/approvals")
def api_pending_approvals():
    return db.pending_approvals()


@app.post("/api/approvals/{approval_id}/{action}")
def api_resolve_approval(approval_id: int, action: str):
    status = "approved" if action == "approve" else "denied"
    db.resolve_approval(approval_id, status)
    return {"ok": True, "id": approval_id, "status": status}


if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(DASHBOARD_DIR / "index.html"))
