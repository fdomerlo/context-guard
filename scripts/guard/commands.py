"""Business logic for all guard CLI commands.

Every function returns a CommandResult or raises a GuardError.
No function calls sys.exit() — that's cli.py's job.
"""

import os
import shutil
from datetime import datetime

from guard.paths import get_paths, generate_agent_id, TASK_LINE_RE, MAX_ARTIFACT_CHARS
from guard.manifest import load_manifest, save_manifest
from guard.locking import with_write_lock, acquire
from guard.errors import (
    CommandResult,
    EXIT_OK,
    EXIT_LOCK_HELD,
    EXIT_VALIDATION,
    ValidationError,
)


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------

def cmd_check_lock(context):
    """Solo lectura — para mostrar estado al desarrollador. NO usar como gate
    antes de acquire/claim: usar `claim` directamente evita la carrera de
    secuenciar dos llamadas separadas."""
    m = load_manifest(context)
    if not m or not m.get("lock", {}).get("held", False):
        return CommandResult("FREE", EXIT_OK)

    acquired = datetime.fromisoformat(m["lock"]["acquired_at"])
    elapsed = int((datetime.now() - acquired).total_seconds())
    ttl = m["lock"].get("ttl_seconds", 1800)

    if elapsed > ttl:
        msg = f"STALE|{elapsed}|{ttl}"
    else:
        msg = f"ACTIVE|{elapsed}|{ttl}|{m['lock'].get('acquired_by')}"
    return CommandResult(msg, EXIT_OK)


def cmd_claim(context, ttl):
    """Un solo comando: check + acquire atómico. Reemplaza la secuencia
    check-lock → acquire del protocolo viejo, que dependía de que el modelo
    encadenara bien dos llamadas."""
    def _do():
        return acquire(context, ttl)
    return with_write_lock(context, _do)


def cmd_release(context):
    """Libera el lock de sesión."""
    def _do():
        p = get_paths(context)
        m = load_manifest(context)
        if m and "lock" in m:
            m["lock"]["held"] = False
            m["lock"]["acquired_at"] = None
            m["lock"]["acquired_by"] = None
            save_manifest(context, m)
        if os.path.exists(p["lock"]):
            os.remove(p["lock"])
        return CommandResult("SUCCESS|LOCK_RELEASED", EXIT_OK)
    return with_write_lock(context, _do)


# ---------------------------------------------------------------------------
# Tareas (lock granular por ítem)
# ---------------------------------------------------------------------------

def cmd_claim_task(context, task_id, agent_id=None):
    """Reclama una tarea específica para un agente."""
    if not agent_id:
        agent_id = generate_agent_id()

    def _do():
        m = load_manifest(context)
        if not m:
            return CommandResult("FAIL|NO_SESSION", EXIT_LOCK_HELD)
        tasks = m.setdefault("task_claims", {})
        existing = tasks.get(task_id)
        if existing and existing["status"] == "claimed":
            return CommandResult(
                f"FAIL|TASK_CLAIMED|{existing['agent_id']}",
                EXIT_LOCK_HELD,
            )
        tasks[task_id] = {
            "status": "claimed",
            "agent_id": agent_id,
            "claimed_at": datetime.now().isoformat(),
        }
        save_manifest(context, m)
        return CommandResult(f"SUCCESS|TASK_CLAIMED|{task_id}", EXIT_OK)
    return with_write_lock(context, _do)


def cmd_release_task(context, task_id, agent_id=None, force=False):
    """Libera una tarea. Si se pasa agent_id, valida ownership (a menos que
    force=True)."""
    def _do():
        m = load_manifest(context)
        if not m:
            return CommandResult("FAIL|NO_SESSION", EXIT_LOCK_HELD)
        tasks = m.get("task_claims", {})
        task = tasks.get(task_id)
        if not task or task["status"] != "claimed":
            return CommandResult(
                f"FAIL|TASK_NOT_CLAIMED|{task_id}",
                EXIT_LOCK_HELD,
            )
        # Ownership validation
        if agent_id and not force and task["agent_id"] != agent_id:
            return CommandResult(
                f"FAIL|OWNERSHIP_MISMATCH|{task_id}|owner={task['agent_id']}",
                EXIT_LOCK_HELD,
            )
        task["status"] = "done"
        task["released_at"] = datetime.now().isoformat()
        save_manifest(context, m)
        return CommandResult(f"SUCCESS|TASK_RELEASED|{task_id}", EXIT_OK)
    return with_write_lock(context, _do)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _count_tasks_in_file(filepath):
    """Cuenta checkboxes en un archivo markdown.

    Returns:
        (total, completed) o None si el archivo no existe.
    """
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    total = completed = 0
    for line in lines:
        m = TASK_LINE_RE.match(line)
        if not m:
            continue
        total += 1
        if m.group(1).lower() == "x":
            completed += 1
    return total, completed


