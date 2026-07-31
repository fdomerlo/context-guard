# Changelog

Todos los cambios notables en este proyecto serán documentados en este archivo.

El formato está basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/), y este proyecto adhiere a [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0] - 2026-07-31

### The state-guard merge

context-guard 2.0 folds state-guard into this repo: one process instead of two
diverging philosophies. state-guard's multi-change layout, phased
`plan → execute → verify` workflow, and cooperative approval model are ported
here on top of context-guard's atomic manifest and DAG-enforced transaction
core — the better architecture of the two, kept as the skeleton. state-guard
is retired; its repository now points here.

### Core fixes (audited bypasses closed)

- `begin` now validates `lock_phase` before starting a phase. Previously the
  DAG was only checked on `commit`, so an agent that never committed was never
  stopped from working a phase it was never authorized to start.
- Orphaned session locks (lockfile present, no metadata) now age off the
  file's own mtime instead of deadlocking forever.
- A write lock held by a live process is no longer stolen by age alone; a hard
  cap (10x the normal TTL) still recovers one abandoned by a reused PID.
- Task claims carry a lease; `next-task` reclaims expired ones and logs the
  takeover, `doctor --fix` releases claims whose owning PID is gone.
- `release` / `release-task` now require `--agent-id` (or an explicit
  `--force`, logged in the manifest) — an anonymous release could previously
  free a lock or claim it did not own.
- Exit codes are unified across the whole CLI: `0` OK, `1` GENERIC, `2`
  LOCK_HELD, `3` LOCK_CONTENDED, `4` VALIDATION, `5` BAD_TRANSITION, `6`
  APPROVAL_REQUIRED. `--format json` is available on every command.

### Multi-change

- State moves from a single `.context-guard/manifest.json` to
  `.context-guard/changes/{name}/`, so several changes can be planned,
  executed, and locked independently in the same project.
