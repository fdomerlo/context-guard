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

1. **`claim` atómico.** `guard.py claim --context X` colapsa check+acquire+stale-takeover en una sola llamada. El modelo no necesita secuenciar `check-lock` → `acquire` manualmente.

2. **`check-completion` determinista.** `guard.py check-completion --context X` parsea `tasks.md` y/o `blockers_todo.md` y devuelve datos estructurados por fuente. El modelo no cuenta checkboxes a mano.

3. **`validate` para artefactos generados.** `guard.py validate --context X` verifica existencia de artefactos obligatorios y tamaño de todos los artefactos presentes. Un archivo faltante se detecta en el momento, no en la próxima sesión.

4. **Cap de longitud en artefactos.** `validate` rechaza cualquier archivo que exceda ~2000 caracteres (~500 tokens), forzando al modelo a resumir. Previene inflación de contexto en rehidrataciones futuras.

5. **Exit codes machine-readable.** Todos los comandos devuelven códigos de salida diferenciados para que el harness bifurque el flujo sin depender de que el LLM parsee strings.

6. **`archive` atómico.** `guard.py archive --context X` verifica completitud, valida artefactos, copia a archive, y limpia la sesión en un solo comando. El modelo no necesita orquestar copy+verify+delete manualmente.

7. **Stale-detection en write lock.** El mutex de escritura incluye PID y timestamp. Si el proceso que lo creó murió, el lock se recupera automáticamente sin esperar timeout.

8. **Ownership validation en `release-task`.** Con `--agent-id`, se valida que quien libera una tarea sea quien la reclamó. `--force` permite override.

### ⚠️ Pendiente

9. **Reducir el SKILL.md para modelos con ventanas chicas.** El protocolo actual funciona para frontier models pero puede ser denso para modelos con peor adherencia a instrucciones largas. Plan de mitigación:
   - Comprimir las secciones declarativas.
   - Considerar un perfil `SKILL-slim.md` como checklist plano sin explicación, seleccionable con `install.sh --profile slim|full`.

**Principio general:** cada mitigación implementada mueve una decisión que antes dependía de que el LLM interpretara bien el prompt, hacia una decisión que el CLI resuelve de forma determinista y devuelve como dato verificable.
