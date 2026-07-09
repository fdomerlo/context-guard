---
name: tasks
description: >
  Desglosa documentos de referencia (SPECs, ADRs) en tareas atómicas de implementación
  con numeración jerárquica. Genera tasks.md dentro de la sesión activa de context-guard.
---

# Tasks Skill — Context Guard

## Propósito

Skill responsable del **DESGLOSE EN TAREAS**. Toma documentos de referencia (`reference_docs` del manifest) y produce un `tasks.md` con tareas concretas, atómicas y agrupadas por fase.

## Cuándo se Activa

- Durante el **cold boot**, si `reference_docs` en el manifest contiene documentos de referencia (SPECs, ADRs, design docs).
- Manualmente, cuando el usuario pide generar o regenerar la lista de tareas.

Si no hay `reference_docs`, el agente usa `blockers_todo.md` como fallback (flujo original de context-guard).

## Qué Hacer

### Paso 1: Leer Dependencias

1. Leer el manifest del contexto: `.context-guard/sessions/{context}/manifest.json`
2. Leer cada documento listado en `reference_docs` del manifest
3. Leer `objective.md` para entender el objetivo general
4. Leer `snapshot.md` para entender el estado actual del proyecto

### Paso 2: Escribir tasks.md

Crear el archivo de tareas en la sesión activa:

```text
.context-guard/sessions/{context}/
├── manifest.json
├── objective.md
├── snapshot.md
└── tasks.md              ← Lo creas tú
```

#### Formato

```markdown
# Tasks: {Título del Objetivo}

## Phase 1: {Nombre de la Fase} (ej: Infrastructure)

- [ ] 1.1 {Tarea atómica con ruta de archivo específica}
- [ ] 1.2 {Tarea atómica}

## Phase 2: {Nombre de la Fase} (ej: Core Implementation)

- [ ] 2.1 {Tarea atómica}
- [ ] 2.2 {Tarea atómica}
- [ ] 2.3 {Tarea atómica}

## Phase 3: {Nombre de la Fase} (ej: Testing)

- [ ] 3.1 {Tarea atómica}
```

### Paso 3: Validar

Ejecutar:
```bash
python3 ~/.agents/skills/context-guard/bin/guard.py validate --context {context}
```

Si el exit code ≠ 0, ajustar el archivo que falla.

### Paso 4: Reportar

Reportar al usuario en **español**:

```markdown
## Tareas Creadas

**Contexto**: {nombre-del-contexto}
**Total**: {N} tareas en {M} fases

### Resumen por Fase
| Fase | Tareas | Enfoque |
|------|--------|---------  |
| {nombre} | {N} | {descripción breve} |

### Próximo Paso
Listo para ejecutar tareas (claim-task / release-task).
```

## Reglas

- Agrupar tareas por fase (infrastructure, implementation, testing)
- Usar numeración jerárquica (1.1, 1.2, etc.) — estos IDs se usan como `--task-id` en `claim-task`
- Cada tarea DEBE ser lo suficientemente pequeña para implementarse en un solo archivo o módulo lógico
- Cada tarea DEBE incluir rutas de archivos concretas cuando sea posible
- Las tareas deben ser completables en una sesión de agente
- Referenciar requisitos específicos de los `reference_docs` como criterios de aceptación
- El archivo tasks.md DEBE estar en **inglés** (regla de dual-language boundary de context-guard)
- El reporte al usuario DEBE estar en **español**
