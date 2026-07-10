# Review — Context Guard

## Propósito

Skill responsable de la **AUDITORÍA ESTÁTICA**. Analiza el código fuente y lo compara contra los documentos de referencia sin ejecutar ningún código ni tests.

La diferenciación clave con `verify` es:

- **verify**: Análisis dinámico — ejecuta tests y build, valida comportamiento en runtime
- **review**: Análisis estático — compara estructura de código contra requisitos documentados

## Cuándo se Activa

Como parte del **pipeline de cierre** de un contexto, antes de `verify`:

```text
check-completion → review → verify → archive
```

También puede ejecutarse manualmente para auditar progreso parcial.

## Qué Hacer

### Paso 1: Leer Contexto

1. Leer el manifest: `.context-guard/sessions/{context}/manifest.json`
2. Leer los documentos de `reference_docs` del manifest (SPECs, ADRs)
3. Leer `tasks.md` para entender el alcance del trabajo
4. Leer `objective.md` para entender el objetivo

### Paso 2: Leer Specifications

```text
PARA CADA DOCUMENTO en reference_docs:
├── Identificar requisitos (MUST, SHALL, SHOULD, MAY)
├── Identificar escenarios Given/When/Then (si aplica)
└── Documentar: qué funciones, estructuras, flujos deben existir
```

Si no hay `reference_docs`, usar `objective.md` como fuente de requisitos.

### Paso 3: Analizar Código Base (Estático)

Sin ejecutar código, analizar la estructura del código fuente:

```text
PARA CADA ARCHIVO MODIFICADO/CREADO según tasks.md:
├── Identificar funciones y sus firmas
├── Identificar estructuras de datos
├── Identificar flujos de datos
├── Identificar dependencias externas
└── Documentar: qué existe realmente
```

### Paso 4: Comparar Contra Requisitos

Cruzar lo que dicen los documentos de referencia contra lo que existe en el código:

```text
PARA CADA REQUISITO:
├── Buscar evidencia en el código base
├── Marcar: ✅ Implemented / ⚠️ Partial / ❌ Missing
└── Documentar desviaciones encontradas
```

### Paso 5: Generar Reporte de Auditoría

Persistir en `.context-guard/sessions/{context}/review-report.md`:

```markdown
# Review Report: {context}

**Status**: {APPROVED | WARNINGS | BLOCKED}

## Findings

### Finding 1: {title}
- **Severity**: CRITICAL | WARNING | SUGGESTION
- **Location**: {file:range}
- **Description**: {what was found}
- **Recommendation**: {what to do}

---

### Static Completeness
| Requirement     | Status              | Notes                    |
|-----------------|---------------------|--------------------------|
| {Requirement}   | ✅ Implemented       | {brief note}             |
| {Requirement}   | ⚠️ Partial          | {what's missing}         |
| {Requirement}   | ❌ Missing           | {not implemented}        |

---

## Verdict

{APPROVED / WARNINGS / BLOCKED}
{One-line summary}
```

### Paso 6: Reportar

Reportar al usuario en **español** con un resumen del resultado.

Si hay issues **CRITICAL**, el contexto no debería avanzar a `verify`.

## Reglas

- **NUNCA ejecutar código** — solo análisis estático
- **NUNCA emitir opiniones sobre estilo** — basarse exclusivamente en requisitos documentados
- Usar las palabras clave RFC 2119 (MUST, SHALL, SHOULD, MAY) para categorizar requisitos
- Ser objetivo — reportar lo que ES, no lo que debería ser
- El reporte (`review-report.md`) DEBE estar en **inglés**
- El reporte al usuario DEBE estar en **español**
- SIEMPRE guardar el reporte en `.context-guard/sessions/{context}/review-report.md`
