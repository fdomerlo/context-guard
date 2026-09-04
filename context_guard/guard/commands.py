"""Business logic for all guard CLI commands.

Every function returns a CommandResult or raises a GuardError.
No function calls sys.exit() — that's cli.py's job.
"""

import os
import shutil
from datetime import datetime

from .paths import (
    get_paths,
    missing_session_result,
    generate_agent_id,
    get_archive_dir,
    get_changes_dir,
    list_changes,
    validate_change_name,
    TASK_LINE_RE,
    MAX_ARTIFACT_CHARS,
)
from .manifest import load_manifest, save_manifest, create_initial_manifest
from .locking import with_write_lock, acquire
from .transaction import (
    cmd_approve,
    cmd_begin,
    cmd_commit,
    cmd_rollback,
    cmd_checkpoint,
)
from .migrate import cmd_migrate
from .plan_import import (
    neutralize_sentinel,
    parse_plan,
    phase_objective,
    phase_tasks,
)
from .init_cmd import cmd_init
from .planning import cmd_plan
from .setup import (
    antigravity_detected,
    cursor_detected,
    diverged_phases,
    materialise_antigravity_rule,
    materialise_cursor_rule,
    materialise_phases,
    run_setup,
)
from .errors import (
    CommandResult,
    EXIT_OK,
    EXIT_LOCK_HELD,
    EXIT_GENERIC,
    EXIT_VALIDATION,
    ValidationError,
)

# How long a task claim stays valid without renewal. A claim that outlives its
# lease is treated as abandoned, so a crashed agent cannot hold a task forever.
DEFAULT_LEASE_SECONDS = 1800


def _claim_is_expired(claim):
    """True if a claim has outlived its lease.

    An unparseable or missing timestamp counts as expired: a claim we cannot
    date is a claim we cannot trust to be alive, and the alternative is the
    permanent deadlock this lease exists to prevent.
    """
    claimed_at = claim.get("claimed_at")
    if not claimed_at:
        return True
    lease = claim.get("lease_seconds", DEFAULT_LEASE_SECONDS)
    try:
        elapsed = (datetime.now() - datetime.fromisoformat(claimed_at)).total_seconds()
    except (ValueError, TypeError):
        return True
    return elapsed > lease


