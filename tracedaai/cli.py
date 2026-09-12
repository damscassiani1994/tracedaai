from __future__ import annotations

import argparse
import json
import sys

from . import db
from .config import DB_PATH, RULES_PATH, ensure_data_dir


def cmd_init(_args) -> int:
    ensure_data_dir()
    db.init_db()
    print(f"DB initialized at {DB_PATH}")
    print(f"Policy rules: {RULES_PATH}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("tracedaai.server:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def cmd_monitor(args) -> int:
    from .monitor import run_loop

    run_loop(interval=args.interval)
    return 0


def cmd_proxy(args) -> int:
    from .mcp_proxy import run_proxy

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        print("Usage: tracedaai proxy --name <server-name> -- <command> [args...]", file=sys.stderr)
        return 2
    return run_proxy(args.name, command)


def cmd_hook(args) -> int:
    from .hook import handle_post, handle_pre

    if args.event == "pre":
        return handle_pre()
    return handle_post()


def cmd_init_hooks(_args) -> int:
    from .hook import HOOK_SNIPPET

    print("Add this to your Claude Code settings.json (project .claude/settings.json")
    print("or the global ~/.claude/settings.json) under the existing config, merging")
    print("with any hooks you already have:\n")
    print(json.dumps(HOOK_SNIPPET, indent=2))
    return 0


def cmd_approve(args) -> int:
    db.resolve_approval(args.approval_id, "approved" if args.action == "approve" else "denied")
    print(f"Approval {args.approval_id} -> {args.action}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tracedaai", description="AI Control Center / AI Firewall")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Initialize local data dir and DB")
    p_init.set_defaults(func=cmd_init)

    p_serve = sub.add_parser("serve", help="Run the dashboard web server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8787)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_monitor = sub.add_parser("monitor", help="Run the resource monitor loop")
    p_monitor.add_argument("--interval", type=float, default=5.0)
    p_monitor.set_defaults(func=cmd_monitor)

    p_proxy = sub.add_parser("proxy", help="Wrap a real MCP server with the TracedAI firewall")
    p_proxy.add_argument("--name", required=True, help="Label for this MCP server in logs/dashboard")
    p_proxy.add_argument("command", nargs=argparse.REMAINDER, help="-- <original command> [args...]")
    p_proxy.set_defaults(func=cmd_proxy)

    p_hook = sub.add_parser("hook", help="Claude Code hook entrypoint (called from settings.json)")
    p_hook.add_argument("event", choices=["pre", "post"])
    p_hook.set_defaults(func=cmd_hook)

    p_init_hooks = sub.add_parser("init-hooks", help="Print settings.json snippet to wire up Claude Code hooks")
    p_init_hooks.set_defaults(func=cmd_init_hooks)

    p_approve = sub.add_parser("approve", help="Resolve a pending 'ask' decision")
    p_approve.add_argument("approval_id", type=int)
    p_approve.add_argument("action", choices=["approve", "deny"], nargs="?", default="approve")
    p_approve.set_defaults(func=cmd_approve)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
