"""Transaction and checkpoint manager for guard middleware.

Provides state snapshot, rollback, begin, commit, and checkpointing for context-guard sessions.
Follows the 3-state pipeline model: PLAN -> EXECUTE -> VERIFY -> ARCHIVE.
"""

from datetime import datetime
import os

from .paths import get_paths
from .manifest import load_manifest, save_manifest, create_initial_manifest
from .locking import with_write_lock
from .errors import (
    CommandResult,
    EXIT_OK,
    EXIT_LOCK_HELD,
    EXIT_GENERIC,
    EXIT_VALIDATION,
    EXIT_BAD_TRANSITION,
)

DEFAULT_TTL = 1800
MAX_SUMMARY_CHARS = 2000

VALID_PHASES = ["PLAN", "EXECUTE", "VERIFY"]

TRANSITIONS = {
    "PLAN": "EXECUTE",
    "EXECUTE": "VERIFY",
    "VERIFY": "ARCHIVE",
}


def is_stale(started_at_iso, ttl_seconds):
    """Verifica si una transacción ha superado su TTL."""
    if not started_at_iso or started_at_iso == "None":
        return False
    try:
        elapsed = (datetime.now() - datetime.fromisoformat(started_at_iso)).total_seconds()
        return elapsed > ttl_seconds
    except (ValueError, TypeError):
        return False


