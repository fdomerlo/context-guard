---
type: readme
title: Context Guard
timestamp: 2026-07-28
tags:
  - mcp-server
  - ai-agents
  - transactional-state
  - context-management
description: Middleware transaccional y gestor de estado estricto para agentes de IA mediante Model Context Protocol (MCP).
---

# Context Guard 🧠🛡️

**Middleware transaccional y gestor de estado estricto para agentes de IA (vía Model Context Protocol - MCP).**

`Context Guard` es un servidor MCP en Python que actúa como un middleware determinista de control de estado y persistencia transaccional para agentes de Inteligencia Artificial. Garantiza la atomicidad en la ejecución de tareas complejas, previniendo la corrupción de estado y la deriva de contexto en ciclos de trabajo multi-turno.

---

## 🎯 El Problema que Aborda

Los agentes de IA basados en Grandes Modelos de Lenguaje (LLMs) enfrentan limitaciones estructurales al ejecutar tareas de ingeniería compuestas o de larga duración:

1. **Degradación y Deriva de Contexto (*Context Drift*):** A medida que la conversación se extiende, las instrucciones iniciales se diluyen. El agente pierde el foco del objetivo original y toma decisiones divergentes o contradictorias.
2. **El Fenómeno "Lost in the Middle":** En contextos extensos, los modelos tienden a ignorar detalles críticos ubicados en la zona central de la ventana de contexto.
3. **Alucinación de Completitud:** El agente asume erróneamente que una tarea está terminada sin haber ejecutado las verificaciones ni las pruebas necesarias.
4. **Estados Corruptos e Incompletos:** Si el proceso se interrumpe (por límites de tokens, timeouts o fallas del sistema), el repositorio queda en un estado inconsistente a medio editar, sin mecanismos de reversión (*rollback*).

---

## 💡 Qué Resuelve (La Solución)

`context-guard` introduce una capa de gobierno estricta sobre el ciclo de vida del trabajo del agente mediante:

* **Pipeline Estricto de 3 Estados (DAG):**
  $$\text{PLAN} \longrightarrow \text{EXECUTE} \longrightarrow \text{VERIFY} \longrightarrow \text{ARCHIVE}$$
  El agente no puede saltar fases (ej. pasar de `PLAN` a `VERIFY` directamente). Cada estado exige completar y validar sus entregables antes de avanzar.
* **Transacciones Atómicas y Rollback:** Al iniciar cada fase (`begin_transaction`), se toma un snapshot del manifest. Si la fase falla o los tests no pasan, `rollback_transaction` restaura el estado previo de manera limpia.
* **Control de Concurrencia y Locks a Nivel de OS:** Utiliza lockfiles del sistema operativo (`O_CREAT|O_EXCL`) y mutexes de escritura (`with_write_lock`) para evitar condiciones de carrera (*TOCTOU*) entre agentes o sesiones concurrentes.
* **Servidor MCP Nativo:** Expone herramientas estructuradas a través de `stdio` (`begin_transaction`, `commit_transaction`, `rollback_transaction`, `save_checkpoint`), integrándose directamente con el flujo de trabajo del agente sin sobrecarga de tokens.

---

## 🚫 Qué NO Resuelve

Para mantener expectativas claras en su adopción:

* **NO es un agente autónomo:** `context-guard` no escribe código, no analiza sintaxis ni genera razonamiento por sí solo. Es una herramienta determinista utilizada *por* el agente.
* **NO es un ejecutor de pruebas (*Test Runner*):** No ejecuta `pytest` o `npm test` automáticamente; en su lugar, establece el protocolo transaccional que exige al agente ejecutar y validar los tests antes de permitir el `commit` a la siguiente fase.

---

## 🚀 Instalación y Configuración

### Opción A: Ejecución Directa (Zero-Install con `uvx`) — RECOMENDADA

