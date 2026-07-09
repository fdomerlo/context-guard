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
bash scripts/install.sh --target <antigravity|opencode>
```

Esto realiza dos acciones:

1. Copia el núcleo a `~/.agents/skills/context-guard/` y el middleware ACID a `bin/guard.py`.
2. Inyecta el *Boot Prompt* obligatorio en el archivo de instrucciones globales del harness elegido (`~/.gemini/GEMINI.md` para Antigravity, `~/.config/opencode/AGENTS.md` para OpenCode).

El bloque inyectado es el mismo en ambos casos:

```markdown
## ACTIVE PERSISTENCE CONTRACT: context-guard

MANDATORY BOOTSTRAP — execute before responding to anything:
1. Call read_file on `~/.agents/skills/context-guard/SKILL.md`.
2. Follow every instruction in that file as your absolute state contract.
3. Check for an active context at `.context-guard/sessions/{context}/manifest.json`
   and act accordingly (Cold Boot, Resume, or Recovery).
```

### Concurrencia: lock de sesión vs. lock de tarea

Context Guard maneja la concurrencia en **dos niveles**, diseñados para permitir paralelismo real entre agentes:

| Nivel | Comando | Duración | Propósito |
|---|---|---|---|
| **Sesión** | `claim` / `release` | Efímero (segundos) | Serializa cold-boot y archivado. Se libera inmediatamente al terminar la inicialización. |
| **Tarea** | `claim-task` / `release-task` | Por ítem | Lock granular por tarea de `blockers_todo.md`. Permite que múltiples agentes trabajen en tareas distintas del mismo contexto simultáneamente. |

En **Antigravity**, los subagentes corren en workspaces aislados; rara vez compiten por el mismo manifest, así que los locks son mayormente defensivos. En **OpenCode**, que soporta multi-sesión real sobre el mismo directorio de proyecto, los locks de tarea son los que habilitan concurrencia productiva — un agente puede ejecutar una tarea mientras otro trabaja en otra distinta, sin bloqueo mutuo. Si vas a probar concurrencia real, hacelo contra OpenCode primero.

---

## 📋 Requisitos

* **Python 3** — `guard.py` es stdlib pura, se ejecuta con `python3` directo. No requiere dependencias externas. `uv` es opcional si preferís ejecución aislada (`uv run guard.py ...`).
* **git** — auto-discovery del estado del repositorio (`git diff`).
* Un orquestador con soporte de *tool use* / ejecución de shell (Antigravity CLI, OpenCode, u otro compatible con el Agent Skills Spec).

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

2. **`check-completion` determinista.** `guard.py check-completion --context X` parsea `blockers_todo.md` y devuelve `total/completed/all_complete` como datos estructurados. El modelo no cuenta checkboxes a mano.

3. **`validate` para artefactos generados.** `guard.py validate --context X` verifica existencia de `objective.md`, `snapshot.md`, `blockers_todo.md` antes de dar por cerrado el cold boot. Un archivo faltante se detecta en el momento, no en la próxima sesión.

4. **Cap de longitud en artefactos.** `validate` rechaza cualquier archivo que exceda ~2000 caracteres (~500 tokens), forzando al modelo a resumir. Previene inflación de contexto en rehidrataciones futuras.

5. **Exit codes machine-readable.** Todos los comandos devuelven códigos de salida diferenciados (`0` éxito, `1` lock ocupado, `2` contención, `3` validación, `4` manifest corrupto) para que el harness bifurque el flujo sin depender de que el LLM parsee strings.

### ⚠️ Pendiente

6. **Reducir el SKILL.md para modelos con ventanas chicas.** El protocolo actual (96 líneas, 5 secciones jerárquicas) funciona para frontier models pero puede ser denso para modelos con peor adherencia a instrucciones largas. Plan de mitigación:
   - Comprimir las secciones declarativas (Paradigm, Dual-Language) de 8 líneas a 3.
   - Considerar un perfil `SKILL-slim.md` como checklist plano sin explicación, seleccionable con `install.sh --profile slim|full`.
   - El principio es el mismo: mover decisiones del prompt al CLI, reducir la cantidad de texto que el modelo necesita procesar.

**Principio general:** cada mitigación implementada mueve una decisión que antes dependía de que el LLM interpretara bien el prompt, hacia una decisión que el CLI resuelve de forma determinista y devuelve como dato verificable.