- New commands: `cg new <name>`, `cg list`, `cg archive --change <name>`.
- `cg migrate` converts both legacy layouts (state-guard's `state.ini` and
  context-guard 1.x's flat directory) in place, idempotently.
- Every command accepts `--change`; with several changes active and no flag,
  commands report the ambiguity and name them — never guess the first one
  alphabetically, the bug both predecessor repos shipped with.

### Human approval gate

- `cg approve --change <name> [--by <who>] [--hotfix --reason "<text>"]`
  records a human sign-off in the manifest. `commit --next-phase EXECUTE`
  refuses without one (`APPROVAL_REQUIRED`, exit 6). The approval is consumed
  by the commit it authorizes, so a later iteration of the plan needs a new
  one.
- `--hotfix` is the audited door out of the pipeline: it requires a reason,
  jumps straight to EXECUTE, and records PLAN as skipped rather than
  completed.
- The gate is cooperative by construction — see Threat Model in the README.
  The hard control is your harness's permission prompt on `cg approve`,
  documented per host in `adapters/*/PERMISSIONS.md`. `approve` is
  deliberately not exposed over MCP, for the same reason.

### Pre-commit hook, promoted

- Reads the multi-change layout (previously blind to it, and blocking every
  large commit regardless of protocol state).
- File threshold is configurable via `hook.file_threshold` in the manifest or
  `CONTEXT_GUARD_FILE_THRESHOLD` (env wins); the strictest configured value
  applies across changes.
- Files staged outside `files_in_scope` on an executing change now warn, never
  block. Output is in English. The audited bypass
  (`CONTEXT_GUARD_BYPASS=1 CONTEXT_GUARD_BYPASS_REASON=...`) is unchanged.

### Phases and adapters

- `phases/{plan,execute,verify}.md`, ported from state-guard, translated to
  English, trimmed, and integrated with `[PENDING]` and `cg approve`.
- Thin per-harness adapters in `adapters/{claude-code,opencode,antigravity}/`
  plus `install.sh`. Each documents its own permission configuration for
  `cg approve` in `PERMISSIONS.md`; OpenCode and Antigravity are marked
  unverified — ported but never run against a real host.
- `AGENTS.md` rewritten to under 100 lines as the single contract an agent
  loads.

### MCP server

- Gains the four read tools promised since F3: `get_status`, `next_task`,
  `check_completion`, `validate`, alongside the existing transactional four.
- `approve` is not an MCP tool — see Threat Model.

### Packaging

- `mcp` dependency pinned with an upper bound (`>=1.0.0,<2.0.0`).
- `requires-python = ">=3.10"`, tested in CI across 3.10–3.13.
- `cg` ships as a short entry point alongside `context-guard`.
- MIT license added.

---

## [1.2.0] - 2026-07-28

### 🔒 Git Hard Gate (Pre-Commit Hook)

- Implementado un hook de pre-commit en Git (`.githooks/pre-commit`) que rechaza commits si se modifican más de 2 archivos sin una transacción de `context-guard` activa.
- Evita cambios grandes al repositorio que esquiven el protocolo `PLAN → EXECUTE → VERIFY`.
- Soporta bypass de emergencia usando `CONTEXT_GUARD_BYPASS=1` con registro automático en `.context-guard/bypass.log`.

### 📦 Corrección de Namespace de Paquete

- Se renombró el directorio fuente de `scripts/` a `context_guard/` para evitar colisiones globales en Python, estandarizando el módulo con el nombre de la herramienta.
- Se actualizaron las importaciones internas para usar referencias relativas (`from .X import Y`) dentro del submódulo `guard`, desacoplándolo del nombre del paquete raíz.
- Se actualizó el entrypoint en `pyproject.toml` para reflejar la nueva estructura: `context_guard.mcp_server:main`.

---

## [1.1.0] - 2026-07-28

### 🏗️ Scaffolding Automático de Artefactos

- **`_scaffold_artifacts(context_path)`** en `transaction.py`:
  - Al iniciar una transacción `PLAN` con `begin_transaction`, se auto-generan en `.context-guard/` cinco plantillas Markdown si no existen previamente: `objective.md`, `snapshot.md`, `tasks.md`, `review-report.md` y `verify-report.md`.
  - Cada plantilla se inicializa con el marcador `[PENDING]` para guiar al LLM sobre qué campos deben completarse antes de avanzar de fase.

### 🚧 Compuertas Duras (Hard Gates) en `cmd_commit`

- Validaciones estrictas en Python antes de autorizar transiciones de fase (sin dependencia de system prompt):
  - **`PLAN` → `EXECUTE`**: Verifica que `objective.md` y `tasks.md` existan y no contengan `[PENDING]`. En caso contrario, retorna `EXIT_VALIDATION` con mensaje descriptivo.
  - **`VERIFY` → `ARCHIVE`**: Verifica que `review-report.md` y `verify-report.md` existan y no contengan `[PENDING]`. En caso contrario, retorna `EXIT_VALIDATION` con mensaje descriptivo.

### 📜 Docstrings MCP actualizados (`mcp_server.py`)

- `begin_transaction`: Documenta el auto-scaffolding de los 5 archivos `.md` en la fase `PLAN`.
- `commit_transaction`: Documenta las reglas de validación estricta de Hard Gates por archivo y por fase, exponiendo las restricciones al LLM vía schema de herramientas.

### ✅ Mejoras en la Suite de Pruebas

- Nuevos casos de prueba en `test_transaction.py`:
  - `test_begin_valid_phase`: verifica la creación de los 5 artefactos scaffold con contenido `[PENDING]`.
  - `test_commit_hard_gate_plan_to_execute_pending`: valida el rechazo cuando los archivos de `PLAN` contienen marcadores.
  - `test_commit_hard_gate_verify_to_archive_pending`: valida el rechazo cuando los archivos de `VERIFY` contienen marcadores.
- Actualización de `test_phases.py` y `test_mcp_server.py` para preparar artefactos válidos antes de cada `commit_transaction`.
- Suite completa: **111 tests, 0 fallos**.

---

## [1.0.0] - 2026-07-28

### 🚀 Novedades y Características Principales

- **Servidor MCP Nativo (Model Context Protocol):**
  - Exposición de herramientas nativas sobre transporte `stdio`: `begin_transaction`, `commit_transaction`, `rollback_transaction` y `save_checkpoint`.
  - Integración transparente con clientes MCP como Claude Desktop, Antigravity, OpenCode y Cursor.

- **Pipeline Transaccional de 3 Estados (DAG):**
  - Implementación estricta de la secuencia de fases: `PLAN` $\longrightarrow$ `EXECUTE` $\longrightarrow$ `VERIFY` $\longrightarrow$ `ARCHIVE`.
  - Validación de transiciones permitidas para evitar saltos arbitarios de fase por parte del LLM.

- **Atomicidad y Mecanismo de Rollback:**
  - Creación automática de snapshots del `manifest.json` al ejecutar `begin_transaction`.
  - Herramienta `rollback_transaction` para restaurar el estado exacto anterior en caso de fallos en ejecución o tests no superados en la fase `VERIFY`.

- **Control de Concurrencia y Write Lock (OS-level):**
  - Implementación de locks de sesión y mutexes de escritura a nivel de sistema operativo (`O_CREAT|O_EXCL`) para prevenir condiciones de carrera (*TOCTOU*) entre agentes o sesiones simultáneas.
  - Detección automática y recuperación de locks huérfanos (*stale locks*) mediante verificación de PID y timestamping.

- **Anclaje de Rutas Absolutas por Proyecto:**
  - Persistencia aislada y transparente dentro del directorio raíz de cada proyecto (`<PROJECT_ROOT>/.context-guard/`), eliminando la contaminación del directorio personal (`$HOME`).

- **Empaquetado Estándar y Soporte Zero-Install (`uvx`):**
  - Incorporación de `pyproject.toml` con backend `hatchling` y punto de entrada executable `context-guard`.
  - Soporte de ejecución en una sola línea sin clonación previa utilizando `uvx git+https://github.com/fdomerlo/context-guard.git`.

- **Optimización de Tool Discovery (i18n):**
  - Docstrings y auto-resúmenes estandarizados en inglés para maximizar la adherencia de modelos de lenguaje en el descubrimiento y selección de herramientas.
