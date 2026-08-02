# Tutorial: memoria persistente para tu asistente de programación con context-guard

*Para personas que usan asistentes de IA (Claude Code, OpenCode, Antigravity) y quieren que no se olviden de lo que estaban haciendo. No hace falta ser experto: si sabés abrir una terminal y copiar comandos, podés seguir esta guía.*

---

## 1. El problema que esto resuelve (leelo aunque tengas apuro)

Cuando trabajás con un asistente de IA en un proyecto, todo lo que "sabe" sobre tu trabajo vive en la conversación actual. Y las conversaciones se terminan: se llena el contexto, se corta la sesión, cerrás la ventana, o el asistente "compacta" la charla y pierde detalles. Al día siguiente abrís una sesión nueva y el asistente arranca de cero: no sabe en qué estaba, qué tareas ya hizo, ni qué decisiones habían tomado juntos.

El resultado conocido: repetir explicaciones, tareas que se hacen dos veces, tareas que se saltean porque "el asistente creía" que ya estaban, y decisiones de diseño que se contradicen entre sesiones.

**context-guard es una libreta de estado en disco.** Piénsalo como los *puntos de guardado* de un videojuego: cada vez que el asistente completa un paso, el estado queda escrito en archivos dentro de tu proyecto. Si la sesión muere en cualquier momento, la próxima sesión lee esa libreta y continúa exactamente donde quedó — no donde *cree* que quedó.

Tres cosas concretas que obtenés:

1. **Continuidad.** Cerrás la sesión un martes, la retomás el jueves, y el asistente sabe la fase exacta, la tarea exacta y el resumen de lo hecho.
2. **Orden.** El trabajo pasa por tres fases obligatorias — planificar, ejecutar, verificar — y el asistente no puede saltearse ninguna mientras use la herramienta.
3. **Control.** Entre el plan y el código hay un punto de aprobación que es tuyo: el asistente te presenta el plan y no puede empezar a escribir código hasta que vos lo apruebes con un comando.

Una aclaración honesta, porque este proyecto se toma en serio la honestidad: context-guard ordena y protege a un asistente que *usa* la herramienta. No es una jaula — un asistente podría ignorarla. Por eso la instalación incluye un paso donde tu propia aplicación de IA (no context-guard) queda configurada para pedirte confirmación en el momento clave. Eso se explica en el paso 4.

---

## 2. Qué necesitás antes de empezar