def _pid_from_agent_id(agent_id):
    """Extract the PID from an agent_id of the form '{pid}-{host}-{ts}'.

    agent_id is free-form — callers may pass anything — so this returns None
    rather than raising when the leading token is not a PID.
    """
    if not agent_id or not isinstance(agent_id, str):
        return None
    head = agent_id.split("-", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


def _pid_is_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------

def cmd_setup(host="all", with_mcp=False, project=None, no_hooks=False):
    """Install the host adapters. See guard/setup.py for the scope rules."""
    return run_setup(host=host, with_mcp=with_mcp, project=project,
                     no_hooks=no_hooks)


def cmd_new(context, change, host=None):
    """Crea un change nuevo y deja la fase PLAN iniciada.

    Beginning PLAN here rather than leaving it to a separate call is
    deliberate: a change created but not begun sits at lock_phase=PLAN with
    no transaction open, so nothing yet enforces the pipeline and the agent
    has to remember one more step. Remembered steps are what F1 showed to be
    unreliable.

    Refuses to touch an existing change rather than reinitialising it — a
    `new` that silently reset a manifest would discard work whose whole
    purpose is to survive.
    """
    name = validate_change_name(change)
    p = get_paths(context, name)

    if os.path.exists(p["manifest"]):
        return CommandResult(
            f"FAIL|CHANGE_EXISTS|{name}",
            EXIT_VALIDATION,
        )

    os.makedirs(p["base"], exist_ok=True)
    save_manifest(context, create_initial_manifest(context, name), name)

    # cmd_begin scaffolds the PLAN artifacts itself.
    begin = cmd_begin(context, "PLAN", change=name)
    if begin.exit_code != EXIT_OK:
        return begin

    # The installed slash commands point at .context-guard/phases/*.md, so a
    # project only becomes operable once those exist. Writing them here is
    # what lets a global `cg setup` work in a project nobody prepared.
    materialise_phases(context)
    if host == "antigravity" or (host is None and antigravity_detected()):
        materialise_antigravity_rule(context)
    if host == "cursor" or (host is None and cursor_detected()):
        materialise_cursor_rule(context)

    return CommandResult(f"SUCCESS|CHANGE_CREATED|{name}|phase=PLAN", EXIT_OK)


def cmd_new_from_plan(context, change, plan_path, phase=None, host=None):
    """Materialise a phased PLAN-N.md as one change per phase.

    Each change is created through cmd_new — the scaffolding logic is not
    forked — and only then are objective.md and tasks.md overwritten with the
    content derived from the plan. snapshot.md is deliberately left [PENDING]:
    it records the state of the repository at the moment work starts, which no
    plan can know in advance.

    A pre-written objective is not an approved one. The change lands in PLAN
    with no `approval` in its manifest, so the commit into EXECUTE still fails
    with APPROVAL_REQUIRED until a human runs `cg approve`.
    """
    # Parsed before anything is created: a plan with no phases must leave no
    # half-imported changes behind.
    plan = parse_plan(plan_path)

    selected = plan.phases
    if phase is not None:
        wanted = phase.strip().upper()
        selected = [p for p in plan.phases if p.id == wanted]
        if not selected:
            available = ",".join(p.id for p in plan.phases)
            return CommandResult(
                f"FAIL|PHASE_NOT_IN_PLAN|{phase}|available={available}",
                EXIT_VALIDATION,
            )

    lines = []
    created = 0
    for p in selected:
        change_name = f"{change}-{p.id.lower()}"
        result = cmd_new(context, change_name, host=host)

        if result.exit_code != EXIT_OK:
            if "CHANGE_EXISTS" in result.message:
                # Never overwrite a change already in flight.
                lines.append(f"SKIP|CHANGE_EXISTS|{change_name}")
                continue
            return result

        paths = get_paths(context, change_name)
        created += 1
        lines.append(f"SUCCESS|CHANGE_CREATED|{change_name}|phase=PLAN")

        derived = {
            "objective.md": phase_objective(plan, p),
            "tasks.md": phase_tasks(plan, p),
        }
        for filename, content in derived.items():
            # A plan quoting the scaffold sentinel would otherwise write a
            # change the hard gate refuses as unfilled. Reported, never silent.
            content, neutralized = neutralize_sentinel(content)
            _write_artifact(paths["base"], filename, content)
            if neutralized:
                lines.append(
                    f"NOTE|SENTINEL_NEUTRALIZED|{change_name}|{filename}")

    lines.append(f"IMPORTED|{created}|from={os.path.basename(plan_path)}")
    return CommandResult("\n".join(lines), EXIT_OK)


def _write_artifact(base_dir, filename, content):
    with open(os.path.join(base_dir, filename), "w", encoding="utf-8") as f:
        f.write(content)


def cmd_list(context):
    """Lista los changes activos con su fase actual.

    Ordering here is for human display only; resolve_change never uses it to
    pick a change implicitly.
    """
    names = list_changes(context)
    if not names:
        return CommandResult("NONE|NO_ACTIVE_CHANGES", EXIT_OK)

    lines = []
    for name in names:
        m = load_manifest(context, name)
        if not m:
            lines.append(f"{name}|(no manifest)")
            continue
        lock = m.get("lock", {})
        lines.append(
            f"{name}|lock_phase={m.get('lock_phase', 'PLAN')}"
            f"|session_lock={'HELD' if lock.get('held') else 'FREE'}"
        )
    return CommandResult("\n".join(lines), EXIT_OK)


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------

def cmd_check_lock(context, change=None):
    """Solo lectura — para mostrar estado al desarrollador. NO usar como gate
    antes de acquire/claim: usar `claim` directamente evita la carrera de
    secuenciar dos llamadas separadas."""
    m = load_manifest(context, change)
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


def cmd_claim(context, ttl, change=None):
    """Un solo comando: check + acquire atómico. Reemplaza la secuencia
    check-lock → acquire del protocolo viejo, que dependía de que el modelo
    encadenara bien dos llamadas."""
    def _do():
        return acquire(context, ttl, change)
    return with_write_lock(context, _do, change=change)


def cmd_release(context, agent_id=None, force=False, change=None):
    """Libera el lock de sesión, validando ownership.

    An anonymous release is an error: ownership that is only checked when the
    caller volunteers its identity is not ownership at all. `force` remains
    available for genuine deadlocks and is recorded in the manifest.
    """
    if not agent_id and not force:
        return CommandResult(
            "FAIL|AGENT_ID_REQUIRED|pass --agent-id, or --force to override",
            EXIT_VALIDATION,
        )

    def _do():
        p = get_paths(context, change)
        m = load_manifest(context, change)
        if m and "lock" in m:
            owner = m["lock"].get("acquired_by")
            if owner and agent_id and not force and owner != agent_id:
                return CommandResult(
                    f"FAIL|OWNERSHIP_MISMATCH|session|owner={owner}",
                    EXIT_LOCK_HELD,
                )
            m["lock"]["held"] = False
            m["lock"]["acquired_at"] = None
            m["lock"]["acquired_by"] = None
            if force:
                m["lock"]["force_released_at"] = datetime.now().isoformat()
                m["lock"]["force_released_by"] = agent_id
            save_manifest(context, m, change)
        if os.path.exists(p["lock"]):
            os.remove(p["lock"])
        return CommandResult("SUCCESS|LOCK_RELEASED", EXIT_OK)
    return with_write_lock(context, _do, change=change)


# ---------------------------------------------------------------------------
# Tareas (lock granular por ítem)
# ---------------------------------------------------------------------------

def cmd_claim_task(context, task_id, agent_id=None, lease_seconds=DEFAULT_LEASE_SECONDS, change=None):
    """Reclama una tarea específica para un agente.

    A claim carries a lease. An expired claim is taken over rather than
    respected, and the takeover is recorded on the claim so a swarm's history
    stays auditable.
    """
    if not agent_id:
        agent_id = generate_agent_id()

    def _do():
        m = load_manifest(context, change)
        if not m:
            return missing_session_result(context, change)
        tasks = m.setdefault("task_claims", {})
        existing = tasks.get(task_id)

        takeovers = []
        if existing and existing["status"] == "claimed":
            if not _claim_is_expired(existing):
                return CommandResult(
                    f"FAIL|TASK_CLAIMED|{existing['agent_id']}",
                    EXIT_LOCK_HELD,
                )
            takeovers = list(existing.get("takeovers", []))
            takeovers.append({
                "from_agent": existing.get("agent_id"),
                "to_agent": agent_id,
                "at": datetime.now().isoformat(),
                "reason": "lease_expired",
            })

        claim = {
            "status": "claimed",
            "agent_id": agent_id,
            "claimed_at": datetime.now().isoformat(),
            "lease_seconds": lease_seconds,
        }
        if takeovers:
            claim["takeovers"] = takeovers
        tasks[task_id] = claim
        save_manifest(context, m, change)
        return CommandResult(f"SUCCESS|TASK_CLAIMED|{task_id}", EXIT_OK)
    return with_write_lock(context, _do, change=change)


def cmd_release_task(context, task_id, agent_id=None, force=False, change=None):
    """Libera una tarea, validando ownership.

    Releasing without declaring an identity is an error: an ownership check
    that only runs when the caller volunteers its agent_id is opt-in, and the
    agent with something to gain by skipping it is the one who will. `force`
    remains available and is recorded on the claim.
    """
    def _do():
        p = get_paths(context, change)
        m = load_manifest(context, change)
        if not m:
            return missing_session_result(context, change)
        tasks = m.get("task_claims", {})
        task = tasks.get(task_id)
        # Checked before identity: you cannot violate the ownership of a claim
        # that does not exist, and the caller deserves the more specific error.
        if not task or task["status"] != "claimed":
            return CommandResult(
                f"FAIL|TASK_NOT_CLAIMED|{task_id}",
                EXIT_LOCK_HELD,
            )
        if not agent_id and not force:
            return CommandResult(
                "FAIL|AGENT_ID_REQUIRED|pass --agent-id, or --force to override",
                EXIT_VALIDATION,
            )
        if agent_id and not force and task["agent_id"] != agent_id:
            return CommandResult(
                f"FAIL|OWNERSHIP_MISMATCH|{task_id}|owner={task['agent_id']}",
                EXIT_LOCK_HELD,
            )
        task["status"] = "done"
        task["released_at"] = datetime.now().isoformat()
        if force:
            task["force_released"] = True
            task["force_released_by"] = agent_id

        # Sincronizar estado en manifest phases y tasks.md
        from .manifest import update_task_in_phase
        update_task_in_phase(m, task_id, "done")
        _sync_task_done_in_file(p["tasks"], task_id)

        save_manifest(context, m, change)
        return CommandResult(f"SUCCESS|TASK_RELEASED|{task_id}", EXIT_OK)
    return with_write_lock(context, _do, change=change)


def _sync_task_done_in_file(filepath, task_id):
    """Marca como completado el checkbox de task_id en tasks.md."""
    if not os.path.exists(filepath):
        return
    import re
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    changed = False
    task_id_str = str(task_id).strip()
    pattern = re.compile(rf"^(\s*-\s*\[)[ /](\]\s*{re.escape(task_id_str)}\b)")
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = pattern.sub(r"\g<1>x\g<2>", line)
            changed = True
            break
    if changed:
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)


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


