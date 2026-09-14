# TraceDaAI

A personal "AI Firewall / AI Permission Manager": audits and controls what AI
agents (Claude Code, Cursor, MCP servers, etc.) do on your machine — files,
commands, network — with allow/ask/block rules, surfaced in a single
dashboard.

## Security model & limits (read this before relying on it)

TraceDaAI Phase 1 is **cooperative**, not real operating-system-level
enforcement. It works by intercepting protocols the agent itself voluntarily
respects: Claude Code's hooks (`PreToolUse`/`PostToolUse`), Cursor's native
hooks (`preToolUse`/`postToolUse`/`postToolUseFailure`), and the MCP
JSON-RPC traffic that passes through the proxy. That means:

- A process that doesn't go through one of those interception points (an
  arbitrary script, a binary that ignores hooks, MCP traffic that bypasses
  the proxy) is **not controlled** by TraceDaAI.
- There's no verification that Claude Code or Cursor themselves honor the
  hook's decision — it relies on each tool's documented hook contract
  (`hookSpecificOutput` for Claude Code, `permission` for Cursor).
- Real, unbypassable enforcement (blocking file access at the kernel level
  no matter which process asks) is roadmap Phase 4 (Endpoint Security on
  macOS / eBPF on Linux / ETW+minifilter on Windows) and **doesn't exist
  yet**.

In short: useful for auditing and for stopping accidental or careless
actions from agents that cooperate with the protocol (the normal case for
Claude Code, Cursor, MCP servers, etc.), but it is not a security barrier
against an adversarial agent that decides to evade it.

## Roadmap

1. **Phase 1 (done):** MCP Firewall (stdio proxy) + Claude Code hooks +
   Cursor native hooks + Cursor MCP wrapping + activity dashboard.
2. **Phase 2 (next):** Discovery + Resource Monitor — automatic process
   discovery (today matching is against a hardcoded process-name list, now
   run automatically by `tracedaai serve`), basic CPU/RAM/network per known
   process.
3. Phase 3: Network attribution via a local proxy.
4. Phase 4: Real OS-level enforcement (Endpoint Security / eBPF / ETW) —
   only if the product validates traction.

## Requirements

