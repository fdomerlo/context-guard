---
type: readme
title: Context Guard
timestamp: 2026-07-02
tags:
  - skill
  - swarm-agent
description: Motor de persistencia transaccional y rehidratación de contexto para enjambres de agentes IA, agnóstico de modelo y de harness.
---

# Context Guard 🧠🛡️

**Motor de Persistencia Transaccional y Rehidratación de Contexto para Enjambres de Agentes**

Context Guard es una *skill* que dota a agentes efímeros de una memoria atómica persistente en el sistema de archivos, resolviendo saturación de tokens, deriva de contexto y pérdida de estado entre sesiones — sin depender del historial de chat.

El middleware (`guard.py`) es Python puro sobre stdlib, sin llamadas a ningún proveedor. Es agnóstico del **modelo** por diseño. No es agnóstico del **harness** de forma automática: cada orquestador (Antigravity, OpenCode, etc.) carga sus instrucciones globales desde un archivo distinto, así que el instalador necesita una rutina por target. Ver sección de instalación.

---

## 🎯 El Problema que Resuelve

1. **Saturación del Contexto:** recordar largos historiales agota tokens. El agente lee el estado actual desde `.context-guard/sessions/{context}/` en lugar de reconstruirlo desde el chat.
2. **Deriva de Estado:** el agente no edita `manifest.json` en crudo. Toda escritura pasa por `guard.py`, que aplica write atómico (`tmp` + `rename`) y un lock de exclusión mutua a nivel de sistema operativo (`O_CREAT|O_EXCL` sobre un lockfile dedicado) — no una simple bandera dentro del propio manifest, que es vulnerable a condiciones de carrera entre lectura y escritura (TOCTOU) cuando dos sesiones acceden en paralelo. Adicionalmente, un mutex de escritura (`with_write_lock`) serializa toda operación read-modify-write sobre el manifest, previniendo lost-updates entre agentes concurrentes.
3. **Arranque en Frío (Cold Boot):** inspecciona el proyecto (`package.json`, `pyproject.toml`, etc.) para auto-rehidratarse antes de actuar.

---

## 🚀 Instalación y Configuración

```bash
bash scripts/install.sh
```

Esto copia el núcleo (package `guard/`, shim `guard.py`, sub-skills) a `~/.agents/skills/context-guard/`.

### Inyección de Boot Prompt (Opcional)

Si deseas inyectar el *Boot Prompt* obligatorio en el archivo de instrucciones globales de tu orquestador, especifica el target (`antigravity` o `opencode`):

```bash
bash scripts/install.sh --target <antigravity|opencode>
```

El bloque inyectado es el mismo en ambos casos:

```markdown
## ACTIVE PERSISTENCE CONTRACT: context-guard

MANDATORY BOOTSTRAP — execute before responding to anything:
1. Call read_file on `~/.agents/skills/context-guard/SKILL.md`.
2. Follow every instruction in that file as your absolute state contract.
3. Check for an active context at `.context-guard/sessions/{context}/manifest.json`
   and act accordingly (Cold Boot, Resume, or Recovery).
```

---

## 📦 Arquitectura

```text
context-guard/
├── SKILL.md                          # Protocolo/contrato para el agente
├── skills/                           # Sub-skills invocables
│   ├── tasks/SKILL.md                # Desglose de tareas desde reference_docs
│   ├── review/SKILL.md               # Auditoría estática contra specs
│   └── verify/SKILL.md               # Verificación dinámica (tests + build)
├── scripts/
│   ├── install.sh                    # Instalador multi-target
│   ├── guard.py                      # Shim CLI (preserva invocación original)
│   └── guard/                        # Package modular (Python stdlib puro)
│       ├── cli.py                    # Argparse + dispatch + sys.exit()
│       ├── commands.py               # Lógica de negocio (retorna resultados)
│       ├── errors.py                 # Exit codes + excepciones tipadas
│       ├── locking.py                # Write lock + session lock + stale detection
│       ├── manifest.py               # I/O atómico del manifest
│       └── paths.py                  # Rutas + constantes
└── tests/                            # Suite de tests (unittest, stdlib)
```

### Concurrencia: lock de sesión vs. lock de tarea

Context Guard maneja la concurrencia en **dos niveles**, diseñados para permitir paralelismo real entre agentes:

| Nivel | Comando | Duración | Propósito |
|---|---|---|---|
| **Sesión** | `claim` / `release` | Efímero (segundos) | Serializa cold-boot y archivado. Se libera inmediatamente al terminar la inicialización. |
| **Tarea** | `claim-task` / `release-task` | Por ítem | Lock granular por tarea. Permite que múltiples agentes trabajen en tareas distintas del mismo contexto simultáneamente. |

### Pipeline de cierre

Cuando todas las tareas están completas, el agente ejecuta el pipeline de cierre:

```text
check-completion → review → verify → archive
```

---

## 🔧 Comandos CLI

| Comando | Tipo | Propósito |
|---|---|---|
| `claim` | Sesión | Check + acquire atómico. Maneja stale-takeover si el TTL expiró |
| `acquire` | Sesión | Alias retrocompatible de `claim` |
| `release` | Sesión | Libera el lock de sesión |
| `check-lock` | Sesión (read-only) | Muestra estado del lock (FREE/ACTIVE/STALE) |
| `claim-task` | Tarea | Lock granular por tarea individual |
| `release-task` | Tarea | Libera lock de una tarea (soporta `--agent-id` para validación de ownership y `--force` para override) |
| `check-completion` | Utilidad | Parsea `tasks.md` y/o `blockers_todo.md`, reporta completitud por fuente y agregada |
| `validate` | Utilidad | Verifica existencia y tamaño de artefactos (required + optional) |
| `archive` | Utilidad | Archiva un contexto completado (verifica completitud, valida, copia, borra) |