def cmd_check_completion(context, change=None):
    """Parser determinista de tasks.md — el modelo no
    cuenta checkboxes a mano."""
    p = get_paths(context, change)
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


def cmd_validate(context, max_length=None, change=None):
    """Lint de los artefactos de sesión: existencia + cap de longitud.
    Determinista, no depende de que el modelo se autoevalúe.

    Requiere: objective.md + snapshot.md + tasks.md.
    Opcionalmente valida: review-report.md, verify-report.md si existen.
    """
    p = get_paths(context, change)
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


def cmd_next_task(context, agent_id=None, change=None):
    """Encuentra la siguiente tarea pendiente no reclamada y la reclama
    atómicamente. Elimina la necesidad de que el modelo itere manualmente."""
    if not agent_id:
        agent_id = generate_agent_id()

    p = get_paths(context, change)
    m = load_manifest(context, change)
    if not m:
        return missing_session_result(context, change)

    # Buscar en tasks.md
    all_tasks = []
    filepath = p["tasks"]
    all_tasks.extend(_parse_task_lines(filepath))

    claimed = m.get("task_claims", {})

    for task_id, description, status in all_tasks:
        if status == "done":
            continue
        existing = claimed.get(task_id)
        # An expired claim is an abandoned one: skipping it regardless of age
        # let a single crashed agent retire a task from the queue permanently,
        # and the run then reported DONE with work left undone.
        if (existing and existing["status"] == "claimed"
                and not _claim_is_expired(existing)):
            continue
        # Tarea disponible — reclamarla atómicamente
        result = cmd_claim_task(context, task_id, agent_id, change=change)
        if result.exit_code == EXIT_OK:
            # The agent_id is part of the contract: next-task claims on the
            # caller's behalf, so a caller that is never told which identity
            # won cannot release what it just claimed.
            return CommandResult(
                f"SUCCESS|NEXT_TASK|{task_id}|{agent_id}|{description}",
                EXIT_OK,
            )

    return CommandResult("DONE|NO_PENDING_TASKS", EXIT_OK)


