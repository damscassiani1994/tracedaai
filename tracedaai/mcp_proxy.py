"""Generic MCP stdio proxy.

Sits between an MCP client (e.g. Claude Code) and a real MCP server:

    client (stdin/stdout) <---> tracedaai proxy <---> real MCP server subprocess

It speaks the same transport as the wrapped server (line-delimited JSON-RPC
over stdio), so from the client's point of view it *is* the server. Every
`tools/call` request is checked against the policy engine before being
forwarded; blocked calls never reach the real server.

Usage (in the client's MCP server config, wrap the original command):
    tracedaai proxy --name my-server -- <original command> [args...]
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Optional

from . import db
from .policy import PolicyEngine, ToolEvent, summarize_target

BLOCK_MESSAGE = (
    "Blocked by TracedAI policy: {reason}. "
    "Approve via `tracedaai approve <event_id>` and retry if this was intentional."
)
ASK_APPROVAL_WINDOW_SECONDS = 300.0


class McpProxy:
    def __init__(self, server_name: str, command: list[str]):
        self.server_name = server_name
        self.command = command
        self.policy = PolicyEngine()
        # request id -> (tool_name, target) so we can log tool_result on the matching response
        self._pending_calls: dict[str, tuple[str, str]] = {}

    async def run(self) -> int:
        db.init_db()
        proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,  # let the child's stderr pass through directly for debugging
        )
        assert proc.stdin and proc.stdout

        client_to_server = asyncio.create_task(self._pump_client_to_server(proc.stdin))
        server_to_client = asyncio.create_task(self._pump_server_to_client(proc.stdout))

        # client_to_server finishes once the client's stdin closes, which in turn
        # closes the child's stdin; server_to_client keeps draining the child's
        # remaining output until *it* exits and closes its stdout. Wait for both
        # so buffered responses aren't dropped, rather than racing/cancelling.
        await client_to_server
        await server_to_client
        if proc.returncode is None:
            proc.terminate()
        return await proc.wait()

    async def _pump_client_to_server(self, server_stdin: asyncio.StreamWriter) -> None:
        reader = await _stdin_reader()
        while True:
            line = await reader.readline()
            if not line:
                break
            decision_line = self._handle_client_line(line)
            if decision_line is not None:
                server_stdin.write(decision_line)
                await server_stdin.drain()
        server_stdin.close()

    async def _pump_server_to_client(self, server_stdout: asyncio.StreamReader) -> None:
        while True:
            line = await server_stdout.readline()
            if not line:
                break
            self._handle_server_line(line)
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()

    def _handle_client_line(self, line: bytes) -> Optional[bytes]:
        """Inspect/police a message from the client before it reaches the real server.

        Returns the (possibly unchanged) line to forward, or None to swallow it
        (a block/deny response has already been written directly to stdout).
        """
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return line  # not JSON-RPC we understand, pass through untouched

        method = msg.get("method")
        req_id = msg.get("id")

        if method != "tools/call":
            db.log_event(
                source="mcp_proxy", event_type="protocol", agent=self.server_name,
                tool_name=method, raw=msg,
            )
            return line

        params = msg.get("params", {}) or {}
        tool_name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        event = ToolEvent.from_args(tool_name, args)
        target = summarize_target(event)
        decision = self.policy.evaluate(event)

        if decision.action == "ask":
            approved = db.check_approval(tool_name, target, ASK_APPROVAL_WINDOW_SECONDS)
            if approved == "approved":
                decision.action = "allow"
            elif approved == "denied":
                decision.action = "block"
            else:
                db.create_approval(tool_name, target)
                decision.action = "block"  # blocked until approved; retry after approving

        event_id = db.log_event(
            source="mcp_proxy", event_type="tool_call", agent=self.server_name,
            tool_name=tool_name, target=target, decision=decision.action,
            risk=decision.risk, reason=decision.reason, request_id=str(req_id), raw=msg,
        )

        if decision.action == "block":
            error_response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32000,
                    "message": BLOCK_MESSAGE.format(reason=decision.reason or "policy rule"),
                    "data": {"event_id": event_id, "rule": decision.rule_name},
                },
            }
            sys.stdout.buffer.write((json.dumps(error_response) + "\n").encode())
            sys.stdout.buffer.flush()
            return None

        if req_id is not None:
            self._pending_calls[str(req_id)] = (tool_name, target)
        return line

    def _handle_server_line(self, line: bytes) -> None:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return
        req_id = msg.get("id")
        if req_id is None:
            return
        call = self._pending_calls.pop(str(req_id), None)
        if call is None:
            return
        tool_name, target = call
        is_error = "error" in msg
        db.log_event(
            source="mcp_proxy", event_type="tool_result", agent=self.server_name,
            tool_name=tool_name, target=target,
            decision="error" if is_error else "completed",
            risk="low", raw=msg, request_id=str(req_id),
        )


_stdin_reader_cache: Optional[asyncio.StreamReader] = None


async def _stdin_reader() -> asyncio.StreamReader:
    global _stdin_reader_cache
    if _stdin_reader_cache is not None:
        return _stdin_reader_cache
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    _stdin_reader_cache = reader
    return reader


def run_proxy(server_name: str, command: list[str]) -> int:
    proxy = McpProxy(server_name, command)
    return asyncio.run(proxy.run())
