# Plan Maestro — Consolidación state-guard + context-guard → context-guard 2.0

## 0. Decisiones fundacionales

### 0.1 Nombre y repo: se queda `context-guard`

Razones: (a) el repo base ya es context-guard por mérito técnico propio, y renombrar resetea historia git, links y cualquier tracción sin ganar nada; (b) el nombre describe exactamente el diferencial que identificamos — el contexto sobrevive; (c) "state-guard" muere como repo activo: un último commit con README apuntando al sucesor ("Superseded by context-guard 2.0 — the transactional core of this project lives on there") y archivado en GitHub. No lo borres: es historial de diseño y lo citás en el post de lanzamiento.

- Binario CLI: `cg` (además del entry point largo `context-guard`).
- MCP: `context-guard-mcp` (se mantiene, ver 0.5).
- Versión: **2.0.0** — el salto de major comunica la fusión.

### 0.2 Idioma: inglés para todo lo que ve una máquina o un extraño

- Código, comentarios, mensajes de error, artefactos de sesión (`objective.md`, `tasks.md`...), `AGENTS.md`, fases: **inglés**. context-guard ya lo enforcea en `cmd_validate` (language boundary) — se mantiene y se extiende a las fases portadas.
- `README.md` en inglés como primario + `README.es.md` completo.

### 0.3 Toolchain

- Python **>=3.10**. Probar en CI contra 3.10–3.13.
- `uv` para todo (venv, install, publish). `hatchling` se queda como backend.
- Tests: **unittest se queda**. Regla: cada fix de esta migración entra con su test adversarial en unittest.
- Dependencias: `mcp>=1.0.0,<2.0.0` (el fix del pin es literalmente el primer commit de la Fase 0). Ninguna otra dependencia obligatoria. Cero deps opcionales tipo watchdog: el daemon murió.
- CI desde la Fase 0: GitHub Actions, `python -m unittest discover -s tests` en la matriz de versiones. Un proyecto cuya promesa es determinismo no puede no tener CI.

### 0.4 Qué vive, qué muere, qué se transforma

| Pieza | Origen | Destino | Razón |
|---|---|---|---|
| Paquete modular (`paths/errors/manifest/locking/transaction/commands/cli`) | context-guard | **VIVE** — es el esqueleto | Mejor arquitectura de los dos, un solo proceso |
| `manifest.json` atómico (tmp+rename) | context-guard | **VIVE** | state.ini in-place era corruptible |
| Rollback con snapshot | context-guard | **VIVE** | El único rollback que hace rollback |
| `claim` atómico, `doctor`, caps de artefactos, language boundary | context-guard | **VIVEN** | |
| Pre-commit hook con bypass auditado | context-guard | **VIVE y se promueve** (ver 0.6) | El mejor gate que existe entre los dos repos |
| Multi-change (`changes/{name}/`) | state-guard | **SE PORTA** | La carencia más seria de context-guard |
| Fases `plan/execute/verify.md` | state-guard | **SE PORTAN** recortadas y en inglés | El "cómo trabajar" que context-guard no tiene |
| Exit codes diferenciados | ambos (divergen) | **SE UNIFICAN** (tabla en 1.4) | Hoy el código 2 significa cosas distintas en cada repo |
| Gate criptográfico /dev/tty + token SHA-256 | state-guard | **MUERE** | Rodeable en 2 comandos; teatro. Lo reemplaza 0.6 |
| Daemon Agent Hooks + watchdog | state-guard | **MUERE** | Feature isla con 3 bugs; lo dan los hooks nativos del harness |
| sg.py (segunda capa CLI por subprocess) | state-guard | **MUERE** | cli.py de context-guard ya es el único entry |
| Skills/slash-commands (`/continue`, `/status`, `/new`...) | state-guard | **SE TRANSFORMAN** en adapters finos (ver 0.7) | Valiosos como UX, no como 80KB de prosa |
| `_shared/*.md` (memory-guard, convention, capabilities...) | state-guard | **MUEREN** como archivos; lo esencial se condensa en un `AGENTS.md` de <100 líneas | El costo de protocolo era el problema |
| MCP server | ambos (filosofías opuestas) | **VIVE, decisión única** (ver 0.5) | |
| `hotfix` bypass | state-guard | **SE TRANSFORMA**: `cg approve --change X --hotfix --reason "..."` — un flag, no un flujo paralelo de 150 líneas | La razón queda auditada en el manifest |