- Python 3.10+
- macOS or Linux for desktop notifications (macOS via `osascript`, Linux via
  `notify-send`; Windows isn't implemented yet — notifications silently
  no-op there)

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
tracedaai init
```

## Usage

### Dashboard

```bash
tracedaai serve
# open http://127.0.0.1:8787
```

Click any row in the **Agents** table to open a detail popup: inferred
**Permissions** (read/write/exec/git/network/env-access, derived from that
agent's actual event history — not a real permissions API), **Resources**
(real CPU/RAM; GPU and network throughput are honestly shown as "N/A" since
neither is measured yet), recent **Activity**, deduped **Warnings**, and a
**Risk** bar. Switch the whole UI between **English and Spanish** with the
EN/ES buttons in the header — English is the default, and the choice is
remembered per-browser.

### Claude Code hooks (audit + allow/ask/block on tool calls)

```bash
tracedaai init-hooks   # prints a settings.json snippet for your venv
```

Copy the snippet into `hooks` in your `~/.claude/settings.json` (global) or
`.claude/settings.json` (per-project) — merge it with any hooks you already
have. It uses the exact interpreter that ran `tracedaai init-hooks`
(`sys.executable`), so it resolves correctly even if the venv isn't active
when Claude Code invokes it. From then on, every `PreToolUse` is evaluated
against `rules.yaml`: `allow` lets it through, `ask` triggers Claude Code's
native permission prompt, `block` denies it and explains why to the model.
Every call (pre and post) is logged and shows up in the dashboard.

### Cursor hooks (audit + allow/ask/block on tool calls)

Cursor 1.7+ has its own native agent hooks (`preToolUse`/`postToolUse`/
`postToolUseFailure`), covering every built-in agent action — shell
commands, file reads/writes/deletes, MCP calls — not just MCP traffic.

```bash
tracedaai init-cursor-hooks   # prints a hooks.json snippet for your venv
```

Copy the snippet into `.cursor/hooks.json` (per-project) or
`~/.cursor/hooks.json` (global) — merge it with any hooks you already have.
Same `sys.executable` resolution trick as `init-hooks`. Every `preToolUse`
is evaluated against `rules.yaml`: `allow` lets it through, `block` denies
it and explains why to the agent. Cursor's `preToolUse` has no native "ask"
prompt, so an `ask` rule denies the first attempt and creates a pending
approval — resolve it with `tracedaai approve <id>` and retry, same as the
MCP proxy's approval flow. Every call (pre and post) is logged under the
"Cursor" agent, merging with the resource-monitor data already shown for
it in the dashboard.

### MCP proxy (wraps any stdio MCP server)

In your client's MCP configuration, point it at TraceDaAI instead of the
real server command:

```bash
tracedaai proxy --name my-server -- <original command> [args...]
```

The proxy forwards all JSON-RPC traffic transparently, but inspects every
`tools/call` against `rules.yaml` before letting it through.

#### Cursor

```bash
tracedaai init-cursor-mcp -- <original MCP server command> [args...]
```

Prints a snippet to paste under `"mcpServers"` in `.cursor/mcp.json` (project)
or `~/.cursor/mcp.json` (global) that wraps that server with the proxy,
using `--name Cursor` by default so events join the same "Cursor" row the
resource monitor already populates. Add `--name <label>` /
`--server-key <key>` to change the dashboard agent label or the JSON key.

This only covers tool calls Cursor routes through an MCP server you've
wrapped this way — it does **not** see Cursor's built-in actions (editing
files or running terminal commands directly in the editor). For that, use
Cursor's own native hooks instead (see "Cursor hooks" above).

### Resource monitor

`tracedaai serve` now runs the resource-monitor loop automatically in a
background thread (default interval: 5s), so CPU/RAM snapshots start
appearing as soon as the dashboard is up — no separate command needed.
Tune it with `--monitor-interval <seconds>`, or turn it off with
`--no-monitor` (e.g. to run the monitor as its own long-lived process
instead, or on a headless box without the dashboard):

```bash
tracedaai serve --monitor-interval 10
tracedaai serve --no-monitor        # then run the loop separately:
tracedaai monitor --interval 5
```

Either way, it records CPU/RAM snapshots for known AI processes so the dashboard can show
resource usage per agent. Currently recognized (see `KNOWN_AI_PROCESSES` in
`tracedaai/config.py`): Claude Code, Cursor, Ollama, GitHub Copilot, Codex
CLI, ChatGPT Desktop, Windsurf/Codeium, Gemini CLI, Aider, and LM Studio.
This only detects agents that run as their own standalone process (a
desktop app or a CLI) — anything embedded as an editor extension (Copilot
Chat inside VS Code, Continue.dev, JetBrains AI) has no separate process to
match and isn't detected this way. Exact process names are best-effort —
if one doesn't match on your machine, adjust the dict.

### Desktop notifications

Every time an action is blocked or a pending approval is created, TraceDaAI
sends a native system notification. Test that it works:

```bash
tracedaai notify-test
```

## Rules (`rules.yaml`)

Rules are evaluated in order; the first match wins. See the bundled
examples (blocking dotenv/credential files, asking for confirmation before
`sudo` or `git push --force`, etc.) for the format.

## Approving an "ask" decision

When a rule says `ask`, the Claude Code hook defers to its own native
prompt. The MCP proxy and the Cursor hooks have no such UI: they block the
first attempt and record a pending approval, visible on the dashboard or via:

```bash
tracedaai approve <id> approve   # or "deny"
```

Retry the call once approved (the approval is valid for 5 minutes for the
same tool + target).

## CLI reference

| Command | Purpose |
|---|---|
| `tracedaai init` | Initialize the local data dir and SQLite DB |
| `tracedaai serve [--host] [--port] [--reload] [--monitor-interval] [--no-monitor]` | Run the dashboard web server (default `127.0.0.1:8787`); also runs the resource monitor in the background unless `--no-monitor` |
| `tracedaai monitor [--interval]` | Run the resource-monitor loop |
| `tracedaai proxy --name <label> -- <cmd> [args...]` | Wrap a real MCP server with the firewall |
| `tracedaai init-cursor-mcp [--name] [--server-key] -- <cmd> [args...]` | Print a `.cursor/mcp.json` snippet wrapping an MCP server with the firewall |
| `tracedaai hook pre\|post` | Claude Code hook entrypoint (called from settings.json, not by hand) |
| `tracedaai init-hooks` | Print the settings.json snippet to wire up Claude Code hooks |
| `tracedaai cursor-hook pre\|post\|post-failure` | Cursor hook entrypoint (called from hooks.json, not by hand) |
| `tracedaai init-cursor-hooks` | Print the hooks.json snippet to wire up Cursor's native agent hooks |
| `tracedaai notify-test` | Send a test desktop notification |
| `tracedaai approve <id> [approve\|deny]` | Resolve a pending "ask" decision |

## License

MIT — see [LICENSE](LICENSE).
