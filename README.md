# TraceDaAI

Un "AI Firewall / AI Permission Manager" personal: audita y controla qué hacen
los agentes de IA (Claude Code, Cursor, Copilot, servidores MCP, etc.) en tu
máquina — archivos, comandos, red — con reglas allow/ask/block, y lo muestra
en un dashboard único.

## Modelo de seguridad y límites (léelo antes de confiar en esto)

TraceDaAI Fase 1 es **cooperativo**, no un enforcement real a nivel de sistema
operativo. Funciona interceptando protocolos que el propio agente respeta
voluntariamente: los hooks de Claude Code (`PreToolUse`/`PostToolUse`) y el
tráfico JSON-RPC de MCP que pasa por el proxy. Esto significa que:

- Un proceso que no pase por esos dos puntos (un script arbitrario, un
  binario que ignore hooks, tráfico MCP que no pase por el proxy) **no está
  controlado** por TraceDaAI.
- No hay verificación de que el propio Claude Code respete la decisión del
  hook — se apoya en el contrato documentado de `hookSpecificOutput`.
- El enforcement real e infalible (bloquear a nivel de kernel el acceso a un
  archivo sin importar qué proceso lo pida) es la Fase 4 del roadmap
  (Endpoint Security en macOS / eBPF en Linux / ETW+minifilter en Windows) y
  **todavía no existe**.

En resumen: útil para auditoría y para frenar acciones accidentales o
descuidadas de agentes que cooperan con el protocolo (que es el caso normal
de Claude Code, Cursor, servidores MCP, etc.), pero no es una barrera de
seguridad contra un agente adversarial que decida evadirla.

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
comando del servidor real, apúntalo a TraceDaAI:

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

### Notificaciones de escritorio

Cada vez que una acción se bloquea o se crea una aprobación pendiente,
TraceDaAI envía una notificación nativa del sistema (macOS vía `osascript`,
Linux vía `notify-send`; Windows aún no implementado). Prueba que funcionen:

```bash
tracedaai notify-test
```

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
