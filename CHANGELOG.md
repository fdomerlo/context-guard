# Changelog

Todos los cambios notables en este proyecto serán documentados en este archivo.

El formato está basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/), y este proyecto adhiere a [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