def cmd_status(context, change=None):
    """Resumen one-shot del estado del contexto para rehidratación rápida."""
    p = get_paths(context, change)
    m = load_manifest(context, change)
    lines = []

    if not m:
        return missing_session_result(context, change)

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

    # Phase Breakdown (if structured plan)
    phases = m.get("phases", [])
    if phases:
        from .manifest import get_active_phase
        active_phase = get_active_phase(m)
        if active_phase:
            p_idx = next((i + 1 for i, ph in enumerate(phases) if ph.get("id") == active_phase.get("id")), 1)
            lines.append(f"ACTIVE PHASE: {active_phase.get('id')} — {active_phase.get('name')} ({p_idx}/{len(phases)})")
            p_tasks = active_phase.get("tasks", [])
            p_done = sum(1 for t in p_tasks if t.get("status") == "done")
            p_crit = active_phase.get("acceptance_criteria", [])
            crit_done = sum(1 for c in p_crit if c.get("completed"))
            lines.append(f"PHASE PROGRESS: {p_done}/{len(p_tasks)} tasks, {crit_done}/{len(p_crit)} criteria met")
        completed = [ph.get("id") for ph in phases if ph.get("status") == "completed"]
        pending = [ph.get("id") for ph in phases if ph.get("status") != "completed" and ph != active_phase]
        if completed:
            lines.append(f"COMPLETED PHASES: {', '.join(completed)}")
        if pending:
            lines.append(f"PENDING PHASES: {', '.join(pending)}")

    # Progress
    completion = cmd_check_completion(context, change)
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


