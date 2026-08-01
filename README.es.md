# Context Guard

[![CI](https://github.com/fdomerlo/context-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/fdomerlo/context-guard/actions/workflows/ci.yml)

**La capa de memoria transaccional para agentes de codificación con IA — tu contexto sobrevive a crashes, compactación y pérdida de sesión.**

*[Read in English](README.md)*

---

## El problema

Las sesiones largas de agentes se degradan. Deriva de contexto, "lost in the
middle", alucinación de completitud (el agente cree haber terminado antes de
verificar nada) — y la que realmente pierde trabajo: un crash o una
compactación a mitad de tarea que deja el repositorio a medio editar, sin
forma de volver atrás.

context-guard no es otro framework de agentes y no escribe código. Es una
máquina de estados pequeña y determinista que se ubica entre un agente y un
proyecto: un manifest en disco que sobrevive a que el proceso del agente
termine, un pipeline estricto `PLAN → EXECUTE → VERIFY → ARCHIVE` del que el
agente no puede saltarse fases, y un log de transacciones que se puede
revertir. Si la sesión muere, el manifest es lo que la próxima sesión lee
para retomar exactamente donde quedó la anterior — esa persistencia, no la
forma del pipeline, es el punto.

## Inicio rápido

Cinco comandos: planear un cambio, conseguir el visto bueno de un humano,
avanzar a ejecución, reclamar una tarea, y chequear el estado.

```bash
# (1) inicia un change — esto arranca PLAN y scaffoldea los artefactos
cg new redis-cache

# completa el plan — lo escribe un agente, no vos
cat > .context-guard/changes/redis-cache/objective.md <<'EOF'
# Objective: Add Redis caching
Cache the top-N query results behind a 60s TTL.
EOF
cat > .context-guard/changes/redis-cache/tasks.md <<'EOF'
- [ ] 1.1 Add the redis client dependency
- [ ] 1.2 Wrap the query path with a cache lookup
EOF

# (2) un humano revisa objective.md y tasks.md, y aprueba
cg approve

# (3) la aprobación registrada desbloquea EXECUTE
cg commit --next-phase EXECUTE

# (4) reclama la próxima tarea de forma atómica — seguro con varios agentes a la vez
cg next-task

# (5) rehidratación en un solo paso tras un crash, una compactación, o una sesión nueva
cg status
```

Cada línea de arriba corre tal cual está escrita contra un directorio nuevo;
nada acá es un resumen ilustrativo.

## Instalación

**Zero-install, vía `uvx`** — agregá esto a la config de tu cliente MCP
(Claude Desktop, Antigravity, Cursor: `claude_desktop_config.json` /
`mcp-settings.json`; OpenCode: `~/.config/opencode/opencode.jsonc`):

```jsonc
{
  "mcpServers": {
    "context-guard": {
      "command": "uvx",
      "args": ["git+https://github.com/fdomerlo/context-guard.git"]
    }
  }
}
```

**Solo CLI**, para el binario `cg` sin cliente MCP:

```bash
uv pip install git+https://github.com/fdomerlo/context-guard.git
```

**Local, editable**, para desarrollo:

```bash
git clone https://github.com/fdomerlo/context-guard.git
cd context-guard && uv venv && uv pip install -e .
git config core.hooksPath .githooks   # activa el gate de pre-commit de más abajo
```

Para instalar los slash commands y los permisos de tu harness, corré
`cg setup` una vez por máquina — ver
[Adapters](#adapters-y-configuración-de-permisos) más abajo. Las fases las
escribe `cg new` en cada proyecto.

## Cómo funciona

```
PLAN  →  EXECUTE  →  VERIFY  →  ARCHIVE
```

Cada change (`.context-guard/changes/<nombre>/`) avanza por este pipeline
fase por fase, forzado por código, no por convención:

- **`begin`** se niega a iniciar una fase que no sea el `lock_phase` del
  manifest — el DAG se chequea antes de que arranque el trabajo, no solo
  cuando se declara terminado.
- **`commit`** valida que los artefactos de la fase (`objective.md` +
  `tasks.md` para PLAN, `review-report.md` + `verify-report.md` para VERIFY)
  no tengan ningún marcador `[PENDING]` restante antes de avanzar
  `lock_phase`.
- **`begin` sobre un PLAN nuevo** scaffoldea automáticamente cinco archivos
  markdown — `objective.md`, `snapshot.md`, `tasks.md`, `review-report.md`,
  `verify-report.md` — cada uno empezando como `[PENDING]`, así el agente
  edita plantillas en vez de inventar una forma desde cero.
- **`rollback`** restaura exactamente el snapshot del manifest tomado cuando
  arrancó la fase.
- **Los locks de sesión y de escritura** son a nivel de sistema operativo
  (`O_CREAT|O_EXCL`), con detección de staleness verificada por liveness, así
  dos agentes sobre el mismo change no compiten en silencio.
- **Los claims de tareas** tienen un lease (`claim-task` / `next-task` /
  `doctor --fix`), así varios agentes pueden trabajar un mismo change en
  paralelo sin que dos tomen la misma tarea.
- **`--change <nombre>`** acota cada comando a un change. Si hay varios
  changes activos y no se pasa `--change`, es un error que los nombra a
  todos — nunca adivina "el primero" en silencio.

## Threat Model

Leé esto antes de confiar en context-guard para algo que realmente te
importa.

El enforcement del pipeline (`begin`/`commit` validando el DAG y los
artefactos) es código real, no una sugerencia de system prompt — un agente
que usa la herramienta `cg` no puede saltarse una fase por accidente ni
avanzar con artefactos en `[PENDING]`. Pero ese enforcement es
**cooperativo**: solo aplica a un agente que llame a `cg` en primer lugar.
Un agente con shell puede escribir directamente a `manifest.json`, o
simplemente no usar la herramienta, y nada en el proceso lo detiene.

El único comando explícitamente **humano** es `cg approve`. Registra el
visto bueno que `commit --next-phase EXECUTE` exige. El nombre que anota
(`--by`, que por defecto toma el usuario del sistema) es **metadata de
auditoría, no autenticación**: dice a quién preguntarle por esa aprobación
más adelante, y un agente podría pasar cualquier string. El comando en sí
es tan cooperativo como el resto: un agente con shell puede correr
`cg approve` él mismo, y nada en `cg` lo impide. El control duro real no
vive en `cg` en absoluto — vive en el permission prompt de tu harness sobre
el comando `cg approve`, configurado por host en
`docs/adapters/*/PERMISSIONS.md`.
Ese prompt corre afuera del proceso del agente, que es el único lugar donde
puede vivir un control que no depende de la cooperación del agente.
`approve` deliberadamente no está expuesto como tool de MCP, por la misma
razón: una tool de MCP es un canal que el permission prompt no ve.

El hook de pre-commit es la única capa que corre enteramente afuera del
proceso del agente — git lo invoca sin importar qué haya decidido hacer el
agente — pero es un chequeo de perímetro sobre cantidad de archivos, no una
garantía de corrección, y viene con un bypass auditado
(`CONTEXT_GUARD_BYPASS=1`) a propósito: un bloqueo incondicional termina en
`--no-verify`, que no deja ningún rastro.

## Referencia del CLI

| Comando | Propósito |
|---|---|
| `cg new <nombre> --context <ruta>` | Crea un change y arranca PLAN |
| `cg list --context <ruta>` | Lista los changes activos y su fase |
| `cg begin --phase <FASE> --context <ruta>` | Inicia una transacción para la fase dada |
| `cg approve [--by <quién>] [--hotfix --reason "<texto>"]` | Solo humano: registra el visto bueno que `commit` exige para entrar a EXECUTE |
| `cg commit --next-phase <FASE> --context <ruta>` | Valida los artefactos de la fase actual y avanza el DAG |
| `cg rollback --context <ruta>` | Restaura el snapshot del manifest tomado en `begin` |
| `cg checkpoint --summary "<texto>" --context <ruta>` | Persiste un resumen de sesión para retomar en caliente |
| `cg claim --context <ruta>` | Adquiere el lock de sesión, tomando uno stale si hace falta |
| `cg release --context <ruta> --agent-id <id>` | Libera el lock de sesión (con chequeo de ownership) |
| `cg claim-task --task-id <id> --context <ruta>` | Reclama una tarea con lease |
| `cg release-task --task-id <id> --agent-id <id> --context <ruta>` | Libera una tarea reclamada |
| `cg next-task --context <ruta>` | Reclama y devuelve la próxima tarea pendiente sin reclamar |
| `cg check-completion --context <ruta>` | Conteo determinista de tareas tildadas |
| `cg validate --context <ruta>` | Lint de los artefactos de sesión: existencia, tamaño, idioma |
| `cg status --context <ruta>` | Resumen en un solo paso para rehidratar tras perder contexto |
| `cg doctor --context <ruta> [--fix]` | Diagnostica (o repara) claims y locks stale |
| `cg archive --context <ruta>` | Mueve un change completado a `changes/archive/` |
| `cg migrate --context <ruta>` | Convierte in situ un layout legacy de state-guard o context-guard 1.x |

Todo comando acepta `--format json`. `cg` y `context-guard` son el mismo
binario bajo dos entry points.

## Servidor MCP

`context-guard-mcp` expone ocho tools sobre stdio — las cuatro
transaccionales más cuatro de solo lectura para hosts sin shell (Claude
Desktop es el caso para el que existen):

`begin_transaction`, `commit_transaction`, `rollback_transaction`,
`save_checkpoint`, `get_status`, `check_completion`, `validate`, `next_task`.

`cg approve` no es una tool de MCP. Ver Threat Model más arriba.

## Multi-change

El estado vive bajo `.context-guard/changes/<nombre>/`, un manifest y un
juego de locks por change, así varios changes se pueden planear y ejecutar
de forma independiente en el mismo proyecto. `cg new <nombre>` crea uno;
`cg list` muestra los activos; `cg archive` mueve uno terminado a
`changes/archive/`. `cg migrate` convierte ambos layouts legacy — el
`state.ini` de state-guard y el `.context-guard/` plano de context-guard
1.x — in situ y de forma idempotente, preservando cualquier aprobación
humana registrada que encuentre.

## Hook de pre-commit

`.githooks/pre-commit` rechaza commits que tocan más de un umbral de
archivos cuando ningún change muestra que el protocolo estuvo activo (una
fase completada o una transacción abierta). Activalo una vez por clon con
`git config core.hooksPath .githooks`.

- **Umbral**: `hook.file_threshold` en el manifest de un change, o la
  variable de entorno `CONTEXT_GUARD_FILE_THRESHOLD`, que gana sobre el
  manifest. Con varios changes activos, aplica el valor configurado más
  estricto.
- **`files_in_scope`**: los archivos staged fuera del scope declarado de un
  change en EXECUTE generan un warning, nunca un bloqueo.
- **Bypass**: `CONTEXT_GUARD_BYPASS=1 CONTEXT_GUARD_BYPASS_REASON='...' git
  commit ...`. Todo bypass queda anotado en `.context-guard/bypass.log` con
  timestamp y la lista de archivos — la puerta sigue abierta, pero nadie
  pasa por ella sin quedar registrado.

## Códigos de salida

| Código | Nombre | Significado |
|---|---|---|
| `[0]` | `EXIT_OK` | Éxito. |
| `[1]` | `EXIT_GENERIC` | Manifest corrupto, o no hay sesión en este context/change. |
| `[2]` | `EXIT_LOCK_HELD` | Otro agente tiene el lock o el claim. Reintentable con backoff. |
| `[3]` | `EXIT_LOCK_CONTENDED` | Perdiste la carrera de takeover de un lock stale. Reintentable. |
| `[4]` | `EXIT_VALIDATION` | Artefacto faltante, `[PENDING]` restante, artefacto demasiado largo, o texto que no es inglés. |
| `[5]` | `EXIT_BAD_TRANSITION` | La fase pedida no es el `lock_phase` actual del DAG. No reintentar. |
| `[6]` | `EXIT_APPROVAL_REQUIRED` | `commit` a EXECUTE sin un `cg approve` registrado. Solo lo resuelve un humano. |

## Adapters y configuración de permisos

Dentro del paquete, en `context_guard/_data/hosts/{claude-code,opencode,
antigravity}/`, viven wrappers finos por harness — cada uno apunta a
`phases/{plan,execute,verify}.md` en vez de duplicarlos. Cómo poner
`cg approve` detrás del permission prompt de cada harness está documentado en
[docs/adapters/](docs/adapters/), un `PERMISSIONS.md` por host, junto con el
checklist de smoke-test manual en
[docs/adapters/VERIFY.md](docs/adapters/VERIFY.md).
`cg setup` instala el que corresponde a cada host detectado. Los
adapters de OpenCode y Antigravity están portados de state-guard y cubiertos
solo por tests estáticos — no se corrieron contra un host real de ninguno de
los dos.

## Cómo se compara

context-guard no es una herramienta que escribe specs, y no pretende serlo.

| | context-guard | spec-kit | Kiro | `AGENTS.md` pelado |
|---|---|---|---|---|
| Genera specs/planes a partir de un prompt | No | Sí | Sí | No |
| Experiencia nativa de IDE | No (CLI + MCP) | Depende del host | Sí | No |
| Fuerza el orden de fases en código, no en prosa | **Sí** | No | Parcial | No |
| Manifest atómico, sobrevive a un crash a mitad de fase | **Sí** | No | No | No |
| Locking a nivel de OS para agentes concurrentes | **Sí** | No | No | No |
| Gate de aprobación humana antes de ejecutar | **Sí** | No | No | No |

Lo que hacemos y ellos no: enforcement en runtime de una máquina de estados
que sobrevive al proceso del agente. Lo que ellos hacen y nosotros no: todo
lo referido a convertir un prompt en un buen spec en primer lugar. Usá
context-guard junto con cualquiera de ellos que ya te genere el
`objective.md` — está diseñado para consumir uno, no para escribirlo.

## Desarrollo

```bash
git clone https://github.com/fdomerlo/context-guard.git
cd context-guard && uv venv && uv pip install -e .
python -m unittest discover -s tests
```

Framework: `unittest`. Cada fix se entrega con un test adversarial que
reproduce el bypass que cierra; ver `tests/test_adversarial_*.py` para el
patrón. Sin fixtures en disco fuera de `tempfile.mkdtemp()`.

## Licencia

MIT — ver [LICENSE](LICENSE).
