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
    EXIT_APPROVAL_REQUIRED,
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


def _scaffold_artifacts(context_path, change=None):
    """Genera plantillas por defecto en .context-guard/ para la fase PLAN si no existen."""
    p = get_paths(context_path, change)
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


def _record_approval(m, approval, consumed_as):
    """Move an approval into the audit trail, spending it.

    An approval left live in the manifest authorizes every future transition
    into EXECUTE, not just the one the human looked at. Consuming it here is
    what makes a sign-off single-use.
    """
    entry = dict(approval)
    entry["consumed_at"] = datetime.now().isoformat()
    entry["consumed_as"] = consumed_as
    m.setdefault("approval_history", []).append(entry)
    m.pop("approval", None)


def cmd_approve(context, by=None, hotfix=False, reason=None, change=None):
    """Records the human sign-off that PLAN -> EXECUTE requires.

    This command is cooperative and makes no pretence otherwise: an agent with
    a shell can run it. What it buys is that the transition cannot happen
    without *someone* running it, and that whoever did is named in the
    manifest. The hard control is the harness permission prompt documented in
    adapters/ — see PLAN.md 0.6.

    `hotfix` is the audited door out of the pipeline: it spends the approval
    immediately and jumps lock_phase straight to EXECUTE, recording why. It
    replaces state-guard's parallel bypass flow, whose problem was never that
    it existed but that nothing survived it.
    """
    if hotfix and not (reason or "").strip():
        return CommandResult(
            'FAIL|HOTFIX_REASON_REQUIRED|pass --reason "<text>"',
            EXIT_VALIDATION,
        )

    # Required, not defaulted to $USER: falling back to the environment made
    # an agent-run `cg approve` indistinguishable from a human-run one
    # whenever the shell happened to report a plausible name. This does not
    # authenticate anyone — an agent can still pass any string — but it
    # forces an active choice instead of silently inheriting one, so the
    # omission is visible in the manifest rather than papered over.
    who = (by or "").strip()
    if not who:
        return CommandResult(
            "FAIL|BY_REQUIRED|pass --by <who>",
            EXIT_VALIDATION,
        )

    # Checked before taking the write lock: acquiring it would create the
    # change directory as a side effect, inventing the change the caller
    # mistyped.
    if load_manifest(context, change) is None:
        return CommandResult("FAIL|NO_SESSION", EXIT_GENERIC)

    def _do():
        m = load_manifest(context, change)
        if not m:
            return CommandResult("FAIL|NO_SESSION", EXIT_GENERIC)

        lock_phase = m.get("lock_phase", "PLAN")
        if lock_phase != "PLAN":
            # Only PLAN -> EXECUTE consumes an approval. Recording one anywhere
            # else leaves a live sign-off that nothing will spend, waiting to
            # authorize a transition nobody was asked about.
            return CommandResult(
                f"FAIL|APPROVAL_NOT_APPLICABLE|lock_phase={lock_phase}",
                EXIT_BAD_TRANSITION,
            )

        approval = {"by": who, "at": datetime.now().isoformat()}

        if not hotfix:
            m["approval"] = approval
            save_manifest(context, m, change)
            return CommandResult(
                f"SUCCESS|APPROVED|{get_paths(context, change)['change']}|by={who}",
                EXIT_OK,
            )

        txn = m.get("transaction", {})
        if txn.get("txn_status", "idle") == "in_progress":
            # The open transaction holds a snapshot taken at lock_phase=PLAN.
            # Jumping the pipeline behind its back means a later rollback
            # restores a state the change already left, silently undoing the
            # hotfix.
            return CommandResult(
                f"FAIL|TXN_IN_PROGRESS|{txn.get('txn_phase')}",
                EXIT_LOCK_HELD,
            )

        approval["hotfix"] = True
        approval["reason"] = reason.strip()
        _record_approval(m, approval, "PLAN->EXECUTE (hotfix)")

        m["lock_phase"] = "EXECUTE"
        # PLAN was skipped, not done. Writing it into completed_phases would
        # make the manifest claim a plan was produced and reviewed; leaving it
        # pending would make the pipeline ask for it again.
        pending = m.get("pending_phases", [])
        if "PLAN" in pending:
            pending.remove("PLAN")
        m["pending_phases"] = pending
        skipped = m.setdefault("skipped_phases", [])
        if "PLAN" not in skipped:
            skipped.append("PLAN")

        save_manifest(context, m, change)
        return CommandResult(
            f"SUCCESS|APPROVED_HOTFIX|{get_paths(context, change)['change']}"
            f"|by={who}|lock_phase=EXECUTE",
            EXIT_OK,
        )

    return with_write_lock(context, _do, change=change)


def cmd_begin(context, phase, ttl=DEFAULT_TTL, change=None):
    """Inicia una transacción para la fase dada (PLAN, EXECUTE, VERIFY)."""
    if phase not in VALID_PHASES:
        return CommandResult(f"FAIL|INVALID_PHASE|{phase}", EXIT_VALIDATION)

    def _do():
        p = get_paths(context, change)
        m = load_manifest(context, change)
        if not m:
            m = create_initial_manifest(context, p["change"])

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
            _scaffold_artifacts(context, change)

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
        save_manifest(context, m, change)
        return CommandResult(f"SUCCESS|BEGIN|phase={phase}", EXIT_OK)

    return with_write_lock(context, _do, change=change)


def cmd_commit(context, next_phase, change=None):
    """Finaliza exitosamente la transacción y avanza en el DAG de 3 estados."""
    def _do():
        m = load_manifest(context, change)
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
        p = get_paths(context, change)
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

            # Checked after the artifacts, deliberately: an approval must not
            # buy a pass through validation, and a human who signed off on a
            # still-[PENDING] plan should be told the plan is empty, not that
            # their approval is missing.
            if not m.get("approval"):
                return CommandResult(
                    "FAIL|APPROVAL_REQUIRED|run `cg approve` before entering EXECUTE",
                    EXIT_APPROVAL_REQUIRED,
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

        # The approval is spent by the transition it authorized, so the next
        # iteration of the plan needs a new one.
        if phase == "PLAN" and next_phase == "EXECUTE" and m.get("approval"):
            _record_approval(m, m["approval"], "PLAN->EXECUTE")

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

        save_manifest(context, m, change)
        return CommandResult(f"SUCCESS|COMMIT|lock_phase={next_phase}", EXIT_OK)

    return with_write_lock(context, _do, change=change)


def cmd_rollback(context, change=None):
    """Revierte la transacción actual restaurando el snapshot previo."""
    def _do():
        m = load_manifest(context, change)
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

        save_manifest(context, m, change)
        return CommandResult("SUCCESS|ROLLBACK|restored", EXIT_OK)

    return with_write_lock(context, _do, change=change)


def cmd_checkpoint(context, summary, change=None):
    """Guarda un checkpoint con el resumen de la sesión en manifest.json."""
    if len(summary) > MAX_SUMMARY_CHARS:
        return CommandResult(
            f"FAIL|SUMMARY_TOO_LONG|{len(summary)}/{MAX_SUMMARY_CHARS}",
            EXIT_VALIDATION,
        )

    def _do():
        m = load_manifest(context, change)
        if not m:
            return CommandResult("FAIL|NO_SESSION", EXIT_GENERIC)

        session_sec = m.setdefault("session", {})
        session_sec["session_summary"] = summary
        save_manifest(context, m, change)
        return CommandResult("SUCCESS|CHECKPOINT_SAVED", EXIT_OK)

    return with_write_lock(context, _do, change=change)