No requiere clonar el repositorio previamente. Agrega el siguiente bloque al archivo de configuración MCP de tu IDE (ej. `mcp-settings.json` o `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "context-guard": {
      "command": "uvx",
      "args": [
        "git+https://github.com/fdomerlo/context-guard.git"
      ]
    }
  }
}
```

---

### Opción B: Instalación Local Aislada (One-Liner)

Para tener el servidor clonado localmente en la ruta estándar de servidores MCP:

```bash
mkdir -p ~/.local/share/mcp-servers && git clone https://github.com/fdomerlo/context-guard.git ~/.local/share/mcp-servers/context-guard && cd ~/.local/share/mcp-servers/context-guard && uv venv && uv pip install -e .
```

Configuración en el JSON del cliente (`mcp-settings.json` o `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "context-guard": {
      "command": "/ruta/a/tu/home/.local/share/mcp-servers/context-guard/.venv/bin/context-guard"
    }
  }
}
```


---

## 📖 Guía de Uso (Instrucciones para el Agente)

Para forzar al agente a utilizar `context-guard` en tareas complejas, incluye el siguiente **System Prompt** en la configuración de reglas de tu IDE (ej. `.clinerules`, `.cursorrules`, o Custom Instructions):

```markdown
## PROTOCOLO OBLIGATORIO DE GESTIÓN DE ESTADO: context-guard

Para cualquier tarea que involucre refactorizaciones, cambios de arquitectura o modificaciones en múltiples archivos (umbral de complejidad > 2 archivos):

1. **Fase PLAN:**
   - Inicia la transacción llamando a `begin_transaction(context="<RUTA_ABSOLUTA_DEL_PROYECTO>", phase="PLAN")`.
   - Define el objetivo y desglosa las tareas.
   - Guarda un checkpoint con `save_checkpoint(context="<RUTA_ABSOLUTA_DEL_PROYECTO>", summary="...")`.
   - Avanza la fase llamando a `commit_transaction(context="<RUTA_ABSOLUTA_DEL_PROYECTO>", next_phase="EXECUTE")`.

2. **Fase EXECUTE:**
   - Inicia la fase con `begin_transaction(context="<RUTA_ABSOLUTA_DEL_PROYECTO>", phase="EXECUTE")`.
   - Realiza las modificaciones de código paso a paso.
   - Si ocurren errores irrecuperables, ejecuta `rollback_transaction(context="<RUTA_ABSOLUTA_DEL_PROYECTO>")`.
   - Al finalizar los cambios, llama a `commit_transaction(context="<RUTA_ABSOLUTA_DEL_PROYECTO>", next_phase="VERIFY")`.

3. **Fase VERIFY:**
   - Inicia la fase con `begin_transaction(context="<RUTA_ABSOLUTA_DEL_PROYECTO>", phase="VERIFY")`.
   - Ejecuta la suite de pruebas del proyecto (`pytest`, `npm test`, etc.).
   - Si las pruebas fallan, corrige o ejecuta `rollback_transaction`.
   - Si todas las pruebas pasan, consolida el trabajo con `commit_transaction(context="<RUTA_ABSOLUTA_DEL_PROYECTO>", next_phase="ARCHIVE")`.

REGLA CLAVE: El parámetro `context` debe ser SIEMPRE la ruta absoluta al directorio raíz del proyecto actual (ej. `/home/usuario/workspace/mi-proyecto`).
```

---

## 🛠️ Errores Comunes (Troubleshooting)

| Código | Nombre | Descripción y Solución |
|---|---|---|
| `[1]` | `EXIT_LOCK_HELD` | **Transacción o Lock Trabado:** Ya existe una transacción activa en el contexto o el TTL no ha expirado. Si el proceso anterior se interrumpió de forma abrupta, espera a que expire el TTL o libera el archivo `.context-guard/.lock`. |
| `[2]` | `EXIT_LOCK_CONTENDED` | **Contención de Lock:** Se detectó colisión con otro proceso intentando tomar el lock simultáneamente. |
| `[3]` | `EXIT_VALIDATION` | **Error de Validación:** Resumen de checkpoint demasiado largo (supera los 2000 caracteres) o parámetro de fase inválido. |
| `[4]` | `EXIT_GENERIC` | **Error Genérico:** Manifest corrupto o no inicializado. |
| `[5]` | `EXIT_BAD_TRANSITION` | **Transición Inválida:** Se intentó saltar una fase del pipeline (ej. pasar de `PLAN` directamente a `VERIFY` sin pasar por `EXECUTE`). Respeta la secuencia `PLAN -> EXECUTE -> VERIFY -> ARCHIVE`. |

---

## 🗺️ Roadmap / Próximos Pasos

- [ ] **Snapshots de Código con Git:** Integración nativa con `git stash` / `git commit` temporal para que `rollback_transaction` no solo revierta el estado JSON del manifest, sino también las modificaciones en los archivos del árbol de trabajo.
- [ ] **Métricas de Rendimiento de Contexto:** Reporte de economía de tokens y tiempo transcurrido por cada fase del pipeline.
- [ ] **Soporte Multi-Agente Avanzado:** Mejoras en la resolución de conflictos cuando múltiples agentes paralelos ejecutan transacciones simultáneas en diferentes subdirectorios.
