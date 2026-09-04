# Context Guard

[![CI](https://github.com/fdomerlo/context-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/fdomerlo/context-guard/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/context-guard-cli)](https://pypi.org/project/context-guard-cli/)

**La capa de memoria transaccional para agentes de codificación con IA — tu contexto sobrevive a crashes, compactación y pérdida de sesión.**

*[Read in English](README.md)*

---

## El problema

Las sesiones largas de agentes se degradan. Deriva de contexto, "lost in the
middle", alucinación de completitud (el agente cree haber terminado antes de
verificar nada) — y la que realmente pierde trabajo: un crash o una
compactación a mitad de tarea que deja el repositorio a medio editar, sin
forma de volver atrás.

context-guard no es otro framework de agentes y no escribe código. Es una
máquina de estados pequeña y determinista que se ubica entre un agente y un
proyecto: un manifest en disco que sobrevive a que el proceso del agente
termine, un pipeline estricto `PLAN → EXECUTE → VERIFY → ARCHIVE` del que el
agente no puede saltarse fases, y un log de transacciones que se puede
revertir. Si la sesión muere, el manifest es lo que la próxima sesión lee
para retomar exactamente donde quedó la anterior — esa persistencia, no la
forma del pipeline, es el punto.

## Inicio rápido

Cinco comandos: planear un cambio, conseguir el visto bueno de un humano,
avanzar a ejecución, reclamar una tarea, y chequear el estado.

```bash
# (1) inicia un change — esto arranca PLAN y scaffoldea los artefactos
cg new redis-cache

# completa el plan — lo escribe un agente, no vos
cat > .context-guard/changes/redis-cache/objective.md <<'EOF'
# Objective: Add Redis caching
Cache the top-N query results behind a 60s TTL.
EOF
cat > .context-guard/changes/redis-cache/tasks.md <<'EOF'
- [ ] 1.1 Add the redis client dependency
- [ ] 1.2 Wrap the query path with a cache lookup
EOF

# (2) un humano revisa objective.md y tasks.md, y aprueba
cg approve

# (3) la aprobación registrada desbloquea EXECUTE
cg commit --next-phase EXECUTE

# (4) reclama la próxima tarea de forma atómica — seguro con varios agentes a la vez
cg next-task

# (5) rehidratación en un solo paso tras un crash, una compactación, o una sesión nueva
cg status
```

Cada línea de arriba corre tal cual está escrita contra un directorio nuevo;
nada acá es un resumen ilustrativo.

### Planificación estructurada con `cg plan`

Para requerimientos que abarcan múltiples pasos o fases, `cg plan` descompone el requerimiento directamente en objetivos, fases (`F1`, `F2`, …), tareas y criterios de aceptación:

```bash
# (1) inicializa el contrato del repositorio y los hooks de git
cg init

# (2) estructura un requerimiento en un plan por fases
cg plan "Agregar autenticación OAuth2"

# (3) un humano revisa objective.md y tasks.md, y aprueba
cg approve

# (4) inicia EXECUTE y reclama tareas de forma atómica
cg begin --phase EXECUTE
cg next-task

# (5) verifica criterios de aceptación y suite de tests
cg verify

# (6) confirma y avanza a la siguiente fase (o archiva)
cg commit --next-phase NEXT
```

## Instalación

Dos líneas, una vez por máquina:

```bash
uv tool install context-guard-cli
cg setup
```

¿No tenés `uv`? `pipx install context-guard-cli` hace lo mismo. Ambos
instalan en un entorno aislado y dejan `cg` en el PATH global — que es el
punto, porque `cg setup` configura tu máquina una vez, no una vez por
proyecto. `pip install context-guard-cli` también funciona, como alternativa
para una instalación de Python simple sin `uv`/`pipx` disponible. **No uses
`uv pip install context-guard-cli`**: eso instala en el venv que esté activo
en ese momento — el de un proyecto puntual, si estás parado adentro de
uno — no en la máquina, lo que anula en silencio el sentido de un `cg setup`
global.

`cg setup` detecta Claude Code, OpenCode, Antigravity y Cursor, instala los slash
commands, y deja `cg approve` detrás del permission prompt de cada uno — ver
[Adapters](#adapters-y-configuración-de-permisos). Imprime cada archivo que
tocó, y correrlo de nuevo no cambia nada.

Por proyecto, corré `cg init` una vez para scaffoldear el contrato de agentes (`AGENTS.md`),
configurar las reglas de harnesses, instalar los hooks de git y materializar los archivos de fase.
`cg new` también materializa los archivos de fase que falten bajo demanda.

**Opcional — el servidor MCP**, para hosts sin shell (Claude Desktop es el
caso para el que existe): `cg setup --with-mcp` lo registra. Todos los
adapters funcionan completos sin él; MCP es transporte alternativo, no
requisito.

**Para contribuir** (el resto está en [desarrollo](#desarrollo)):

```bash
git clone https://github.com/fdomerlo/context-guard.git
cd context-guard && uv venv && uv pip install -e ".[dev]"
git config core.hooksPath .githooks   # activa el gate de pre-commit de más abajo
```

## Actualizar

```bash
uv tool upgrade context-guard-cli && cg setup
```

El segundo comando no es opcional. `cg setup` copia los comandos, skills y
snippets de permisos dentro de la configuración de tus hosts; actualizar el
paquete no toca esas copias, así que las correcciones de adapters de una
versión nueva recién llegan a la máquina cuando se vuelve a correr
`cg setup`. Es idempotente — se puede correr las veces que quieras.

Las fases ya materializadas en un proyecto (`.context-guard/phases/`) nunca
se sobrescriben, por diseño: cada proyecto conserva las fases con las que
empezó, incluidas tus ediciones. Borrá el archivo de fase y corré `cg new`
para traer la versión actual.

## Cómo funciona

```
REQUIREMENT  →  INIT / SCAFFOLD  →  PLAN  →  DECOMPOSE  →  APPROVE  →  EXECUTE  →  VERIFY  →  ARCHIVE
```

context-guard unifica la disciplina del repositorio, el contrato de agentes y el enforcement transaccional de fases en un flujo de trabajo único:

1. **Scaffoldea el contrato del repositorio (`cg init`)**: Genera de forma idempotente `AGENTS.md`, reglas para cada harness (`CLAUDE.md`, `.cursorrules`, `.agent/rules/`), hooks de Git (`.githooks/commit-msg` forzando Conventional Commits y `.githooks/pre-commit`), y activa `core.hooksPath`.
2. **Descompone requerimientos en planes estructurados (`cg plan`)**: Lee especificaciones o requerimientos en texto y estructura objetivos, especificaciones, DAG multi-fase (F1, F2...), tareas (`tasks.md`) y criterios de aceptación directamente en `manifest.json`.
3. **Gate de aprobación humana (`cg approve`)**: Exige el visto bueno humano antes de entrar a `EXECUTE` para cada fase.
4. **Ejecuta tareas atómicamente (`cg begin`, `cg next-task`, `cg release-task`)**: Reclama y avanza en cada tarea una por una con locking atómico.
5. **Verifica y audita (`cg verify`)**: Verifica la ejecución de la suite de tests, comprueba la completitud de tareas y criterios de aceptación, actualiza reportes de auditoría (`verify-report.md`, `review-report.md`), y avanza a la siguiente fase o archivo.

Cada change (`.context-guard/changes/<nombre>/`) avanza por este pipeline
fase por fase, forzado por código, no por convención:

- **`begin`** se niega a iniciar una fase que no sea el `lock_phase` del
  manifest — el DAG se chequea antes de que arranque el trabajo, no solo
  cuando se declara terminado.
- **`commit`** valida que los artefactos de la fase (`objective.md` +
  `tasks.md` para PLAN, `review-report.md` + `verify-report.md` para VERIFY)
  no tengan ningún marcador `[PENDING]` restante antes de avanzar
  `lock_phase`.
- **`begin` sobre un PLAN nuevo** scaffoldea automáticamente cinco archivos
  markdown — `objective.md`, `snapshot.md`, `tasks.md`, `review-report.md`,
  `verify-report.md` — cada uno empezando como `[PENDING]`, así el agente
  edita plantillas en vez de inventar una forma desde cero.
- **`rollback`** restaura exactamente el snapshot del manifest tomado cuando
  arrancó la fase.
- **Los locks de sesión y de escritura** son a nivel de sistema operativo
  (`O_CREAT|O_EXCL`), con detección de staleness verificada por liveness, así
  dos agentes sobre el mismo change no compiten en silencio.
- **Los claims de tareas** tienen un lease (`claim-task` / `next-task` /
  `doctor --fix`), así varios agentes pueden trabajar un mismo change en
  paralelo sin que dos tomen la misma tarea.
- **`--change <nombre>`** acota cada comando a un change. Si hay varios
  changes activos y no se pasa `--change`, es un error que los nombra a
  todos — nunca adivina "el primero" en silencio.

## Threat Model

Leé esto antes de confiar en context-guard para algo que realmente te
importa.

El enforcement del pipeline (`begin`/`commit` validando el DAG y los
artefactos) es código real, no una sugerencia de system prompt — un agente
que usa la herramienta `cg` no puede saltarse una fase por accidente ni
avanzar con artefactos en `[PENDING]`. Pero ese enforcement es
**cooperativo**: solo aplica a un agente que llame a `cg` en primer lugar.
Un agente con shell puede escribir directamente a `manifest.json`, o
simplemente no usar la herramienta, y nada en el proceso lo detiene.

El único comando explícitamente **humano** es `cg approve`. Registra el
visto bueno que `commit --next-phase EXECUTE` exige. El nombre que anota
(`--by`, que por defecto toma el usuario del sistema) es **metadata de
auditoría, no autenticación**: dice a quién preguntarle por esa aprobación
más adelante, y un agente podría pasar cualquier string. El comando en sí
es tan cooperativo como el resto: un agente con shell puede correr
`cg approve` él mismo, y nada en `cg` lo impide. El control duro real no
vive en `cg` en absoluto — vive en el permission prompt de tu harness sobre
el comando `cg approve`, configurado por host en
`docs/adapters/*/PERMISSIONS.md`.
Ese prompt corre afuera del proceso del agente, que es el único lugar donde
puede vivir un control que no depende de la cooperación del agente.
`approve` deliberadamente no está expuesto como tool de MCP, por la misma
razón: una tool de MCP es un canal que el permission prompt no ve.

El hook de pre-commit es la única capa que corre enteramente afuera del
proceso del agente — git lo invoca sin importar qué haya decidido hacer el
agente — pero es un chequeo de perímetro sobre cantidad de archivos, no una
garantía de corrección, y viene con un bypass auditado
(`CONTEXT_GUARD_BYPASS=1`) a propósito: un bloqueo incondicional termina en
`--no-verify`, que no deja ningún rastro.

## Referencia del CLI

| Comando | Propósito |
|---|---|
| `cg init [--strict] [--no-hooks]` | Scaffoldea el contrato de agentes (`AGENTS.md`), reglas de hosts y hooks de git |
| `cg plan <requerimiento> [--from-file <ruta>]` | Descompone un requerimiento en plan estructurado, fases y tareas |
| `cg new <nombre> --context <ruta>` | Crea un change y arranca PLAN |
| `cg new <nombre> --from-plan <archivo> [--phase F2]` | Importa un `PLAN-N.md` por fases como un change por fase |
| `cg list --context <ruta>` | Lista los changes activos y su fase |
| `cg begin [--phase <FASE>] --context <ruta>` | Inicia una transacción para la fase dada |
| `cg approve [--by <quién>] [--hotfix --reason "<texto>"]` | Solo humano: registra el visto bueno que `commit` exige para entrar a EXECUTE |
| `cg commit --next-phase <FASE> --context <ruta>` | Valida los artefactos de la fase actual y avanza el DAG |
| `cg verify [--fix] --context <ruta>` | Verifica tareas y criterios de aceptación, y actualiza reportes de auditoría |
| `cg rollback --context <ruta>` | Restaura el snapshot del manifest tomado en `begin` |
| `cg checkpoint --summary "<texto>" --context <ruta>` | Persiste un resumen de sesión para retomar en caliente |
| `cg claim --context <ruta>` | Adquiere el lock de sesión, tomando uno stale si hace falta |
| `cg release --context <ruta> --agent-id <id>` | Libera el lock de sesión (con chequeo de ownership) |
| `cg claim-task --task-id <id> --context <ruta>` | Reclama una tarea con lease |
| `cg release-task --task-id <id> --agent-id <id> --context <ruta>` | Libera una tarea reclamada |
| `cg next-task --context <ruta>` | Reclama y devuelve la próxima tarea pendiente sin reclamar |
| `cg check-completion --context <ruta>` | Conteo determinista de tareas tildadas |
| `cg validate --context <ruta>` | Lint de los artefactos de sesión: existencia, tamaño, idioma |
| `cg status --context <ruta>` | Resumen en un solo paso para rehidratar tras perder contexto |
| `cg doctor --context <ruta> [--fix]` | Diagnostica (o repara) claims y locks stale |
| `cg archive --context <ruta>` | Mueve un change completado a `changes/archive/` |
| `cg migrate --context <ruta>` | Convierte in situ un layout legacy de state-guard o context-guard 1.x |

Todo comando acepta `--format json`. `cg` y `context-guard` son el mismo
binario bajo dos entry points.

## Servidor MCP

`context-guard-mcp` expone ocho tools sobre stdio — las cuatro
transaccionales más cuatro de solo lectura para hosts sin shell (Claude
Desktop es el caso para el que existen):

`begin_transaction`, `commit_transaction`, `rollback_transaction`,
`save_checkpoint`, `get_status`, `check_completion`, `validate`, `next_task`.

`cg approve` no es una tool de MCP. Ver Threat Model más arriba.

## Multi-change

El estado vive bajo `.context-guard/changes/<nombre>/`, un manifest y un
juego de locks por change, así varios changes se pueden planear y ejecutar
de forma independiente en el mismo proyecto. `cg new <nombre>` crea uno;
`cg list` muestra los activos; `cg archive` mueve uno terminado a
`changes/archive/`. `cg migrate` convierte ambos layouts legacy — el
`state.ini` de state-guard y el `.context-guard/` plano de context-guard
1.x — in situ y de forma idempotente, preservando cualquier aprobación
humana registrada que encuentre.

## Desde un plan por fases

Si el ciclo ya se planificó como un `PLAN-N.md` por fases — el artefacto
previamente generado por [disciplined-scaffold](https://github.com/fdomerlo/disciplined-scaffold)
después de debatir un proyecto con el asistente — `cg new --from-plan` lo
materializa en vez de que lo retipees:

```bash
cg new redis --from-plan PLAN-3.md
```

Nota: Las capacidades de planificación y scaffolding de `disciplined-scaffold`
ahora están unificadas nativamente dentro de `context-guard` mediante `cg init` y `cg plan`.
El flag `--from-plan` continúa totalmente soportado para retrocompatibilidad
al migrar proyectos existentes o importar documentos `PLAN-N.md` legados.

Un change por cada fase `## F<N>`, nombrados `redis-f1`, `redis-f2`, … La
prosa y el spec de cada fase se vuelven su `objective.md`; sus ítems de test
y criterios de aceptación se vuelven `tasks.md` en formato `- [ ] N.M
<texto>`, el que `cg next-task` ya reclama. `--phase F2` importa una sola
fase. Re-ejecutar saltea los changes que ya existen
(`SKIP|CHANGE_EXISTS|<nombre>`) en vez de pisar trabajo en curso.

`snapshot.md` queda `[PENDING]`: registra el estado del repositorio al
arrancar, que ningún plan escrito de antemano puede conocer.

**Importar no aprueba nada.** Cada change entra en PLAN sin aprobación en su
manifest, así que `cg commit --next-phase EXECUTE` sigue saliendo con código
6 hasta que un humano corra `cg approve` — una vez por fase. Un objetivo
pre-escrito sigue siendo un objetivo sin revisar.

El flujo unificado completo: `cg init` scaffoldea el contrato del repo → `cg plan` descompone
el requerimiento → `cg approve` revisa cada fase → `cg begin` y `cg next-task` ejecutan →
`cg verify` audita → `cg commit` avanza.

## Hook de pre-commit

Los hooks de Git se instalan automáticamente mediante `cg init` o se activan por clon con
`git config core.hooksPath .githooks`:

- **`.githooks/commit-msg`**: Rechaza mensajes de commit que no siguen Conventional
  Commits (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `release`). Se saltea con
  `git commit --no-verify`.
- **`.githooks/pre-commit`**: Rechaza commits que tocan más de un umbral de
  archivos cuando ningún change muestra que el protocolo estuvo activo (una
  fase completada o una transacción abierta).
- **Umbral**: `hook.file_threshold` en el manifest de un change, o la
  variable de entorno `CONTEXT_GUARD_FILE_THRESHOLD`, que gana sobre el
  manifest. Con varios changes activos, aplica el valor configurado más
  estricto.
- **`files_in_scope`**: los archivos staged fuera del scope declarado de un
  change en EXECUTE generan un warning, nunca un bloqueo.
- **Bypass**: `CONTEXT_GUARD_BYPASS=1 CONTEXT_GUARD_BYPASS_REASON='...' git
  commit ...`. Todo bypass queda anotado en `.context-guard/bypass.log` con
  timestamp y la lista de archivos — la puerta sigue abierta, pero nadie
  pasa por ella sin quedar registrado.

## Códigos de salida

| Código | Nombre | Significado |
|---|---|---|
| `[0]` | `EXIT_OK` | Éxito. |
| `[1]` | `EXIT_GENERIC` | Manifest corrupto, o no hay sesión en este context/change. |
| `[2]` | `EXIT_LOCK_HELD` | Otro agente tiene el lock o el claim. Reintentable con backoff. |
| `[3]` | `EXIT_LOCK_CONTENDED` | Perdiste la carrera de takeover de un lock stale. Reintentable. |
| `[4]` | `EXIT_VALIDATION` | Artefacto faltante, `[PENDING]` restante, artefacto demasiado largo, o texto que no es inglés. |
| `[5]` | `EXIT_BAD_TRANSITION` | La fase pedida no es el `lock_phase` actual del DAG. No reintentar. |
| `[6]` | `EXIT_APPROVAL_REQUIRED` | `commit` a EXECUTE sin un `cg approve` registrado. Solo lo resuelve un humano. |

## Adapters y configuración de permisos

Dentro del paquete, en `context_guard/_data/hosts/{claude-code,opencode,
antigravity,cursor}/`, viven wrappers finos por harness — cada uno apunta a
`phases/{plan,execute,verify}.md` en vez de duplicarlos. Cómo poner
`cg approve` detrás del permission prompt de cada harness está documentado en
[docs/adapters/](docs/adapters/), un `PERMISSIONS.md` por host, junto con el
checklist de smoke-test manual en
[docs/adapters/VERIFY.md](docs/adapters/VERIFY.md).
`cg setup` instala el que corresponde a cada host detectado. Los
adapters de OpenCode y Antigravity están portados de state-guard y cubiertos
solo por tests estáticos — no se corrieron contra un host real de ninguno de
los dos.

## Cómo se compara

context-guard no es una herramienta que escribe specs, y no pretende serlo.

| | context-guard | spec-kit | Kiro | `AGENTS.md` pelado |
|---|---|---|---|---|
| Genera specs/planes a partir de un prompt | No | Sí | Sí | No |
| Experiencia nativa de IDE | No (CLI + MCP) | Depende del host | Sí | No |
| Fuerza el orden de fases en código, no en prosa | **Sí** | No | Parcial | No |
| Manifest atómico, sobrevive a un crash a mitad de fase | **Sí** | No | No | No |
| Locking a nivel de OS para agentes concurrentes | **Sí** | No | No | No |
| Gate de aprobación humana antes de ejecutar | **Sí** | No | No | No |

Lo que hacemos y ellos no: enforcement en runtime de una máquina de estados
que sobrevive al proceso del agente. Lo que ellos hacen y nosotros no: todo
lo referido a convertir un prompt en un buen spec en primer lugar. Usá
context-guard junto con cualquiera de ellos que ya te genere el
`objective.md` — está diseñado para consumir uno, no para escribirlo.

[disciplined-scaffold](https://github.com/fdomerlo/disciplined-scaffold) era
el paso liviano previo a este: disciplina de fases en markdown, sin estado
transaccional. Sus capacidades (contrato de agentes, scaffolding, hooks de commits convencionales, planificación multi-fase estructurada) ahora están nativamente integradas en context-guard (`cg init` y `cg plan`). Para proyectos con planes existentes, `cg new --from-plan` lee los `PLAN-N.md` legados — ver [Desde un plan por fases](#desde-un-plan-por-fases).

## Desarrollo

```bash
git clone https://github.com/fdomerlo/context-guard.git
cd context-guard && uv venv && uv pip install -e .
python -m unittest discover -s tests
```

Framework: `unittest`. Cada fix se entrega con un test adversarial que
reproduce el bypass que cierra; ver `tests/test_adversarial_*.py` para el
patrón. Los tests solo escriben bajo `tempfile.mkdtemp()`; los únicos
fixtures en disco son los planes de ejemplo de solo lectura en
`tests/fixtures/`, que existen porque `--from-plan` parsea documentos en vez
de generarlos.

## Licencia

MIT — ver [LICENSE](LICENSE).