def _scaffold_artifacts(context_path):
    """Genera plantillas por defecto en .context-guard/ para la fase PLAN si no existen."""
    p = get_paths(context_path)
    base_dir = p["base"]
    os.makedirs(base_dir, exist_ok=True)

    artifacts = {
        "objective.md": "[PENDING] Define objective here",
        "snapshot.md": "[PENDING] Define snapshot here",
        "tasks.md": "[PENDING] Define tasks here",
        "review-report.md": "[PENDING] Write static review here",
        "verify-report.md": "[PENDING] Write dynamic verification here",
    }

    for filename, default_content in artifacts.items():
        filepath = os.path.join(base_dir, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(default_content)


def cmd_begin(context, phase, ttl=DEFAULT_TTL):
    """Inicia una transacción para la fase dada (PLAN, EXECUTE, VERIFY)."""
    if phase not in VALID_PHASES:
        return CommandResult(f"FAIL|INVALID_PHASE|{phase}", EXIT_VALIDATION)

    def _do():
        p = get_paths(context)
        m = load_manifest(context)
        if not m:
            m = create_initial_manifest(context)

        # DAG enforcement: the manifest decides which phase may start, not the
        # caller. Without this, the pipeline was only checked on commit — and
        # an agent that never commits was never stopped.
        lock_phase = m.get("lock_phase", "PLAN")
        if phase != lock_phase:
            return CommandResult(
                f"FAIL|PHASE_NOT_AUTHORIZED|requested={phase}|lock_phase={lock_phase}",
                EXIT_BAD_TRANSITION,
            )

        txn = m.setdefault("transaction", {})
        status = txn.get("txn_status", "idle")
        started_at = txn.get("txn_started_at", None)

        if status == "in_progress" and not is_stale(started_at, ttl):
            return CommandResult(
                f"FAIL|TXN_IN_PROGRESS|{txn.get('txn_phase')}",
                EXIT_LOCK_HELD,
            )

        if phase == "PLAN":
            _scaffold_artifacts(context)

        # Snapshot de estado previo para rollback
        snapshot = {
            "current_phase": m.get("current_phase", "PLAN"),
            "lock_phase": m.get("lock_phase", "PLAN"),
            "completed_phases": list(m.get("completed_phases", [])),
            "pending_phases": list(m.get("pending_phases", list(VALID_PHASES))),
            "session_summary": m.get("session", {}).get("session_summary", ""),
        }

        txn["txn_status"] = "in_progress"
        txn["txn_phase"] = phase
        txn["txn_started_at"] = datetime.now().isoformat()
        txn["snapshot"] = snapshot

        m["transaction"] = txn
        save_manifest(context, m)
        return CommandResult(f"SUCCESS|BEGIN|phase={phase}", EXIT_OK)

    return with_write_lock(context, _do)


def cmd_commit(context, next_phase):
    """Finaliza exitosamente la transacción y avanza en el DAG de 3 estados."""
    def _do():
        m = load_manifest(context)
        if not m:
            return CommandResult("FAIL|NO_SESSION", EXIT_GENERIC)

        txn = m.get("transaction", {})
        if txn.get("txn_status", "idle") != "in_progress":
            return CommandResult("FAIL|NO_TXN_IN_PROGRESS", EXIT_GENERIC)

        phase = txn.get("txn_phase")
        expected_next = TRANSITIONS.get(phase)
        if expected_next != next_phase:
            return CommandResult(
                f"FAIL|BAD_TRANSITION|from={phase}|to={next_phase}|expected={expected_next}",
                EXIT_BAD_TRANSITION,
            )

        # Validaciones estrictas (Hard Gates) antes de autorizar el cambio de fase
        p = get_paths(context)
        base_dir = p["base"]

        if phase == "PLAN" and next_phase == "EXECUTE":
            required_files = ["objective.md", "tasks.md"]
            for fname in required_files:
                fpath = os.path.join(base_dir, fname)
                if not os.path.exists(fpath):
                    return CommandResult(
                        "FAIL|VALIDATION|Debe completar objective.md y tasks.md antes de avanzar a EXECUTE",
                        EXIT_VALIDATION,
                    )
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                if "[PENDING]" in content:
                    return CommandResult(
                        "FAIL|VALIDATION|Debe completar objective.md y tasks.md antes de avanzar a EXECUTE",
                        EXIT_VALIDATION,
                    )

        elif phase == "VERIFY" and next_phase == "ARCHIVE":
            required_files = ["review-report.md", "verify-report.md"]
            for fname in required_files:
                fpath = os.path.join(base_dir, fname)
                if not os.path.exists(fpath):
                    return CommandResult(
                        "FAIL|VALIDATION|Debe completar la auditoría en review-report.md y verify-report.md antes de archivar",
                        EXIT_VALIDATION,
                    )
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                if "[PENDING]" in content:
                    return CommandResult(
                        "FAIL|VALIDATION|Debe completar la auditoría en review-report.md y verify-report.md antes de archivar",
                        EXIT_VALIDATION,
                    )

        # Actualizar grafo de fases
        m["current_phase"] = phase
        m["lock_phase"] = next_phase

        completed = m.get("completed_phases", [])
        if phase not in completed:
            completed.append(phase)
        m["completed_phases"] = completed

        pending = m.get("pending_phases", [])
        if phase in pending:
            pending.remove(phase)
        m["pending_phases"] = pending

        txn["txn_status"] = "idle"
        txn["txn_phase"] = "None"
        txn["txn_started_at"] = None
        txn.pop("snapshot", None)

        # Generar auto_summary determinístico
        auto_summary = (
            f"completed_phase={phase}\n"
            f"next_phase={next_phase}\n"
            f"completed={', '.join(completed)}\n"
            f"pending={', '.join(pending)}"
        )
        session_sec = m.setdefault("session", {})
        session_sec["session_summary"] = auto_summary

        save_manifest(context, m)
        return CommandResult(f"SUCCESS|COMMIT|lock_phase={next_phase}", EXIT_OK)

    return with_write_lock(context, _do)


def cmd_rollback(context):
    """Revierte la transacción actual restaurando el snapshot previo."""
    def _do():
        m = load_manifest(context)
        if not m:
            return CommandResult("FAIL|NO_SESSION", EXIT_GENERIC)

        txn = m.get("transaction", {})
        if txn.get("txn_status", "idle") != "in_progress":
            return CommandResult("FAIL|NO_TXN_IN_PROGRESS", EXIT_GENERIC)

        snapshot = txn.get("snapshot")
        if snapshot:
            m["current_phase"] = snapshot.get("current_phase", "PLAN")
            m["lock_phase"] = snapshot.get("lock_phase", "PLAN")
            m["completed_phases"] = snapshot.get("completed_phases", [])
            m["pending_phases"] = snapshot.get("pending_phases", list(VALID_PHASES))
            if "session_summary" in snapshot:
                session_sec = m.setdefault("session", {})
                session_sec["session_summary"] = snapshot["session_summary"]

        txn["txn_status"] = "idle"
        txn["txn_phase"] = "None"
        txn["txn_started_at"] = None
        txn.pop("snapshot", None)

        save_manifest(context, m)
        return CommandResult("SUCCESS|ROLLBACK|restored", EXIT_OK)

    return with_write_lock(context, _do)


def cmd_checkpoint(context, summary):
    """Guarda un checkpoint con el resumen de la sesión en manifest.json."""
    if len(summary) > MAX_SUMMARY_CHARS:
        return CommandResult(
            f"FAIL|SUMMARY_TOO_LONG|{len(summary)}/{MAX_SUMMARY_CHARS}",
            EXIT_VALIDATION,
        )

    def _do():
        m = load_manifest(context)
        if not m:
            return CommandResult("FAIL|NO_SESSION", EXIT_GENERIC)

        session_sec = m.setdefault("session", {})
        session_sec["session_summary"] = summary
        save_manifest(context, m)
        return CommandResult("SUCCESS|CHECKPOINT_SAVED", EXIT_OK)

    return with_write_lock(context, _do)