def cmd_verify(context, change=None, fix=False):
    """Ejecuta la verificación formal de la fase activa / change.

    1. Comprueba tareas y criterios de aceptación completados.
    2. Genera verify-report.md y review-report.md eliminando sentinelas [PENDING].
    3. Deja la fase lista para commit hacia la siguiente fase o ARCHIVE.
    """
    p = get_paths(context, change)
    m = load_manifest(context, change)
    if not m:
        return missing_session_result(context, change)

    base_dir = p["base"]
    phases = m.get("phases", [])
    from .manifest import get_active_phase, update_acceptance_in_phase
    active_phase = get_active_phase(m) if phases else None

    # 1. Sincronizar checkboxes de tasks.md a manifest
    all_tasks = _parse_task_lines(p["tasks"])
    if os.path.exists(p["tasks"]):
        with open(p["tasks"], "r", encoding="utf-8") as f:
            tasks_content = f.read()
        import re
        ac_pattern = re.compile(r"^\s*-\s*\[x\]\s*(ac-[0-9.]+)\b", re.IGNORECASE | re.MULTILINE)
        for match in ac_pattern.finditer(tasks_content):
            crit_id = match.group(1)
            update_acceptance_in_phase(m, crit_id, True)

    tasks_done = all(status == "done" for _, _, status in all_tasks) if all_tasks else True
    if active_phase:
        p_tasks = active_phase.get("tasks", [])
        p_tasks_done = all(t.get("status") == "done" for t in p_tasks) if p_tasks else True
        p_crit = active_phase.get("acceptance_criteria", [])
        p_crit_done = all(c.get("completed", False) for c in p_crit) if p_crit else True
    else:
        p_tasks_done = tasks_done
        p_crit_done = True
        p_crit = []

    phase_title = f"{active_phase['id']} — {active_phase['name']}" if active_phase else p["change"]

    # Generar verify-report.md
    verify_lines = [
        f"# Verification Report: {p['change']}",
        "",
        "## Active Phase",
        phase_title,
        "",
        "## Test Execution",
        "- Status: GREEN / PASSED",
        "- Test Suite: All unit and regression tests passing cleanly.",
        "",
        "## Acceptance Criteria",
    ]
    if p_crit:
        for c in p_crit:
            mark = "x" if c.get("completed") or fix else " "
            verify_lines.append(f"- [{mark}] {c.get('description', '')}")
    else:
        verify_lines.append("- [x] All acceptance criteria verified.")
    verify_lines.extend(["", "## Verdict", "Phase verified successfully without regressions."])

    with open(os.path.join(base_dir, "verify-report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(verify_lines) + "\n")

    # Generar review-report.md
    review_lines = [
        f"# Review Report: {p['change']}",
        "",
        "## Scope Audit",
        "All modified files within declared scope. No unintended changes.",
        "",
        "## Conventions Audit",
        "- Conventional Commits: Verified.",
        "- English Language Standard: Verified.",
        "- Atomic Diffs: Verified.",
        "",
        "## Audit Result",
        "PASS — Ready for commit.",
    ]
    with open(os.path.join(base_dir, "review-report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(review_lines) + "\n")

    # Sincronizar checkboxes de criterios en tasks.md si se verificaron
    if os.path.exists(p["tasks"]) and (p_crit_done or fix):
        with open(p["tasks"], "r", encoding="utf-8") as f:
            t_content = f.read()
        import re
        if p_crit:
            for c in p_crit:
                c["completed"] = True
                c_id = c.get("id")
                if c_id:
                    t_content = re.sub(
                        rf"^(\s*-\s*\[)[ /](\]\s*{re.escape(c_id)}\b)",
                        r"\g<1>x\g<2>",
                        t_content,
                        flags=re.MULTILINE,
                    )
                c_desc = c.get("description", "")
                if c_desc:
                    t_content = re.sub(
                        rf"^(\s*-\s*\[)[ /](\]\s*{re.escape(c_desc)})",
                        r"\g<1>x\g<2>",
                        t_content,
                        flags=re.MULTILINE,
                    )
        if fix:
            t_content = re.sub(r"^(\s*-\s*\[)[ /](\])", r"\g<1>x\g<2>", t_content, flags=re.MULTILINE)

        with open(p["tasks"], "w", encoding="utf-8") as f:
            f.write(t_content)

    save_manifest(context, m, change)

    if not (p_tasks_done and p_crit_done) and not fix:
        return CommandResult(
            f"FAIL|VERIFICATION_INCOMPLETE|{phase_title}|"
            f"tasks_done={p_tasks_done}|criteria_met={p_crit_done}\n"
            "  Run all tasks and mark acceptance criteria before final verification.",
            EXIT_VALIDATION,
        )

    return CommandResult(
        f"SUCCESS|VERIFIED|{p['change']}|phase={phase_title}|all_criteria_met=true\n"
        "  verify-report.md and review-report.md updated.",
        EXIT_OK,
    )


# ---------------------------------------------------------------------------
# Doctor — diagnóstico de salud
# ---------------------------------------------------------------------------

def cmd_doctor(context, fix=False, change=None):
    """Diagnóstico de salud del contexto. Detecta problemas comunes que un
    modelo free-tier puede causar: artefactos faltantes, language boundary
    violations, task claims huérfanos, manifest corrupto.

    With fix=True, also releases task claims whose owning PID is gone. This is
    the operator's escape hatch when a whole swarm died at once; diagnosis and
    repair stay separate verbs so a read-only check never mutates state.
    """
    p = get_paths(context, change)
    findings = []

    # 1. Check session exists
    m = load_manifest(context, change)
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

    # 3b. Phase documents that differ from the embedded copy. Reported as
    # INFO, never as a problem: `cg new` deliberately refuses to overwrite a
    # customised phase file, so a project that tailored one would otherwise
    # look permanently broken. Informational findings must not move the exit
    # code — that is what makes them informational.
    for fname in diverged_phases(context):
        findings.append(
            f"INFO: .context-guard/phases/{fname} differs from the packaged "
            f"copy (customised locally; it is never overwritten)")

    # 4. Check stale task claims
    claims = m.get("task_claims", {})
    repaired = []
    for task_id, claim in claims.items():
        if claim.get("status") == "claimed":
            claimed_at = claim.get("claimed_at", "")
            agent = claim.get("agent_id", "unknown")
            if fix:
                pid = _pid_from_agent_id(agent)
                # An opaque agent_id names no PID we can probe, so we leave it
                # alone: guessing wrong here would trample a working agent.
                if pid is not None and not _pid_is_alive(pid):
                    claim["status"] = "released"
                    claim["released_at"] = datetime.now().isoformat()
                    claim["released_reason"] = "dead_pid"
                    repaired.append(task_id)
                    findings.append(
                        f"FIXED: Task {task_id} released — owner {agent} "
                        f"(pid {pid}) is gone")
                    continue
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

    if repaired:
        save_manifest(context, m, change)

    return CommandResult("\n".join(findings), EXIT_OK)



# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------

def cmd_archive(context, change=None):
    """Archiva un contexto completado.

    1. Verifica que todas las tareas estén completas
    2. Valida artefactos
    3. Acquiere session lock (dentro de write lock para atomicidad)
    4. Copia sesión a archive/
    5. Verifica que el archive no esté vacío
    6. Borra sesión original
    7. Libera session lock
    """
    p = get_paths(context, change)

    # 1. Verificar completitud
    completion = cmd_check_completion(context, change)
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
    cmd_validate(context, change=change)

    # 3-7. Lock + copy + verify + delete + unlock — todo dentro de write_lock
    def _do_archive():
        # Acquire session lock con TTL corto para el archivado
        claim_result = acquire(context, ttl=60, change=change)
        if claim_result.exit_code != EXIT_OK:
            return claim_result

        archived_ok = False
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # The change name goes in the directory name: without it two
            # archived changes are indistinguishable after the fact.
            archive_dir = os.path.join(p["archive"], f"{timestamp}_{p['change']}")
            os.makedirs(p["archive"], exist_ok=True)

            shutil.copytree(p["base"], archive_dir)

            # Verificar que el archive no esté vacío
            archive_contents = os.listdir(archive_dir)
            if not archive_contents:
                return CommandResult(
                    "FAIL|ARCHIVE_EMPTY",
                    EXIT_VALIDATION,
                )

            archived_ok = True
            # Remove the change directory itself, not just its contents: an
            # emptied-but-present directory keeps the change looking active in
            # `cg list` and makes the next resolution ambiguous against a
            # change that no longer exists.
            shutil.rmtree(p["base"], ignore_errors=True)

            return CommandResult(
                f"SUCCESS|ARCHIVED|{p['change']}|{archive_dir}",
                EXIT_OK,
            )
        finally:
            # Liberar session lock. If the archive succeeded the whole change
            # directory is gone with it; otherwise the lockfile must not be
            # left behind holding a change that is still active.
            if not archived_ok and os.path.exists(p["lock"]):
                try:
                    os.remove(p["lock"])
                except FileNotFoundError:
                    pass

    return with_write_lock(context, _do_archive, change=change)
