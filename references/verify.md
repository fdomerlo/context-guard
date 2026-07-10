# Verify — Context Guard

## Propósito

Skill responsable de la **VERIFICACIÓN DINÁMICA**. Demuestra —con evidencia de ejecución real— que la implementación está completa, es correcta y cumple con los requisitos.

El análisis estático por sí solo NO es suficiente. DEBÉS ejecutar el código.

## Cuándo se Activa

Como parte del **pipeline de cierre**, después de `review`:

```text
check-completion → review → verify → archive
```

## Modos de Operación

### Modo con reference_docs (verificación formal)

Cuando el manifest tiene `reference_docs` con SPECs/ADRs:
- Completitud de tareas
- Corrección estática vs specs
- Ejecución de tests
- Build
- Matriz de cumplimiento

### Modo sin reference_docs (verificación básica)

Cuando no hay documentos de referencia:
- Completitud de tareas
- Ejecución de tests
- Build
- Reporte de resultados

## Qué Hacer

### Paso 1: Leer Contexto

1. Leer el manifest: `.context-guard/sessions/{context}/manifest.json`
2. Leer `reference_docs` del manifest (si existen)
3. Leer `tasks.md`

**REGLA CRÍTICA**: No buscar en todo el código base. Solo leer archivos específicos mencionados en las tareas.

### Paso 2: Verificar Completitud

```text
Ejecutar:
python3 ~/.agents/skills/context-guard/scripts/guard.py check-completion --context {context}

Evaluar resultado:
├── Si aggregate_all_complete=true → continuar
├── Si hay tareas incompletas centrales → CRITICAL
└── Si hay tareas incompletas menores → WARNING
```

### Paso 3: Verificar Corrección vs Specs (solo modo con reference_docs)

```text
PARA CADA REQUISITO en reference_docs:
├── Buscar evidencia de implementación en el código
├── Para cada escenario documentado:
│   ├── ¿La precondición está manejada?
│   ├── ¿La acción está implementada?
│   ├── ¿El resultado esperado se produce?
│   └── ¿Los casos límite están cubiertos?
└── Marcar: CRITICAL si falta el requisito, WARNING si cobertura parcial
```

### Paso 4: Ejecutar Tests

**CRÍTICO**: Debés ejecutar usando una herramienta de terminal real. ESTÁ PROHIBIDO simular o inferir el resultado.

Detectar el test runner:

```text
Detectar comando de test desde:
├── package.json → scripts.test → npm test / npx jest / npx vitest
├── pyproject.toml / setup.py → pytest / python -m unittest
├── go.mod → go test ./...
├── Cargo.toml → cargo test
├── Makefile → make test
└── Fallback: buscar archivos *_test.* o test_*.* y ejecutar con el runner del lenguaje
```

Ejecutar los tests y registrar resultados.

### Paso 5: Build y Verificación de Tipos

```text
Detectar comando de build desde:
├── package.json → scripts.build → también ejecutar tsc --noEmit si existe tsconfig.json
├── pyproject.toml → python -m build o equivalente
├── go.mod → go build ./...
├── Cargo.toml → cargo build
├── Makefile → make build
└── Fallback: omitir y reportar como WARNING (no CRITICAL)
```

### Paso 6: Matriz de Cumplimiento (solo modo con reference_docs)

Cruzar CADA requisito de los reference_docs contra los resultados reales:

```text
PARA CADA REQUISITO:
  ├── Encontrar tests que cubren este requisito
  ├── Consultar el resultado de ese test desde el Paso 4
  ├── Asignar estado:
  │   ├── ✅ MEETS     → test exists AND passed
  │   ├── ❌ FAILING   → test exists BUT failed (CRITICAL)
  │   ├── ❌ NO_TEST   → no test found for this requirement (CRITICAL)
  │   └── ⚠️ PARTIAL  → test exists, passes, but covers only part (WARNING)
  └── Registrar: requisito, test file, test name, result
```

### Paso 7: Persistir Reporte

Escribir en `.context-guard/sessions/{context}/verify-report.md`:

```markdown
# Verify Report: {context}

## Completeness
| Metric              | Value |
|----------------------|-------|
| Total tasks          | {N}   |
| Completed tasks      | {N}   |
| Incomplete tasks     | {N}   |

## Build & Test Execution
**Build**: ✅ Passed / ❌ Failed
**Tests**: ✅ {N} passed / ❌ {N} failed / ⚠️ {N} skipped

## Spec Compliance Matrix (if reference_docs available)
| Requirement | Test        | Result     |
|-------------|-------------|------------|
| {REQ-01}    | `{test}`    | ✅ MEETS   |

## Issues Found
**CRITICAL**: {List or "None"}
**WARNING**: {List or "None"}

## Verdict
{APPROVED / APPROVED WITH WARNINGS / REJECTED}
```

### Paso 8: Reportar

Si hay issues CRITICAL → reportar que el contexto no puede ser archivado.

Reportar al usuario en **español**.

## Reglas

- SIEMPRE leer el código fuente real — no confiar en resúmenes
- SIEMPRE ejecutar tests — el análisis estático solo no es verificación
- Comparar contra reference_docs primero (corrección), código segundo (estructura)
- Ser objetivo — reportar lo que ES, no lo que debería ser
- Issues CRITICAL = deben resolverse antes de archivar
- Issues WARNING = deberían resolverse pero no bloquean
- NO corregir ningún problema — solo reportarlos
- El reporte (`verify-report.md`) DEBE estar en **inglés**
- El reporte al usuario DEBE estar en **español**
- SIEMPRE guardar el reporte en `.context-guard/sessions/{context}/verify-report.md`