### 0.5 MCP: una sola filosofía, elegida de una vez

Los dos repos documentan principios opuestos (state-guard excluye lo transaccional del MCP; context-guard lo expone). Decisión: **se mantiene el MCP de context-guard (transaccional completo) y se le agregan las tools de lectura** (`get_status`, `next_task`, `check_completion`, `validate`). Justificación honesta: la separación de state-guard pretendía que el MCP no pudiera aprobar planes — pero como demostramos, esa garantía nunca existió (el agente con bash rodea todo). Fingir que el canal MCP es "el seguro" era parte del teatro. El enforcement real vive en 0.6; el MCP es solo un transporte, y castrarlo no protege nada. Para hosts sin shell (Claude Desktop) el MCP completo es además la única vía de uso. Documentalo así, con esas palabras, en el README.

### 0.6 El modelo de enforcement (esto reemplaza al gate criptográfico)

Tres capas, cada una honesta sobre lo que garantiza:

1. **Protocolo cooperativo (código):** `begin` valida `lock_phase` (el fix central), `commit` valida artefactos sin `[PENDING]`, transiciones del DAG estrictas. Garantiza: un agente que usa la herramienta no puede *equivocarse* de fase. No garantiza: que no la rodee.
2. **Aprobación humana (`cg approve`):** comando simple que escribe `approval: {by, at, hotfix?, reason?}` en el manifest; `commit PLAN→EXECUTE` lo exige. Sin TTY, sin tokens, sin hash — funciona en CI con `--by ci-pipeline`. La garantía dura no la da el comando: la da la **configuración del harness**: en Claude Code, `cg approve` va a la lista de permisos "ask" (`settings.json → permissions`), con equivalentes documentados para OpenCode y Antigravity en `adapters/`. Ese sí es un punto de control fuera del proceso del agente. El README lo dice sin vueltas: *"cg approve is cooperative by itself; pair it with your harness's permission prompt for hard enforcement."*
3. **Pre-commit hook (perímetro git):** el hook de context-guard, promovido: umbral configurable, se agrega chequeo de que si hay un change activo en EXECUTE, los archivos staged estén dentro de `files_in_scope` (warning, no bloqueo, para no pelearte con tu propio flujo). El bypass con `CONTEXT_GUARD_BYPASS=1` + razón logueada se queda tal cual — es la mejor idea de gobernanza de los dos repos.

Sección obligatoria del README: **Threat model** — dos párrafos que digan explícitamente qué es cooperativo y qué es duro. Esa honestidad es diferenciación: ningún framework comparable la tiene, y te inmuniza contra el issue #1 que habría hundido a state-guard.

### 0.7 Estructura final del repo

```
context-guard/
├── context_guard/
│   ├── __init__.py
│   ├── paths.py            # + resolución de changes/{name}/
│   ├── errors.py           # exit codes unificados
│   ├── manifest.py         # atómico, schema v3 (con "schema_version": 3)
│   ├── locking.py          # fixes de 1.2
│   ├── transaction.py      # begin valida lock_phase; approve
│   ├── commands.py         # + init/list/archive por change, migrate
│   ├── cli.py              # único dueño de sys.exit/print; --format json
│   └── mcp_server.py       # transaccional + lectura, pin corregido
├── phases/
│   ├── plan.md             # ~5KB, inglés
│   ├── execute.md          # ~4KB
│   └── verify.md           # ~5KB (archive = paso final de verify, como en state-guard)
├── adapters/
│   ├── claude-code/        # slash commands .claude/commands/*.md + settings de permisos recomendados
│   ├── opencode/           # stubs equivalentes
│   ├── antigravity/
│   └── install.sh          # detecta host, instala el adapter que corresponde
├── hooks/
│   └── pre-commit          # activación: git config core.hooksPath
├── tests/                  # 109 existentes + adversariales nuevos
├── AGENTS.md               # <100 líneas, el único contrato que carga el agente
├── README.md / README.es.md / CHANGELOG.md / LICENSE (MIT)
└── pyproject.toml
```

