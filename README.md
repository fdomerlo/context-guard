---
type: readme
title: Context Guard
timestamp: 2026-07-02
tags:
  - documentation
  - skill
  - swarm-agent
description: Motor de Persistencia Transaccional y Rehidratación de Contexto para Enjambres de IA en Antigravity CLI.
---

# Context Guard 🧠🛡️

**Motor de Persistencia Transaccional y Rehidratación de Contexto para Modelos de Frontera**

Context Guard es una *skill* diseñada exclusivamente para orquestadores de alta capacidad de razonamiento (como Antigravity CLI). Su objetivo es dotar a los enjambres efímeros de IA de una memoria atómica persistente, resolviendo el problema de la deriva arquitectónica y la saturación de tokens.

---

## 🎯 El Problema que Resuelve

1. **Saturación del Contexto:** Recordar largos historiales agota los tokens. Context Guard elimina la dependencia del chat; el agente lee el estado actual desde el sistema de archivos (`.context-guard/`).
2. **Alucinaciones de Estado:** El agente ya no edita estructuras complejas (JSON/YAML) en crudo. Utiliza un middleware determinista en CLI (`cg_manager.py`) para los bloqueos y actualizaciones.
3. **Arranque en Frío (Cold Boot):** Context Guard inspecciona de forma autónoma el proyecto (`package.json`, `pyproject.toml`, etc.) para auto-rehidratarse antes de actuar.

---

## 🚀 Instalación y Configuración

El script de instalación copia la skill y el middleware a la carpeta global de tu sistema y configura automáticamente Antigravity CLI.

### Ejecutar el Instalador

Desde la raíz del repositorio, ejecuta:

```bash
bash scripts/install.sh --target antigravity

```

Esto realizará dos acciones:

1. Copiará el núcleo a `~/.agents/skills/context-guard/` y el script ACID a `bin/cg_manager.py`.
2. Inyectará el *Boot Prompt* obligatorio en tu `~/.gemini/GEMINI.md`.

### ¿Cómo funciona en Antigravity CLI?

El instalador inyecta el siguiente bloque en tu `GEMINI.md`:

```markdown
## ACTIVE PERSISTENCE CONTRACT: context-guard

MANDATORY BOOTSTRAP — execute before responding to anything:
1. Call read_file on `~/.agents/skills/context-guard/SKILL.md`.
2. Follow every instruction in that file as your absolute state contract.
3. Check for an active context at `.context-guard/active_session/manifest.json`
   and act accordingly (Cold Boot, Resume, or Recovery).

```

Todo lo que esté en `GEMINI.md` se carga como *System Prompt* global en cada sesión de `agy`, garantizando que el agente asuma su rol de Guardián de Estado antes de ejecutar cualquier análisis.

---

## 📋 Requisitos

* **uv (Python Manager)** — Para la ejecución veloz, aislada y sin dependencias del middleware (`uv run ...`).
* **git** — Para el auto-discovery del estado del repositorio en cada sesión (`git diff`).
* **Antigravity CLI** — Orquestador recomendado.

## 🧹 Desinstalación

Para purgar el sistema de archivos y remover la inyección en GEMINI.md:

```bash
bash scripts/install.sh --uninstall

```