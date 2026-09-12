"""Claude Code PreToolUse / PostToolUse hook entrypoints.

Wire these into .claude/settings.json (see `tracedaai init-hooks`). Claude Code
invokes the configured command with the hook payload on stdin as JSON, and
reads the hook's stdout (also JSON) to decide what to do next.

PreToolUse can steer the outcome via `hookSpecificOutput.permissionDecision`:
"allow" lets the call proceed silently, "ask" makes Claude Code show its own
native permission prompt, and "deny" blocks the call and feeds the reason
back to the model. PostToolUse can only observe/log — the action already ran.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from . import db
from .notifier import notify
from .policy import PolicyEngine, ToolEvent, summarize_target

AGENT_NAME = "claude-code"

_DECISION_TO_PERMISSION = {
    "allow": "allow",
    "ask": "ask",
    "block": "deny",
}


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

    if decision.action == "ask":
        resolved = db.check_approval(tool_name, target)
        if resolved == "approved":
            decision.action = "allow"
        elif resolved == "denied":
            decision.action = "block"
        # else: leave as "ask" and let Claude Code's own prompt handle it

    db.log_event(
        source="claude_hook", event_type="tool_call", agent=AGENT_NAME,
        tool_name=tool_name, target=target, decision=decision.action,
        risk=decision.risk, reason=decision.reason,
        request_id=payload.get("session_id"), raw=payload,
    )

    if decision.action == "block":
        notify("TraceDaAI — Blocked", f"{tool_name}: {decision.reason or target}")

    _emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": _DECISION_TO_PERMISSION[decision.action],
            "permissionDecisionReason": decision.reason or "",
        }
    })
    return 0


def handle_post() -> int:
    payload = _read_payload()
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    tool_response = payload.get("tool_response", {}) or {}
    event = ToolEvent.from_args(tool_name, tool_input)
    target = summarize_target(event)

    is_error = bool(tool_response.get("is_error") or tool_response.get("error"))
    db.log_event(
        source="claude_hook", event_type="tool_result", agent=AGENT_NAME,
        tool_name=tool_name, target=target,
        decision="error" if is_error else "completed",
        risk="low", request_id=payload.get("session_id"), raw=payload,
    )
    return 0


HOOK_SNIPPET = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "*",
                "hooks": [
                    {"type": "command", "command": "python3 -m tracedaai.cli hook pre"}
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": "*",
                "hooks": [
                    {"type": "command", "command": "python3 -m tracedaai.cli hook post"}
                ],
            }
        ],
    }
}
