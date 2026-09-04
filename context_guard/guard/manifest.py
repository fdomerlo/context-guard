"""Manifest I/O with atomic writes for guard middleware."""

import json
import os

from .paths import get_paths
from .errors import ManifestCorruptError


DEFAULT_PIPELINE = ["PLAN", "EXECUTE", "VERIFY"]

# Bumped for the multi-change layout: manifests now live per change under
# .context-guard/changes/{name}/ and carry the change name.
SCHEMA_VERSION = 3


def create_initial_manifest(context, change=None, requirement=None, objective=None, phases=None):
    """Crea una estructura de manifest inicial con el pipeline de 3 estados y soporte de fases."""
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "context_name": context,
        "change_name": change,
        "current_phase": "PLAN",
        "lock_phase": "PLAN",
        "completed_phases": [],
        "pending_phases": list(DEFAULT_PIPELINE),
        "lock": {},
        "transaction": {
            "txn_status": "idle",
            "txn_phase": "None",
            "txn_started_at": None,
        },
        "reference_docs": [],
        "files_in_scope": [],
        "task_claims": {},
        "phases": phases or [],
        "active_phase_id": phases[0]["id"] if phases and len(phases) > 0 else None,
    }
    if requirement:
        manifest["requirement"] = requirement
    if objective:
        manifest["objective"] = objective
    return manifest


def load_manifest(context, change=None):
    """Carga el manifest del change dado.

    Returns:
        dict or None: El manifest parseado, o None si no existe.

    Raises:
        ManifestCorruptError: Si el archivo existe pero no es JSON válido.
    """
    p = get_paths(context, change)
    if not os.path.exists(p["manifest"]):
        return None
    try:
        with open(p["manifest"], "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError) as e:
        raise ManifestCorruptError(str(e))


def save_manifest(context, data, change=None):
    """Escribe el manifest con write atómico (tmp + rename).

    Crea los directorios necesarios si no existen.
    """
    p = get_paths(context, change)
    os.makedirs(os.path.dirname(p["manifest"]), exist_ok=True)
    tmp_path = p["manifest"] + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.rename(tmp_path, p["manifest"])


# ---------------------------------------------------------------------------
# Phase management helpers
# ---------------------------------------------------------------------------

def get_phases(manifest):
    """Retorna la lista de fases definidas en el manifest."""
    return manifest.get("phases", [])


def get_phase(manifest, phase_id):
    """Obtiene una fase por su ID (e.g. 'F1')."""
    if not phase_id:
        return None
    phase_id_norm = phase_id.strip().upper()
    for phase in get_phases(manifest):
        if phase.get("id", "").strip().upper() == phase_id_norm:
            return phase
    return None


def get_active_phase(manifest):
    """Retorna la fase actualmente activa según active_phase_id o la primera pendiente."""
    phases = get_phases(manifest)
    if not phases:
        return None
    active_id = manifest.get("active_phase_id")
    if active_id:
        phase = get_phase(manifest, active_id)
        if phase:
            return phase
    for phase in phases:
        if phase.get("status") != "completed":
            return phase
    return phases[-1]


def set_active_phase(manifest, phase_id):
    """Establece la fase activa por su ID."""
    phase = get_phase(manifest, phase_id)
    if not phase:
        raise ValueError(f"Phase not found in manifest: {phase_id}")
    manifest["active_phase_id"] = phase["id"]


def add_phase(manifest, phase_dict):
    """Agrega una fase estructurada al manifest."""
    phases = manifest.setdefault("phases", [])
    phase_id = phase_dict.get("id")
    if not phase_id:
        phase_id = f"F{len(phases) + 1}"
    
    normalized_phase = {
        "id": phase_id.strip().upper(),
        "name": phase_dict.get("name", f"Phase {phase_id}"),
        "status": phase_dict.get("status", "pending"),
        "spec": phase_dict.get("spec", ""),
        "dependencies": phase_dict.get("dependencies", []),
        "tasks": phase_dict.get("tasks", []),
        "acceptance_criteria": phase_dict.get("acceptance_criteria", []),
        "verification": phase_dict.get("verification", {
            "command": phase_dict.get("tests", ""),
            "status": "pending",
        }),
    }
    phases.append(normalized_phase)
    if not manifest.get("active_phase_id"):
        manifest["active_phase_id"] = normalized_phase["id"]
    return normalized_phase


def update_phase_status(manifest, phase_id, status):
    """Actualiza el estado de una fase ('pending', 'in_progress', 'completed', 'skipped')."""
    phase = get_phase(manifest, phase_id)
    if not phase:
        raise ValueError(f"Phase not found: {phase_id}")
    phase["status"] = status
    if status == "completed":
        # Avanzar active_phase_id a la siguiente pendiente si corresponde
        for p in get_phases(manifest):
            if p.get("status") != "completed":
                manifest["active_phase_id"] = p["id"]
                break


def get_phase_tasks(manifest, phase_id=None):
    """Retorna las tareas de una fase dada o de la fase activa."""
    phase = get_phase(manifest, phase_id) if phase_id else get_active_phase(manifest)
    if not phase:
        return []
    return phase.get("tasks", [])


def update_task_in_phase(manifest, task_id, status, phase_id=None, agent_id=None):
    """Actualiza el estado de una tarea dentro de una fase."""
    phase = get_phase(manifest, phase_id) if phase_id else get_active_phase(manifest)
    if not phase:
        return False
    for task in phase.get("tasks", []):
        if str(task.get("id")) == str(task_id):
            task["status"] = status
            if agent_id:
                task["claimed_by"] = agent_id
            return True
    return False


def update_acceptance_in_phase(manifest, criterion_id, completed=True, phase_id=None):
    """Actualiza un criterio de aceptación en una fase."""
    phase = get_phase(manifest, phase_id) if phase_id else get_active_phase(manifest)
    if not phase:
        return False
    for crit in phase.get("acceptance_criteria", []):
        if str(crit.get("id")) == str(criterion_id):
            crit["completed"] = bool(completed)
            return True
    return False


def is_phase_complete(manifest, phase_id):
    """Verifica si todas las tareas y criterios de una fase están completos."""
    phase = get_phase(manifest, phase_id)
    if not phase:
        return False
    tasks = phase.get("tasks", [])
    if any(t.get("status") != "done" for t in tasks):
        return False
    criteria = phase.get("acceptance_criteria", [])
    if any(not c.get("completed", False) for c in criteria):
        return False
    return True


def all_phases_complete(manifest):
    """Verifica si todas las fases del manifest están completadas."""
    phases = get_phases(manifest)
    if not phases:
        return True
    return all(p.get("status") == "completed" for p in phases)