Los slash commands de state-guard (`/new`, `/continue`, `/status`, `/approve`...) renacen como archivos de comando *nativos de cada harness* en `adapters/` — 10-20 líneas cada uno que dicen "load phases/X.md and follow it for change {arg}". El contenido pesado vive una sola vez en `phases/`; los adapters solo apuntan. Así el mismo protocolo corre en los tres hosts sin triplicar prosa.

---

## 1. Especificación técnica de los cambios core

### 1.1 Fix central — `begin` valida el DAG

En `transaction.py:cmd_begin`, después de cargar el manifest:

```python
lock_phase = m.get("lock_phase", "PLAN")
if phase != lock_phase:
    return CommandResult(
        f"FAIL|PHASE_NOT_AUTHORIZED|requested={phase}|lock_phase={lock_phase}",
        EXIT_BAD_TRANSITION,
    )
```

Test adversarial obligatorio: manifest fresco → `begin EXECUTE` debe fallar con exit 5. Este test es la razón de ser del proyecto; va primero.

### 1.2 Fixes de locking (los tres verificados en las auditorías)

1. **Lock huérfano sin metadata** (`locking.py:acquire`): si `acquired_at` es None y el lockfile existe, usar `os.path.getmtime(p["lock"])` como fallback para el cálculo de stale. Test: `touch .lock` sin manifest → segundo `claim` con TTL vencido por mtime debe hacer takeover, no LOCK_HELD eterno.
2. **Robo de write-lock a proceso vivo** (`locking.py:_is_write_lock_stale`): la edad solo declara stale si el PID además no responde, **o** si supera un hard cap de 10× `WRITE_LOCK_MAX_AGE` (protección contra PID reuse). Test: lock de proceso vivo con 31s no es stale; con PID muerto sí.
3. **Task claims con lease:** cada claim guarda `lease_seconds` (default 1800). `next-task` trata como disponibles los claims vencidos (re-claim con log del takeover en el manifest). `doctor --fix` libera claims de PIDs muertos. Esto destraba el escenario swarm que hoy queda en deadlock silencioso.
4. **Ownership real:** `next-task` devuelve el `agent_id` en su salida (`SUCCESS|NEXT_TASK|{id}|{agent_id}|{desc}`) y en el JSON. `release-task` sin `--agent-id` pasa a ser **error** salvo `--force` (que se loguea en el manifest con timestamp). `release` de sesión valida owner con la misma regla.

### 1.3 Multi-change

- Layout: `.context-guard/changes/{name}/` con `manifest.json`, artefactos y locks propios; `.context-guard/changes/archive/` para completados. `get_paths(context, change)` gana el segundo parámetro.
- Todos los comandos ganan `--change` (default: si hay exactamente un change activo, se usa; si hay varios, error pidiendo explicitarlo — nunca "el primero alfabético", ese bug ya lo tuviste en el git hook de state-guard).
- Nuevos comandos: `cg new <name>` (init + scaffold), `cg list`, `cg archive --change <name>`.
- `cg migrate`: detecta y convierte los dos layouts legacy — `state.ini` v2 de state-guard (parsear INI → manifest.json v3) y el `.context-guard/` plano de context-guard 1.x (mover a `changes/default/`). Idempotente, con test por cada layout de origen.

### 1.4 Exit codes unificados (schema v3)

| Código | Nombre | Significado |
|---|---|---|
| 0 | OK | |
| 1 | GENERIC | manifest corrupto, sesión inexistente |
| 2 | LOCK_HELD | lock/claim activo de otro agente — reintentable con backoff |
| 3 | LOCK_CONTENDED | perdiste la carrera de takeover — reintentable |
| 4 | VALIDATION | artefacto faltante/[PENDING]/muy largo/idioma |
| 5 | BAD_TRANSITION | fase no autorizada por el DAG — **no** reintentar |
| 6 | APPROVAL_REQUIRED | falta `cg approve` — solo el humano lo resuelve |

`--format json` en todos los comandos (ya existe la infraestructura en cli.py) — es lo que consumen los tres harnesses.

### 1.5 `cg approve`

```
cg approve --change <name> [--by <who>] [--hotfix --reason "<text>"]
```
Escribe `approval` en el manifest. `commit --next-phase EXECUTE` exige `approval` presente (o `hotfix: true`, que además setea `lock_phase` directo a EXECUTE saltando PLAN — con la razón persistida). El approval se consume en el commit (se mueve a `approval_history[]`) para que no se reutilice entre iteraciones del plan.