### Exit codes

```text
0 = EXIT_OK
1 = EXIT_LOCK_HELD         (otra sesión activa)
2 = EXIT_LOCK_CONTENDED    (perdiste la carrera por un stale lock)
3 = EXIT_VALIDATION        (artefacto mal formado o excede cap)
4 = EXIT_GENERIC           (manifest corrupto)
```

---

## 📋 Requisitos

* **Python 3** — `guard.py` es stdlib pura, se ejecuta con `python3` directo. No requiere dependencias externas.
* **git** — auto-discovery del estado del repositorio (`git diff`).
* Un orquestador con soporte de *tool use* / ejecución de shell (Antigravity CLI, OpenCode, u otro compatible con el Agent Skills Spec).

## 🧪 Tests

```bash
python3 -m unittest discover tests/ -v
```

## 🧹 Desinstalación

```bash
bash scripts/install.sh --uninstall --target <antigravity|opencode>
```

Si se omite `--target`, se limpian ambos archivos (`GEMINI.md` y `AGENTS.md`).

---

## ⚠️ Compatibilidad entre niveles de modelo (free-tier → frontier)

El middleware es determinista y no depende del modelo. **El protocolo del `SKILL.md` sí depende de instruction-following confiable**, y ese es el eslabón débil con modelos de menor capacidad.

- **Frontier (Opus, GLM-5.1 grande, etc.):** el protocolo funciona porque el modelo mantiene la secuencia cold-boot → claim-task → ejecución → release-task sin saltarse pasos, incluso a través de múltiples turnos.
- **Mid-range / free-tier (MiniMax free, Nemotron, Gemini Flash):** riesgo residual de que el modelo rompa el boundary de idioma (archivos en inglés / respuesta en español) o no interprete correctamente el flujo de claim-task por ítem.

### ✅ Implementado (mitigaciones que reducen la superficie de error del modelo)

1. **`claim` atómico:** `guard.py claim --context X` colapsa check+acquire+stale-takeover en una sola llamada. El modelo no necesita secuenciar check-lock y adquisición manualmente.
2. **`check-completion` determinista:** `guard.py check-completion --context X` parsea `tasks.md` y/o `blockers_todo.md` devolviendo métricas estructuradas. El modelo ya no necesita contar checkboxes a mano, evitando alucinaciones numéricas.
3. **`validate` preventivo y límite de longitud:** `guard.py validate --context X` verifica la existencia de artefactos obligatorios y audita su tamaño. Se rechaza automáticamente cualquier archivo que exceda el límite de caracteres, atrapando errores en tiempo de ejecución para forzar al modelo a sintetizar y prevenir la inflación de contexto.
4. **Exit codes semánticos (machine-readable):** Todos los comandos devuelven códigos de salida diferenciados (e.g., `EXIT_LOCK_HELD`, `EXIT_VALIDATION`). El orquestador puede bifurcar el flujo de control sin depender de que el LLM parsee strings de texto.
5. **`archive` atómico:** `guard.py archive --context X` orquesta la validación final, el copiado y la limpieza de sesión en un único paso transaccional. Elimina la necesidad de que el modelo encadene operaciones complejas de I/O sobre el file system.
6. **Detección de locks huérfanos (Stale-detection por PID):** El mutex de escritura (read-modify-write) incluye el PID del proceso en su lockfile. Si el agente es interrumpido bruscamente y el proceso muere, el lock se recupera automáticamente verificando la vitalidad del proceso local, sin depender de un timeout ciego (a diferencia del lock de sesión que opera por TTL).
7. **Validación de ownership en tareas:** `release-task --agent-id` asegura que un agente no libere accidentalmente una tarea reclamada por otro agente en sesiones concurrentes.
8. **Desacople en Sub-skills:** Procesos complejos como el desglose funcional (`tasks`), auditoría estática (`review`) y validación dinámica (`verify`) se aislaron en skills independientes. Esto achica el prompt principal del enjambre y carga las instrucciones específicas solo en la fase del pipeline que las requiere.


<!-- 

### ⚠️ Pendiente (Hoja de ruta)

* **Perfil Slim para modelos limitados:** El protocolo actual del `SKILL.md` es estable en frontier models, pero puede ser denso para modelos con ventanas de contexto chicas o baja adherencia a instrucciones.
   - *Mejora propuesta:* Crear un `SKILL-slim.md` (un checklist plano y estricto) e introducir la flag `--profile slim` en el instalador.
* **Soporte extendido de orquestadores:** Actualmente el instalador provee inyección automática (`--target`) para Antigravity y OpenCode.
   - *Mejora propuesta:* Integración automática con otros harness populares (ej. RooCode, Cline) modificando sus system prompts dinámicamente.
* **Telemetría / Auditoría de estado (Event Sourcing):** 
   - *Mejora propuesta:* Mantener un log de transacciones estructurado (JSONL) con todas las mutaciones realizadas sobre el `manifest.json`, para facilitar el post-mortem debugging si un agente rompe la integridad lógica del contexto.
