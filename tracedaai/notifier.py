"""Best-effort OS desktop notifications for blocked/pending policy decisions.

Never raises: a notification failure (unsupported platform, notifications
disabled, no `osascript`/`notify-send` on PATH) must never break a hook or
the MCP proxy — it just silently no-ops.
"""
from __future__ import annotations

import platform
import subprocess


def notify(title: str, message: str) -> None:
    try:
        system = platform.system()
        if system == "Darwin":
            _notify_macos(title, message)
        elif system == "Linux":
            _notify_linux(title, message)
        # Windows and anything else: not implemented yet, no-op.
    except Exception:
        pass


def _notify_macos(title: str, message: str) -> None:
    script = f"display notification {_applescript_quote(message)} with title {_applescript_quote(title)}"
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)


def _notify_linux(title: str, message: str) -> None:
    subprocess.run(["notify-send", title, message], capture_output=True, timeout=5)


def _applescript_quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
