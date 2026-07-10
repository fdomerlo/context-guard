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
| `next-task` | Tarea | Busca la siguiente tarea pendiente no reclamada, la reclama atómicamente, y retorna su ID + descripción |
| `check-completion` | Utilidad | Parsea `tasks.md` y/o `blockers_todo.md`, reporta completitud por fuente y agregada |
| `validate` | Utilidad | Verifica existencia y tamaño de artefactos (required + optional) |
| `status` | Utilidad | Resumen one-shot del contexto: objetivo, progreso, próxima tarea, estado del lock |
| `doctor` | Utilidad | Diagnóstico de salud: artefactos, tamaño, idioma, task claims huérfanos, lock state |
| `archive` | Utilidad | Archiva un contexto completado (verifica completitud, valida, copia, borra) |

### Output format

Todos los comandos soportan `--format json` para output estructurado (default: `text`):

```bash
python3 guard.py --format json claim --context my-project
# {"status": "SUCCESS", "command": "claim", "action": "LOCK_ACQUIRED", "exit_code": 0}
```

### Exit codes

```text
0 = EXIT_OK
1 = EXIT_LOCK_HELD         (otra sesión activa)
2 = EXIT_LOCK_CONTENDED    (perdiste la carrera por un stale lock)
3 = EXIT_VALIDATION        (artefacto mal formado o excede cap)
4 = EXIT_GENERIC           (manifest corrupto)
```

### Task checkbox convention

El middleware reconoce tres estados de checkbox:

```text
- [ ] Pending      (no empezada)
- [/] In progress  (empezada, no terminada)
- [x] Done         (completada)
```

`[/]` se cuenta como incompleta en `check-completion`.

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
bash install.sh --uninstall --target <antigravity|opencode>
```

Si se omite `--target`, se limpian ambos archivos (`GEMINI.md` y `AGENTS.md`).

---

## ⚠️ Compatibilidad entre niveles de modelo (free-tier → frontier)

El middleware es determinista y no depende del modelo. **El protocolo del `SKILL.md` sí depende de instruction-following confiable**, y ese es el eslabón débil con modelos de menor capacidad.

- **Frontier (Opus, GLM-5.1 grande, etc.):** el protocolo funciona porque el modelo mantiene la secuencia cold-boot → claim-task → ejecución → release-task sin saltarse pasos, incluso a través de múltiples turnos.
- **Mid-range / free-tier (MiniMax free, Nemotron, Gemini Flash):** riesgo residual de que el modelo rompa el boundary de idioma o no interprete correctamente el flujo de claim-task por ítem.

### 🔄 Perfil Slim para modelos free-tier

Para modelos con baja adherencia a instrucciones, el instalador soporta un perfil compacto:

```bash
bash install.sh --target antigravity --profile slim
```

| Perfil | SKILL.md | Sub-skills | Dual-language | Líneas |
|---|---|---|---|---|
| `full` (default) | Protocolo narrativo completo | ✅ tasks, review, verify | ✅ EN archivos / ES respuestas | ~130 |
| `slim` | Checklist imperativo | ❌ solo archive directo | ❌ todo en inglés | ~50 |

El perfil slim usa `next-task` y `status` en lugar de requerir que el modelo itere manualmente sobre `claim-task`.

### ✅ Mitigaciones implementadas

1. **`claim` atómico:** colapsa check+acquire+stale-takeover en una sola llamada.
2. **`check-completion` determinista:** parsea checkboxes devolviendo métricas estructuradas. Evita alucinaciones numéricas.
3. **`validate` preventivo:** verifica existencia y tamaño de artefactos obligatorios (cap: ~1500 tokens).
4. **Exit codes semánticos:** códigos de salida diferenciados y machine-readable.
5. **`archive` atómico:** validación final + copiado + limpieza en un único paso transaccional dentro de write-lock.
6. **Stale-detection por PID:** el write-lock detecta procesos muertos automáticamente.
7. **Ownership validation:** `release-task --agent-id` previene liberaciones accidentales.
8. **Sub-skills desacoplados:** `tasks`, `review`, `verify` se cargan solo cuando se necesitan.
9. **`next-task`:** elimina el loop implícito — busca y reclama la siguiente tarea pendiente en una sola llamada.
10. **`status`:** resumen one-shot del estado para rehidratación sin leer múltiples archivos.
11. **`doctor`:** diagnóstico automático de problemas comunes (artefactos, idioma, claims huérfanos).
12. **`--format json`:** output JSON estructurado para modelos que no parsean bien pipe-delimited strings.
13. **Soporte `[/]`:** reconoce tareas en progreso en las métricas de completitud.