def cmd_check_completion(context):
    """Parser determinista de blockers_todo.md y tasks.md — el modelo no
    cuenta checkboxes a mano. Reporta ambos archivos si existen."""
    p = get_paths(context)
    lines = []

    blockers = _count_tasks_in_file(p["blockers"])
    tasks = _count_tasks_in_file(p["tasks"])

    agg_total = 0
    agg_completed = 0

    if blockers is not None:
        b_total, b_completed = blockers
        b_all = b_total > 0 and b_completed == b_total
        lines.append(f"source=blockers_todo.md")
        lines.append(f"total={b_total}")
        lines.append(f"completed={b_completed}")
        lines.append(f"all_complete={'true' if b_all else 'false'}")
        agg_total += b_total
        agg_completed += b_completed

    if tasks is not None:
        t_total, t_completed = tasks
        t_all = t_total > 0 and t_completed == t_total
        if blockers is not None:
            lines.append("")  # blank separator
        lines.append(f"source=tasks.md")
        lines.append(f"total={t_total}")
        lines.append(f"completed={t_completed}")
        lines.append(f"all_complete={'true' if t_all else 'false'}")
        agg_total += t_total
        agg_completed += t_completed

    if blockers is None and tasks is None:
        lines.append("total=0")
        lines.append("completed=0")
        lines.append("all_complete=false")
        agg_all = False
    else:
        agg_all = agg_total > 0 and agg_completed == agg_total

    # Aggregate only if both sources exist
    if blockers is not None and tasks is not None:
        lines.append("")
        lines.append(f"aggregate_total={agg_total}")
        lines.append(f"aggregate_completed={agg_completed}")
        lines.append(f"aggregate_all_complete={'true' if agg_all else 'false'}")

    return CommandResult("\n".join(lines), EXIT_OK)


def cmd_validate(context):
    """Lint de los artefactos de sesión: existencia + cap de longitud.
    Determinista, no depende de que el modelo se autoevalúe.

    Requiere: objective.md + snapshot.md + al menos uno de (blockers_todo.md, tasks.md).
    Opcionalmente valida: review-report.md, verify-report.md si existen.
    """
    p = get_paths(context)
    session_dir = p["base"]

    # Artefactos obligatorios (siempre deben existir)
    required = ["objective.md", "snapshot.md"]
    # Al menos uno de estos debe existir
    task_files = ["blockers_todo.md", "tasks.md"]
    # Artefactos opcionales (se validan solo si existen)
    optional = ["review-report.md", "verify-report.md"]

    failures = []

    for fname in required:
        path = os.path.join(session_dir, fname)
        if not os.path.exists(path):
            failures.append(f"MISSING|{fname}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if len(content) > MAX_ARTIFACT_CHARS:
            failures.append(f"TOO_LONG|{fname}|{len(content)}/{MAX_ARTIFACT_CHARS}")

    # Al menos un archivo de tareas debe existir
    has_task_file = False
    for fname in task_files:
        path = os.path.join(session_dir, fname)
        if os.path.exists(path):
            has_task_file = True
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if len(content) > MAX_ARTIFACT_CHARS:
                failures.append(f"TOO_LONG|{fname}|{len(content)}/{MAX_ARTIFACT_CHARS}")
    if not has_task_file:
        failures.append("MISSING|blockers_todo.md or tasks.md")

    # Artefactos opcionales — solo validar tamaño si existen
    for fname in optional:
        path = os.path.join(session_dir, fname)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if len(content) > MAX_ARTIFACT_CHARS:
                failures.append(f"TOO_LONG|{fname}|{len(content)}/{MAX_ARTIFACT_CHARS}")

    if failures:
        raise ValidationError(failures)

    return CommandResult("SUCCESS|VALIDATE_OK", EXIT_OK)


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------

def cmd_archive(context):
    """Archiva un contexto completado.

    1. Verifica que todas las tareas estén completas
    2. Valida artefactos
    3. Acquiere session lock
    4. Copia sesión a archive/
    5. Verifica que el archive no esté vacío
    6. Borra sesión original
    7. Libera session lock
    """
    p = get_paths(context)

    # 1. Verificar completitud
    completion = cmd_check_completion(context)
    output = completion.message
    # Determinar si todo está completo
    all_complete = False
    for line in output.split("\n"):
        # Si hay aggregate, usar ese; si no, usar el único all_complete
        if line.startswith("aggregate_all_complete="):
            all_complete = line.split("=")[1] == "true"
            break
        if line.startswith("all_complete="):
            all_complete = line.split("=")[1] == "true"

    if not all_complete:
        return CommandResult(
            "FAIL|ARCHIVE_BLOCKED|tasks_incomplete",
            EXIT_VALIDATION,
        )

    # 2. Validar artefactos (puede lanzar ValidationError)
    cmd_validate(context)

    # 3-7. Lock + copy + verify + delete + unlock
    def _do():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_dir = os.path.join(p["archive"], f"{timestamp}_{context}")

        # Copiar sesión a archive
        shutil.copytree(p["base"], archive_dir)

        # Verificar que el archive no esté vacío
        archive_contents = os.listdir(archive_dir)
        if not archive_contents:
            return CommandResult(
                "FAIL|ARCHIVE_EMPTY",
                EXIT_VALIDATION,
            )

        # Borrar contenido de la sesión original
        for item in os.listdir(p["base"]):
            item_path = os.path.join(p["base"], item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)

        return CommandResult(
            f"SUCCESS|ARCHIVED|{archive_dir}",
            EXIT_OK,
        )

    # Acquire session lock con TTL corto para el archivado
    claim_result = cmd_claim(context, ttl=60)
    if claim_result.exit_code != EXIT_OK:
        return claim_result

    try:
        result = _do()
    finally:
        # Liberar session lock — los archivos de sesión ya fueron borrados,
        # pero el lockfile podría persistir
        lock_path = get_paths(context)["lock"]
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except FileNotFoundError:
                pass

    return result