- **Una computadora con terminal.** macOS, Linux, o Windows con WSL.
- **Python 3.10 o más nuevo.** Verificalo con `python3 --version`. Si no lo tenés, instalalo desde [python.org](https://www.python.org/downloads/).
- **git.** Verificalo con `git --version`.
- **Un asistente de programación instalado**: Claude Code, OpenCode o Antigravity. Cualquiera de los tres funciona; los comandos del asistente son los mismos.
- **Un proyecto** donde trabajar. Puede ser uno existente o una carpeta nueva; solo necesita ser un repositorio git (si no lo es, entrá a la carpeta y corré `git init`).

---

## 3. Instalación (dos líneas, una sola vez)

Abrí la terminal y corré:

```bash
uv tool install context-guard-cli
cg setup
```

La primera línea instala la herramienta. La segunda detecta qué asistentes
tenés instalados y los configura: les agrega dos comandos nuevos, `/cg-new` y
`/cg-continue`, y deja lista la configuración de permisos del punto de
aprobación (paso 4). Al terminar imprime la lista exacta de archivos que
tocó — nada oculto. Podés correrlo las veces que quieras: si ya está
instalado, no duplica nada.

¿No tenés `uv`? `pipx install context-guard-cli` hace lo mismo. Si ninguno de
los dos está disponible, `pip install context-guard-cli` también funciona,
como alternativa.

> **Ojo con esta:** `uv pip install context-guard-cli` *no* es lo mismo que
> `uv tool install`. Instala la herramienta adentro del entorno virtual de
> tu proyecto actual, no en tu máquina — y `cg setup` necesita que `cg` esté
> disponible en cualquier terminal, no solo dentro de ese proyecto.

Verificá que quedó todo:

```bash
cg --help
```

Si ves la lista de comandos, listo. `cg` es el nombre corto de la
herramienta; todo lo que hagas con context-guard empieza con `cg`.

**Y eso es todo.** No hay un paso por proyecto: la primera vez que arranques
un cambio en un proyecto nuevo, `cg new` escribe ahí lo que falte. No
necesitás descargar este repositorio ni copiar archivos a mano.

> **¿Dónde quedó instalado?** `uv tool install` y `pipx` ponen `cg` en un
> directorio propio (`~/.local/bin` en Linux/macOS típicamente) y lo agregan
> al PATH por vos. `pip install` sin `--user` lo deja donde viva tu Python
> del sistema; con `--user`, en `~/.local/bin` también. Si el paso de
> verificación de arriba no encuentra `cg`, es casi siempre esto: el
> directorio existe pero tu terminal no lo tiene en el PATH todavía.

> **Si algo falla:** el error más común es que la instalación terminó bien
> pero la terminal no encuentra `cg`. Cerrá y reabrí la terminal. Si
> persiste, probá `python3 -m pip install --user context-guard-cli` y de
> nuevo cerrar/reabrir.

---

## 3.1. Cómo actualizar

Cuando salga una versión nueva, dos comandos en uno:

```bash
uv tool upgrade context-guard-cli && cg setup
```

*(Con pipx: `pipx upgrade context-guard-cli && cg setup`.)*

**Por qué son dos y no uno:** el primero actualiza el programa; el segundo
vuelve a copiar los comandos y la configuración dentro de tu asistente. Si
hacés solo el primero, tu asistente sigue usando las instrucciones viejas y
las mejoras de la versión nueva no aparecen. Correr `cg setup` de más nunca
rompe nada.

**Tus proyectos viejos siguen como estaban.** Las guías de fase que se
copiaron dentro de cada proyecto no se pisan al actualizar — a propósito,
para no borrar cambios que hayas hecho. Los proyectos nuevos arrancan con
las guías actualizadas.

---

## 4. El punto de aprobación: tu único trabajo obligatorio

Acá está el corazón del sistema, y es importante que lo entiendas antes del primer uso.

Cuando el asistente termina de planificar, intenta pasar a la fase de ejecución. context-guard se lo niega con un mensaje claro: *falta la aprobación humana*. El asistente entonces se detiene y te pide que corras vos este comando:

```bash
cg approve
```

Sin flags: con un solo cambio activo, context-guard sabe cuál es, y anota tu
usuario del sistema como responsable. Si tenés varios cambios en paralelo,
agregá `--change nombre-del-cambio`.

Ese comando es **solo tuyo**. La configuración que instaló el paso 3 hace que, si el asistente intentara correrlo por su cuenta, tu aplicación de IA te muestre un cartel de confirmación antes de permitirlo — y ahí simplemente decís que no. El resultado práctico: **ningún código se escribe sin que vos hayas leído el plan y dado el visto bueno.** Es un semáforo con tu nombre.

Cuando aparezca ese cartel de confirmación en tu asistente pidiendo permiso para `cg approve`, rechazalo siempre — la aprobación la das vos desde tu terminal, no el asistente desde la suya. Y una advertencia: si el cartel ofrece un botón tipo "permitir siempre", no lo uses para este comando, porque desactiva el semáforo por el resto de la sesión.

---

## 5. Tu primer cambio, paso a paso

Un "cambio" (change) es una unidad de trabajo con nombre: una feature, un arreglo, una refactorización. Vamos a hacer uno completo.

**Paso 1 — Crear el cambio.** En tu asistente, escribí:

```
/cg-new login-form
```

*(o el nombre que describa tu tarea: `arreglar-boton-pago`, `migrar-base-datos`...)*

El asistente crea el cambio y entra automáticamente en la fase **PLAN**. Detrás de escena apareció una carpeta `.context-guard/changes/login-form/` en tu proyecto — esa es la libreta. No la edites a mano nunca; para eso están los comandos.

**Paso 2 — Planificar juntos.** El asistente va a investigar tu proyecto y escribir tres cosas: el objetivo, una foto del estado actual del código, y la lista de tareas concretas. Conversá con él normalmente: pedile ajustes, agregá contexto, marcá lo que no querés. Cuando el plan te cierre, el asistente intentará avanzar... y se topará con el semáforo del paso 4.

**Paso 3 — Aprobar.** Leé el plan (está en `.context-guard/changes/login-form/`, en archivos legibles: `objective.md`, `tasks.md`). Si estás de acuerdo, en TU terminal:

```bash
cg approve
```

Avisale al asistente que ya aprobaste, y ahora sí: pasa a **EXECUTE**.

**Paso 4 — Ejecutar.** El asistente toma las tareas de la lista una por una — pide la siguiente con `cg next-task`, la hace, la marca completada. Cada tarea marcada queda escrita en disco al instante. Vos podés mirar el avance cuando quieras:

```bash
cg status
```

**Paso 5 — Verificar.** Con todas las tareas completas, el asistente pasa a **VERIFY**: revisa su propio trabajo, corre los tests, y escribe dos reportes (revisión y verificación). Si algo falló, vuelve a corregir. Al terminar, el cambio se archiva con su historia completa.

---

## 6. La magia: qué pasa cuando la sesión se muere

Esto es lo que viniste a buscar. Supongamos que a mitad de la fase EXECUTE se te corta la sesión — contexto lleno, se colgó la app, apagaste la máquina, lo que sea.

Abrí una sesión nueva del asistente en el mismo proyecto y escribí:

```
/cg-continue
```

Eso es todo. El comando lee la libreta y le entrega al asistente el estado real: qué cambio está activo, en qué fase, qué tareas están hechas (con tilde en disco, no en la memoria de nadie), cuál es la siguiente, y el resumen de la última sesión. El asistente no reconstruye nada de memoria ni te pide que le expliques de nuevo — continúa desde el punto de guardado.

Probalo a propósito la primera vez: cerrá la sesión en medio del trabajo y reabrila. Ver al asistente retomar la tarea exacta donde quedó es el momento en que esta herramienta se paga sola.

---

## 7. Preguntas que te vas a hacer

**"El asistente dice FAIL con un número de error, ¿qué hago?"** Los números son deliberadamente simples: **2** significa que otra sesión tiene tomado el cambio (esperá o mirá el punto siguiente); **4**, que falta completar un artefacto del plan (algo quedó como `[PENDING]`); **5**, que intentó una fase fuera de orden (la herramienta lo frenó — está funcionando); **6**, que falta tu aprobación (paso 4). El asistente sabe interpretarlos solo; esto es para que vos también entiendas qué pasa.

**"Quedó todo trabado y nadie está trabajando."** Pasa si una sesión murió de forma fea. Corré el médico:

```bash
cg doctor --fix
```

Diagnostica y libera lo que quedó colgado de procesos muertos. Nunca resuelvas un traba editando los archivos de `.context-guard/` a mano.

**"¿Puedo tener varios cambios a la vez?"** Sí — cada uno con su nombre, su libreta y su fase, independientes. Si hay varios activos, los comandos te van a pedir que especifiques cuál con `--change`; nunca adivinan.

**"¿Esto reemplaza a git?"** No: lo complementa. git guarda la historia de tu *código*; context-guard guarda el estado del *proceso de trabajo* (fase, tareas, aprobaciones). De hecho se llevan bien: la instalación incluye un guardián opcional de git que te avisa si el asistente intenta un commit gigante sin haber pasado por el protocolo.

**"¿Qué gano de verdad, en una frase?"** Que el conocimiento sobre tu trabajo deje de vivir en una conversación frágil y pase a vivir en tu disco, con orden de fases y tu firma antes de cada tramo de código.

**"¿Y si el asistente decide ignorar todo esto?"** Puede — la herramienta lo ordena, no lo encarcela (el README lo explica en la sección *Threat Model*, sin marketing). En la práctica no pasa: los comandos instalados le indican el protocolo desde el primer mensaje, y el único momento de riesgo real — aprobarse un plan a sí mismo — está cubierto por el cartel de confirmación de tu propia aplicación, que corre fuera de su alcance.

---

## 8. Chuleta de referencia

| Momento | Vos hacés | El asistente hace |
|---|---|---|
| Empezar algo nuevo | `/cg-new nombre` | Crea el cambio, entra a PLAN |
| Revisar el plan | Leés `objective.md` y `tasks.md` | Espera tu aprobación |
| Aprobar | `cg approve` | Pasa a EXECUTE |
| Ver el avance | `cg status` | — |
| Retomar tras un corte | `/cg-continue` | Continúa donde quedó |
| Destrabar | `cg doctor --fix` | — |
| Actualizar | `uv tool upgrade context-guard-cli && cg setup` | — |

Instalación (una vez): `uv tool install context-guard-cli` y luego `cg setup` una vez por máquina.

Documentación completa, en inglés y español, en el [repositorio](https://github.com/fdomerlo/context-guard).
