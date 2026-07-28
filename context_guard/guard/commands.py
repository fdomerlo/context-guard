"""Business logic for all guard CLI commands.

Every function returns a CommandResult or raises a GuardError.
No function calls sys.exit() — that's cli.py's job.
"""

import os
import shutil
from datetime import datetime

from .paths import get_paths, generate_agent_id, TASK_LINE_RE, MAX_ARTIFACT_CHARS
from .manifest import load_manifest, save_manifest
from .locking import with_write_lock, acquire
from .transaction import cmd_begin, cmd_commit, cmd_rollback, cmd_checkpoint
from .errors import (
    CommandResult,
    EXIT_OK,
    EXIT_LOCK_HELD,
    EXIT_GENERIC,
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
            return CommandResult("FAIL|NO_SESSION", EXIT_GENERIC)
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
            return CommandResult("FAIL|NO_SESSION", EXIT_GENERIC)
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
    """Parser determinista de tasks.md — el modelo no
    cuenta checkboxes a mano."""
    p = get_paths(context)
    lines = []

    tasks = _count_tasks_in_file(p["tasks"])

    if tasks is not None:
        t_total, t_completed = tasks
        t_all = t_total > 0 and t_completed == t_total
        lines.append(f"source=tasks.md")
        lines.append(f"total={t_total}")
        lines.append(f"completed={t_completed}")
        lines.append(f"all_complete={'true' if t_all else 'false'}")
    else:
        lines.append("total=0")
        lines.append("completed=0")
        lines.append("all_complete=false")

    return CommandResult("\n".join(lines), EXIT_OK)


def cmd_validate(context, max_length=None):
    """Lint de los artefactos de sesión: existencia + cap de longitud.
    Determinista, no depende de que el modelo se autoevalúe.

    Requiere: objective.md + snapshot.md + tasks.md.
    Opcionalmente valida: review-report.md, verify-report.md si existen.
    """
    p = get_paths(context)
    session_dir = p["base"]

    if max_length is None:
        from .paths import MAX_ARTIFACT_CHARS
        max_length = MAX_ARTIFACT_CHARS

    # Artefactos obligatorios (siempre deben existir)
    required = ["objective.md", "snapshot.md"]
    # El archivo de tareas debe existir
    task_files = ["tasks.md"]
    # El archivo de tareas debe existir
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
        if len(content) > max_length:
            failures.append(f"TOO_LONG|{fname}|{len(content)}/{max_length}")

    # Archivo de tareas debe existir
    path = os.path.join(session_dir, "tasks.md")
    if not os.path.exists(path):
        failures.append("MISSING|tasks.md")
    else:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if len(content) > max_length:
            failures.append(f"TOO_LONG|tasks.md|{len(content)}/{max_length}")

    # Artefactos opcionales — solo validar tamaño si existen
    for fname in optional:
        path = os.path.join(session_dir, fname)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if len(content) > max_length:
                failures.append(f"TOO_LONG|{fname}|{len(content)}/{max_length}")

    # Validacion estricta de idioma
    for fname in required + task_files + optional:
        path = os.path.join(session_dir, fname)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            continue
        spanish_indicators = ["á", "é", "í", "ó", "ú", "ñ", "¿", "¡"]
        spanish_count = sum(content.lower().count(c) for c in spanish_indicators)
        if spanish_count > 5:
            failures.append(f"LANGUAGE_BOUNDARY|{fname}|Spanish text detected. Artifacts must be in English.")

    if failures:
        raise ValidationError(failures)

    return CommandResult("SUCCESS|VALIDATE_OK", EXIT_OK)


def _parse_task_lines(filepath):
    """Parse un archivo de tareas y retorna lista de (task_id, description, status).

    status es 'done', 'wip', o 'pending'.
    task_id se extrae del primer token numérico (ej. '1.1') o se genera
    como índice secuencial.
    """
    import re
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    tasks = []
    idx = 0
    task_id_re = re.compile(r"^(\d+(?:\.\d+)?)\s+(.*)$")
    for line in lines:
        m = TASK_LINE_RE.match(line)
        if not m:
            continue
        idx += 1
        marker = m.group(1)
        description = m.group(2).strip()
        if marker.lower() == "x":
            status = "done"
        elif marker == "/":
            status = "wip"
        else:
            status = "pending"
        # Extract task_id from description (e.g. "1.1 Create the foo")
        id_match = task_id_re.match(description)
        if id_match:
            task_id = id_match.group(1)
        else:
            task_id = str(idx)
        tasks.append((task_id, description, status))
    return tasks


def cmd_next_task(context, agent_id=None):
    """Encuentra la siguiente tarea pendiente no reclamada y la reclama
    atómicamente. Elimina la necesidad de que el modelo itere manualmente."""
    if not agent_id:
        agent_id = generate_agent_id()

    p = get_paths(context)
    m = load_manifest(context)
    if not m:
        return CommandResult("FAIL|NO_SESSION", EXIT_GENERIC)

    # Buscar en tasks.md
    all_tasks = []
    filepath = p["tasks"]
    all_tasks.extend(_parse_task_lines(filepath))

    claimed = m.get("task_claims", {})

    for task_id, description, status in all_tasks:
        if status == "done":
            continue
        existing = claimed.get(task_id)
        if existing and existing["status"] == "claimed":
            continue
        # Tarea disponible — reclamarla atómicamente
        result = cmd_claim_task(context, task_id, agent_id)
        if result.exit_code == EXIT_OK:
            return CommandResult(
                f"SUCCESS|NEXT_TASK|{task_id}|{description}",
                EXIT_OK,
            )

    return CommandResult("DONE|NO_PENDING_TASKS", EXIT_OK)


def cmd_status(context):
    """Resumen one-shot del estado del contexto para rehidratación rápida."""
    p = get_paths(context)
    m = load_manifest(context)
    lines = []

    if not m:
        return CommandResult("FAIL|NO_SESSION", EXIT_GENERIC)

    lines.append(f"CONTEXT: {m.get('context_name', context)}")

    # Objective
    obj_path = os.path.join(p["base"], "objective.md")
    if os.path.exists(obj_path):
        with open(obj_path, "r", encoding="utf-8") as f:
            obj_text = f.read().strip()
        # Take first non-header, non-empty line as summary
        for obj_line in obj_text.split("\n"):
            stripped = obj_line.strip()
            if stripped and not stripped.startswith("#"):
                lines.append(f"OBJECTIVE: {stripped}")
                break
    else:
        lines.append("OBJECTIVE: (missing)")

    # Progress
    completion = cmd_check_completion(context)
    for comp_line in completion.message.split("\n"):
        if comp_line.startswith("total="):
            total = comp_line.split("=")[1]
        if comp_line.startswith("completed="):
            completed = comp_line.split("=")[1]
        if comp_line.startswith("aggregate_total="):
            total = comp_line.split("=")[1]
        if comp_line.startswith("aggregate_completed="):
            completed = comp_line.split("=")[1]
    lines.append(f"PROGRESS: {completed}/{total} tasks complete")

    # Next pending task
    all_tasks = []
    filepath = p["tasks"]
    all_tasks.extend(_parse_task_lines(filepath))
    claimed = m.get("task_claims", {})
    next_task = None
    for task_id, description, status in all_tasks:
        if status == "done":
            continue
        existing = claimed.get(task_id)
        if existing and existing["status"] == "claimed":
            continue
        next_task = f"{task_id} - {description}"
        break
    if next_task:
        lines.append(f"NEXT: {next_task}")
    else:
        lines.append("NEXT: (none)")

    # Lock status
    lock = m.get("lock", {})
    if lock.get("held"):
        lines.append(f"LOCK: HELD by {lock.get('acquired_by', 'unknown')}")
    else:
        lines.append("LOCK: FREE")

    return CommandResult("\n".join(lines), EXIT_OK)


# ---------------------------------------------------------------------------
# Doctor — diagnóstico de salud
# ---------------------------------------------------------------------------

def cmd_doctor(context):
    """Diagnóstico de salud del contexto. Detecta problemas comunes que un
    modelo free-tier puede causar: artefactos faltantes, language boundary
    violations, task claims huérfanos, manifest corrupto."""
    p = get_paths(context)
    findings = []

    # 1. Check session exists
    m = load_manifest(context)
    if not m:
        findings.append("ERROR: No session found (manifest.json missing)")
        return CommandResult("\n".join(findings), EXIT_GENERIC)
    findings.append("OK: manifest.json is valid")

    # 2. Check required artifacts
    required = ["objective.md", "snapshot.md"]
    task_files = ["tasks.md"]
    for fname in required:
        path = os.path.join(p["base"], fname)
        if not os.path.exists(path):
            findings.append(f"ERROR: {fname} is missing")
        else:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if len(content) > MAX_ARTIFACT_CHARS:
                findings.append(
                    f"WARN: {fname} exceeds size limit "
                    f"({len(content)}/{MAX_ARTIFACT_CHARS} chars)")
            else:
                findings.append(f"OK: {fname} exists ({len(content)} chars)")

    has_task_file = False
    for fname in task_files:
        path = os.path.join(p["base"], fname)
        if os.path.exists(path):
            has_task_file = True
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if len(content) > MAX_ARTIFACT_CHARS:
                findings.append(
                    f"WARN: {fname} exceeds size limit "
                    f"({len(content)}/{MAX_ARTIFACT_CHARS} chars)")
            else:
                findings.append(f"OK: {fname} exists ({len(content)} chars)")
    if not has_task_file:
        findings.append("ERROR: No task file found (need tasks.md)")

    # 3. Check for non-ASCII in artifacts (removed from doctor, moved to validate)

    # 4. Check stale task claims
    claims = m.get("task_claims", {})
    for task_id, claim in claims.items():
        if claim.get("status") == "claimed":
            claimed_at = claim.get("claimed_at", "")
            agent = claim.get("agent_id", "unknown")
            if claimed_at:
                try:
                    claimed_time = datetime.fromisoformat(claimed_at)
                    elapsed = (datetime.now() - claimed_time).total_seconds()
                    if elapsed > 1800:  # 30 minutes
                        findings.append(
                            f"WARN: Task {task_id} claimed by {agent} "
                            f"{int(elapsed)}s ago (possibly stale)")
                    else:
                        findings.append(
                            f"OK: Task {task_id} claimed by {agent} "
                            f"({int(elapsed)}s ago)")
                except (ValueError, TypeError):
                    findings.append(
                        f"WARN: Task {task_id} has unparseable claimed_at: {claimed_at}")

    # 5. Lock status
    lock = m.get("lock", {})
    if lock.get("held"):
        acquired_at = lock.get("acquired_at")
        if acquired_at:
            try:
                elapsed = (datetime.now() - datetime.fromisoformat(acquired_at)).total_seconds()
                ttl = lock.get("ttl_seconds", 1800)
                if elapsed > ttl:
                    findings.append(
                        f"WARN: Session lock is stale "
                        f"(held {int(elapsed)}s, TTL={ttl}s)")
                else:
                    findings.append(
                        f"OK: Session lock active ({int(elapsed)}s/{ttl}s)")
            except (ValueError, TypeError):
                findings.append("WARN: Session lock has unparseable timestamp")
    else:
        findings.append("OK: Session lock is FREE")
    return CommandResult("\n".join(findings), EXIT_OK)



# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------

def cmd_archive(context):
    """Archiva un contexto completado.

    1. Verifica que todas las tareas estén completas
    2. Valida artefactos
    3. Acquiere session lock (dentro de write lock para atomicidad)
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

    # 3-7. Lock + copy + verify + delete + unlock — todo dentro de write_lock
    def _do_archive():
        # Acquire session lock con TTL corto para el archivado
        claim_result = acquire(context, ttl=60)
        if claim_result.exit_code != EXIT_OK:
            return claim_result

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ctx_name = os.path.basename(os.path.abspath(context))
            archive_dir = os.path.join(p["archive"], f"{timestamp}_{ctx_name}")

            # Copiar sesión a archive (excluyendo la propia carpeta archive si está dentro de p["base"])
            shutil.copytree(p["base"], archive_dir, ignore=shutil.ignore_patterns("archive"))

            # Verificar que el archive no esté vacío
            archive_contents = os.listdir(archive_dir)
            if not archive_contents:
                return CommandResult(
                    "FAIL|ARCHIVE_EMPTY",
                    EXIT_VALIDATION,
                )

            # Limpiar los archivos de la sesión activa en p["base"] (preservando p["archive"])
            for item in os.listdir(p["base"]):
                if item == "archive":
                    continue
                item_path = os.path.join(p["base"], item)
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)

            return CommandResult(
                f"SUCCESS|ARCHIVED|{archive_dir}",
                EXIT_OK,
            )
        finally:
            # Liberar session lock — los archivos de sesión ya fueron borrados,
            # pero el lockfile podría persistir
            lock_path = p["lock"]
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                except FileNotFoundError:
                    pass

    return with_write_lock(context, _do_archive)
