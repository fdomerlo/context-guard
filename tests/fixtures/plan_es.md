# PLAN-2.3 — Continuación automática en PLAN→EXECUTE y disparadores de la skill de Antigravity

Ciclo chico, disparado por dogfooding real con los tres hosts en simultáneo
(agosto 2026, prueba de la todo-app). Dos fixes de comportamiento, no de
documentación.

## Diagnóstico (evidencia, no hipótesis)

- El gate de aprobación ya es seguro: `commit --next-phase EXECUTE` exige
  `approval` en el manifest y falla con exit 6 si falta.
- Antigravity, confirmado en vivo: sin invocar `/context-guard`, la skill no
  se activa con un prompt tipo "creá una todo-app simple".

## F1 — Continuación automática en la misma sesión (Sonnet)

En `_data/phases/plan.md`, Step 6, después de "This advances `lock_phase`
to `EXECUTE`...", instruir al agente a continuar en el mismo turno.

Un solo lugar de cambio (la fase, no cada adapter) corrige los tres hosts a
la vez.

**Tests:** `plan.md` es prosa que interpreta el agente, no código ejecutable
— el test es de contenido, no de ejecución. Verificar que la instrucción de
continuar en el mismo turno aparece antes que la de sugerir `/cg-continue`.

**Criterios de aceptación:**
- Revisión humana de que el texto es inequívoco.
- El texto nunca debe leerse como "continuá sin aprobación".

## F2 — Disparadores de la skill de Antigravity (Opus para redactar, humano para validar)

**Paso humano primero, antes de commitear nada.** El agente redacta dos
candidatos de `description` para la skill de Antigravity.

**Spec:**
- Candidato A amplía disparadores concretos y conserva carga selectiva.
- Candidato B es incondicional: "Use always for any coding task".

**Tests:** extender el test de disparadores concretos con los términos
nuevos, en rojo antes del fix.

**Criterios de aceptación:**
- La `description` es la que el humano validó en vivo.
- Constancia en `VERIFY.md` de contra qué versión se validó.

## F3 — Constancia de validación

Anotar en `docs/adapters/VERIFY.md` qué `description` está en uso.

**Criterios de aceptación:**
- `VERIFY.md` nombra la versión de Antigravity CLI usada.

## Fuera de scope

Todo lo demás del backlog.

## Criterios de aceptación

1. Suite verde.
2. `plan.md` actualizado; test de contenido de la fase en verde.
