"""Cursor preToolUse / postToolUse / postToolUseFailure hook entrypoints.

Wire these into .cursor/hooks.json (see `tracedaai init-cursor-hooks`). Cursor
invokes the configured command with the hook payload on stdin as JSON, and
reads the hook's stdout (also JSON) to decide what to do next.

preToolUse fires before any agent action (Shell, Read, Write, Grep, Delete,
Task, MCP:<tool>) and can steer the outcome via `permission`: "allow" lets
the call proceed, "deny" blocks it and explains why to the model. Unlike
Claude Code, Cursor's preToolUse has no native "ask" — a policy "ask"
decision is handled the same way the MCP proxy handles it: deny on first
attempt, create a pending approval, and let a later retry through once
`tracedaai approve` resolves it.

postToolUse / postToolUseFailure can only observe/log — the action already
ran (or was denied/failed).
"""
from __future__ import annotations

import json
import shlex
import sys
from typing import Any

from . import db
from .notifier import notify
from .policy import PolicyEngine, ToolEvent, summarize_target

AGENT_NAME = "Cursor"
ASK_APPROVAL_WINDOW_SECONDS = 300.0


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def handle_pre() -> int:
    payload = _read_payload()
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    engine = PolicyEngine()
    event = ToolEvent.from_args(tool_name, tool_input)
    target = summarize_target(event)
    decision = engine.evaluate(event)

    already_notified = False
    if decision.action == "ask":
        resolved = db.check_approval(tool_name, target, ASK_APPROVAL_WINDOW_SECONDS)
        if resolved == "approved":
            decision.action = "allow"
        elif resolved == "denied":
            decision.action = "block"
        else:
            db.create_approval(tool_name, target)
            decision.action = "block"  # preToolUse has no "ask" — deny until approved, then retry
            notify("TraceDaAI — Approval needed", f"[Cursor] {tool_name}: {target}")
            already_notified = True

    db.log_event(
        source="cursor_hook", event_type="tool_call", agent=AGENT_NAME,
        tool_name=tool_name, target=target, decision=decision.action,
        risk=decision.risk, reason=decision.reason,
        request_id=payload.get("tool_use_id") or payload.get("conversation_id"), raw=payload,
    )

    if decision.action == "block" and not already_notified:
        notify("TraceDaAI — Blocked", f"[Cursor] {tool_name}: {decision.reason or target}")

    permission = "deny" if decision.action == "block" else "allow"
    reason = decision.reason or (
        "Pending approval — run `tracedaai approve <id>` and retry."
        if already_notified else ""
    )
    _emit({
        "permission": permission,
        "agent_message": reason if permission == "deny" else "",
    })
    return 0


def handle_post() -> int:
    payload = _read_payload()
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    event = ToolEvent.from_args(tool_name, tool_input)
    target = summarize_target(event)

    db.log_event(
        source="cursor_hook", event_type="tool_result", agent=AGENT_NAME,
        tool_name=tool_name, target=target, decision="completed",
        risk="low", request_id=payload.get("tool_use_id"), raw=payload,
    )
    return 0


def handle_post_failure() -> int:
    payload = _read_payload()
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    event = ToolEvent.from_args(tool_name, tool_input)
    target = summarize_target(event)

    db.log_event(
        source="cursor_hook", event_type="tool_result", agent=AGENT_NAME,
        tool_name=tool_name, target=target, decision="error",
        risk="low", reason=payload.get("error_message"),
        request_id=payload.get("tool_use_id"), raw=payload,
    )
    return 0


def hooks_snippet() -> dict:
    """Build the .cursor/hooks.json snippet using the *current* interpreter.

    Same rationale as hook.hook_snippet(): sys.executable resolves correctly
    regardless of whether the venv is active when Cursor invokes the hook.
    """
    python = shlex.quote(sys.executable)
    return {
        "version": 1,
        "hooks": {
            "preToolUse": [
                {"command": f"{python} -m tracedaai.cli cursor-hook pre", "type": "command"}
            ],
            "postToolUse": [
                {"command": f"{python} -m tracedaai.cli cursor-hook post", "type": "command"}
            ],
            "postToolUseFailure": [
                {"command": f"{python} -m tracedaai.cli cursor-hook post-failure", "type": "command"}
            ],
        },
    }