---

## 2. Plan de ejecución por fases (una fase = una sesión de agente = un PR)

Cada fase lista sus criterios de aceptación; no se cierra la fase sin que la suite completa pase y sin mi audit del diff.

**F0 — Preparación (Sonnet, ~1h de agente)**
Branch `v2` en context-guard. Fix del pin mcp (`>=1.0.0,<2.0.0`). CI de GitHub Actions con matriz 3.10–3.13. `requires-python = ">=3.10"`. README de state-guard reemplazado por el aviso de sucesión + repo archivado en GitHub (esto último lo hacés vos, es un click).
*Acepta:* CI verde en el branch, `uvx git+...` instala y el MCP hace handshake.

**F1 — Core fixes + tests adversariales (Opus)**
Todo 1.1, 1.2 y 1.4. Regla de la fase: **el test adversarial se escribe primero y debe fallar contra el código actual** (RED→GREEN literal — los bypasses verificados en las auditorías son la especificación del test). Mínimo: bypass de lock_phase, deadlock de lock huérfano, robo de write-lock a vivo, release sin ownership, claim huérfano de PID muerto.
*Acepta:* los 5 adversariales + los 109 legacy verdes.

**F2 — Multi-change + migrate (Opus)**
Todo 1.3. Fixtures de migración: un `state.ini` real de state-guard y un `.context-guard/` 1.x real como archivos de test.
*Acepta:* dos changes en paralelo con locks independientes; `cg migrate` idempotente sobre ambos layouts.

**F3 — Fases + adapters (Sonnet)**
Portar `plan/execute/verify.md` de state-guard: traducir a inglés, recortar a ~4-5KB c/u (fuera: plantillas duplicadas que ya scaffoldea el código, el sub-flujo de gate viejo, referencias a `_shared/`), integrar con `[PENDING]` y `cg approve`. Escribir `adapters/{claude-code,opencode,antigravity}/` + `install.sh` (basate en el install.sh de state-guard, que ya detecta hosts — recortado). `AGENTS.md` nuevo (<100 líneas; el actual de context-guard es la base correcta, sumale la tabla de fases y el flujo approve).
*Acepta:* en un repo de juguete, `/new` + `/continue` completan un ciclo entero en Claude Code.

**F4 — Approve + hook promovido (Opus para el flow, Sonnet para docs)**
1.5 completo. Hook: umbral configurable vía manifest o env, chequeo soft de `files_in_scope`, mantener bypass auditado. Documentar la configuración de permisos por harness en cada adapter (para Claude Code: el snippet exacto de `settings.json`).
*Acepta:* test adversarial "commit a EXECUTE sin approve → exit 6"; hook rechaza y bypass loguea.

**F5 — Docs, branding, release (Sonnet)**
README EN con: pitch de una oración ("The transactional memory layer for AI coding agents — your context survives crashes, compaction, and session loss"), quickstart de 5 comandos, sección Threat Model (0.6), comparación honesta de una tabla contra spec-kit/Kiro/AGENTS.md-pelado ("qué hacemos que ellos no: runtime; qué hacen ellos que nosotros no: todo lo demás — úsanos juntos"). README.es.md espejo. CHANGELOG 2.0.0 citando la fusión. Publicar a PyPI con `uv publish`.
*Acepta:* vos leés el README como si fueras un extraño y no encontrás ninguna claim que las auditorías puedan falsar.

---

## Lo que deliberadamente queda FUERA de 2.0 (backlog, no scope)

- HMAC/firma de integridad del manifest (buena idea, no bloquea nada hoy).
- Tools MCP de solo-lectura extra más allá de las 4 básicas.
- Perfil "slim" para modelos débiles (recortá primero; medí después).
- Cualquier resurrección de hooks de filesystem.
- Telemetría, config.yaml elaborado, glosarios.
- `cg unarchive --change X`: hoy, si archivás por error, la recuperación es mover el directorio de `changes/archive/` a mano. No bloquea nada (el archive no borra, copia y después elimina el original), pero es una aspereza conocida.
- `--format json` con campos nombrados en lugar de `details` posicional (hoy el `agent_id` de `next-task` sale como `details[1]`).
- `--format` debe ir antes del subcomando (`cg --format json next-task ...`), no después. Trampa de UX preexistente para los tres harnesses.
