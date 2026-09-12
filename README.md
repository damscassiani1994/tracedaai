# TracedAI

Un "AI Firewall / AI Permission Manager" personal: audita y controla qué hacen
los agentes de IA (Claude Code, Cursor, Copilot, servidores MCP, etc.) en tu
máquina — archivos, comandos, red — con reglas allow/ask/block, y lo muestra
en un dashboard único.

## Roadmap

1. **Fase 1 (actual):** MCP Firewall (proxy stdio) + hooks de Claude Code +
   dashboard mínimo de actividad.
2. Fase 2: Discovery + Resource Monitor (CPU/RAM/red por proceso conocido).
3. Fase 3: Atribución de red vía proxy local.
4. Fase 4: Enforcement real a nivel de SO (Endpoint Security / eBPF / ETW) —
   solo si el producto valida tracción.

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
tracedaai init
```

## Uso

### Dashboard

```bash
tracedaai serve
# abre http://127.0.0.1:8787
```

### Hooks de Claude Code (auditoría + allow/ask/block sobre tool calls)

```bash
tracedaai init-hooks   # imprime el snippet para .claude/settings.json
```

Copia el snippet dentro de `hooks` en tu `~/.claude/settings.json` (global) o
`.claude/settings.json` (por proyecto). A partir de ahí, cada `PreToolUse` se
evalúa contra `rules.yaml`: `allow` deja pasar, `ask` dispara el prompt nativo
de permisos de Claude Code, `block` deniega y explica el motivo al modelo.
Cada llamada (pre y post) queda registrada en el dashboard.

### Proxy MCP (envuelve cualquier servidor MCP stdio)

En la configuración MCP de tu cliente, en vez de apuntar directamente al
comando del servidor real, apúntalo a TracedAI:

```bash
tracedaai proxy --name mi-servidor -- <comando original> [args...]
```

El proxy reenvía todo el tráfico JSON-RPC de forma transparente, pero
inspecciona cada `tools/call` contra `rules.yaml` antes de dejarlo pasar.

### Resource monitor

```bash
tracedaai monitor --interval 5
```

Registra snapshots de CPU/RAM de procesos conocidos (Claude, Cursor, Ollama,
Copilot, Codex) para que el dashboard muestre uso de recursos por agente.

## Reglas (`rules.yaml`)

Reglas evaluadas en orden, la primera que matchea gana. Ver los ejemplos ya
incluidos (bloquear `.env`/credenciales, pedir confirmación antes de `sudo` o
`git push --force`, etc.) para el formato.

## Aprobar una acción en "ask"

Cuando una regla dice `ask`, el hook de Claude Code delega en su propio
prompt nativo. El proxy MCP, en cambio, no tiene esa UI: bloquea la primera
vez y registra una aprobación pendiente, visible en el dashboard o vía:

```bash
tracedaai approve <id> approve   # o "deny"
```

Reintenta la llamada una vez aprobada (la aprobación es válida 5 minutos para
la misma herramienta+objetivo).
