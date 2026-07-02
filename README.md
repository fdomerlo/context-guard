---
type: readme
title: Context Guard
timestamp: 2026-07-02
tags:
  - documentation
  - skill
  - swarm-agent
description: Motor de persistencia transaccional y rehidratación de contexto para enjambres de agentes IA, agnóstico de modelo y de harness.
---

# Context Guard 🧠🛡️

**Motor de Persistencia Transaccional y Rehidratación de Contexto para Enjambres de Agentes**

Context Guard es una *skill* que dota a agentes efímeros de una memoria atómica persistente en el sistema de archivos, resolviendo saturación de tokens, deriva de contexto y pérdida de estado entre sesiones — sin depender del historial de chat.

El middleware (`cg_manager.py`) es Python puro sobre stdlib, sin llamadas a ningún proveedor. Es agnóstico del **modelo** por diseño. No es agnóstico del **harness** de forma automática: cada orquestador (Antigravity, OpenCode, etc.) carga sus instrucciones globales desde un archivo distinto, así que el instalador necesita una rutina por target. Ver sección de instalación.

---

## 🎯 El Problema que Resuelve

1. **Saturación del Contexto:** recordar largos historiales agota tokens. El agente lee el estado actual desde `.context-guard/` en lugar de reconstruirlo desde el chat.
2. **Deriva de Estado:** el agente no edita `manifest.json` en crudo. Toda escritura pasa por `cg_manager.py`, que aplica write atómico (`tmp` + `rename`) y un lock de exclusión mutua a nivel de sistema operativo (`O_CREAT|O_EXCL` sobre un lockfile dedicado) — no una simple bandera dentro del propio manifest, que es vulnerable a condiciones de carrera entre lectura y escritura (TOCTOU) cuando dos sesiones acceden en paralelo.
3. **Arranque en Frío (Cold Boot):** inspecciona el proyecto (`package.json`, `pyproject.toml`, etc.) para auto-rehidratarse antes de actuar.

---

## 🚀 Instalación y Configuración

```bash
bash scripts/install.sh --target <antigravity|opencode>
```

Esto realiza dos acciones:

1. Copia el núcleo a `~/.agents/skills/context-guard/` y el middleware ACID a `bin/cg_manager.py`.
2. Inyecta el *Boot Prompt* obligatorio en el archivo de instrucciones globales del harness elegido (`~/.gemini/GEMINI.md` para Antigravity, `~/.config/opencode/AGENTS.md` para OpenCode).

El bloque inyectado es el mismo en ambos casos:

```markdown
## ACTIVE PERSISTENCE CONTRACT: context-guard

MANDATORY BOOTSTRAP — execute before responding to anything:
1. Call read_file on `~/.agents/skills/context-guard/SKILL.md`.
2. Follow every instruction in that file as your absolute state contract.
3. Check for an active context at `.context-guard/active_session/manifest.json`
   and act accordingly (Cold Boot, Resume, or Recovery).
```

### ¿Por qué el lock importa más en OpenCode que en Antigravity?

Los subagentes de Antigravity corren en workspaces aislados; rara vez compiten por el mismo `manifest.json`. OpenCode soporta multi-sesión real sobre el mismo directorio de proyecto — ahí el lock deja de ser defensivo y pasa a prevenir corrupción activa. Si vas a probar concurrencia real, hacelo contra OpenCode primero.

---

## 📋 Requisitos

* **uv (Python Manager)** — ejecución aislada del middleware (`uv run ...`).
* **git** — auto-discovery del estado del repositorio (`git diff`).
* Un orquestador con soporte de *tool use* / ejecución de shell (Antigravity CLI, OpenCode, u otro compatible con el Agent Skills Spec).

## 🧹 Desinstalación

```bash
bash scripts/install.sh --uninstall --target <antigravity|opencode>
```

---

## ⚠️ Compatibilidad entre niveles de modelo (free-tier → frontier)

El middleware es determinista y no depende del modelo. **El protocolo del `SKILL.md` sí depende de instruction-following confiable**, y ese es el eslabón débil con modelos de menor capacidad. Estado actual honesto:

- **Frontier (Opus, GLM-5.1 grande, etc.):** el protocolo funciona porque el modelo mantiene la secuencia cold-boot → lock-check → ejecución → release sin saltarse pasos, incluso a través de múltiples turnos.
- **Mid-range / free-tier (MiniMax free, Nemotron, Gemini Flash):** riesgo real de que el modelo omita el `check-lock` antes de escribir, cuente mal los ítems pendientes en `blockers_todo.md`, o rompa el boundary de idioma (archivos en inglés / respuesta en español).

### Lo que falta para que sea confiable en todo el rango:

1. **Colapsar pasos multi-turno en comandos atómicos del CLI.** Hoy `check-lock` y `acquire` son dos invocaciones separadas que el modelo debe secuenciar correctamente. Un modelo débil puede ejecutar `acquire` sin chequear antes. Falta un subcomando `cg_manager.py claim --context X` que haga check+acquire en una sola llamada atómica, reduciendo la superficie de error de orquestación a cero pasos del lado del prompt.

2. **Mover el conteo de finalización del prompt al CLI.** El paso 5 del SKILL.md (archivar cuando `blockers_todo.md` tiene cero `- [ ]` pendientes) le pide al modelo que cuente manualmente. Un modelo débil cuenta mal. Falta `cg_manager.py check-completion` que parsee el archivo de forma determinista y devuelva `TRUE`/`FALSE`.

3. **Validación de esquema para archivos generados por el modelo.** `snapshot.md`, `objective.md` y `blockers_todo.md` los escribe el LLM en formato libre. Nada verifica que el formato generado sea parseable en la próxima sesión. Falta un subcomando `validate` que haga lint sobre esos archivos antes de dar por cerrado el cold boot — si un modelo débil genera un `blockers_todo.md` mal formado, hoy eso se descubre recién en la sesión siguiente, no en el momento en que se creó.

4. **Topes de longitud en los artefactos generados.** No hay límite de tokens en `snapshot.md`/`objective.md`. Un modelo verboso (común en free-tier, que compensa incertidumbre con explicación) puede inflar estos archivos, y ese costo se paga en cada rehidratación futura. Falta un cap explícito (equivalente a lo que ya aplicaste en `sdd-verify`/`sdd-apply` de Agentify SDD) — por ejemplo, rechazar en `validate` cualquier archivo que exceda ~500 tokens y forzar resumen.

5. **Exit codes machine-readable en vez de solo texto por stdout.** Hoy `cg_manager.py` imprime `SUCCESS|...` o `FAIL|...` como string. Un modelo débil puede no interpretar correctamente el resultado y continuar como si hubiera tenido éxito. Falta devolver códigos de salida distintos (0 = éxito, 1 = lock ocupado, 2 = stale, etc.) para que el harness pueda bifurcar el flujo sin depender de que el LLM lea bien el string.

6. **Reducir el SKILL.md mismo.** Es denso y jerárquico (5 secciones, pasos anidados). Para modelos con ventanas de contexto chicas o peor adherencia a instrucciones largas, conviene aplanarlo — mismo principio que ya usaste al auditar `orchestrator-core.md` en Agentify SDD: menos indirección, contrato de ejecución más cerca de cada paso en lugar de centralizado arriba.

**Principio general:** cada uno de estos puntos mueve una decisión que hoy depende de que el LLM interprete bien el prompt, hacia una decisión que el CLI resuelve de forma determinista y devuelve como dato verificable. Es la misma dirección que ya tomaste con `state_manager.py` en Agentify SDD — acá falta aplicarla de forma más agresiva porque el rango de modelos objetivo es más amplio.
