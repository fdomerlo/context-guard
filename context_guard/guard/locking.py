"""Locking primitives for guard middleware.

Two independent lock levels:
  - Session lock: OS-level lockfile (.lock) for cold-boot and archival
  - Write lock: short-lived mutex (.write.lock) for serializing read-modify-write
"""

import os
import time
from datetime import datetime

from .paths import get_paths, generate_agent_id
from .manifest import load_manifest, save_manifest, create_initial_manifest
from .errors import (
    CommandResult,
    EXIT_OK,
    EXIT_LOCK_HELD,
    EXIT_LOCK_CONTENDED,
    LockContendedError,
)


# ---------------------------------------------------------------------------
# Write lock — mutex de milisegundos para serializar read-modify-write
# ---------------------------------------------------------------------------

WRITE_LOCK_MAX_AGE = 30  # seconds before a write lock is considered stale


def _is_write_lock_stale(lockfile):
    """Detecta si un .write.lock es huérfano (proceso muerto o demasiado viejo).

    Returns:
        True si el lock es stale y puede ser removido de forma segura.
    """
    try:
        with open(lockfile, "r") as f:
            lines = f.readlines()
        if len(lines) >= 1:
            pid = int(lines[0].strip())
            try:
                os.kill(pid, 0)
            except OSError:
                return True  # proceso muerto, lock huérfano
        if len(lines) >= 2:
            created = float(lines[1].strip())
            if time.time() - created > WRITE_LOCK_MAX_AGE:
                return True  # demasiado viejo
    except (ValueError, IOError):
        return True  # no se puede leer, asumir stale
    return False


def with_write_lock(context, fn, timeout=5, retry_interval=0.05):
    """Mutex de milisegundos para serializar read-modify-write.

    Independiente del lock de negocio (que dura toda la sesión).
    Escribe PID + timestamp en el lockfile para stale-detection.
    """
    p = get_paths(context)
    lockfile = p["write_lock"]
    os.makedirs(os.path.dirname(lockfile), exist_ok=True)
    start = time.time()
    while True:
        try:
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()}\n{time.time()}\n".encode())
            os.close(fd)
            break
        except FileExistsError:
            if _is_write_lock_stale(lockfile):
                try:
                    os.remove(lockfile)
                    continue
                except FileNotFoundError:
                    continue
            if time.time() - start > timeout:
                raise TimeoutError("write lock contention")
            time.sleep(retry_interval)
    try:
        return fn()
    finally:
        try:
            os.remove(lockfile)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Session lock — lockfile a nivel de SO
# ---------------------------------------------------------------------------

def try_create_lockfile(context):
    """Atomic test-and-set at the OS level. Returns True if acquired."""
    p = get_paths(context)
    os.makedirs(os.path.dirname(p["lock"]), exist_ok=True)
    try:
        fd = os.open(p["lock"], os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def acquire(context, ttl):
    """Lógica compartida de claim/acquire: intenta tomar el lock, hace
    stale-takeover si corresponde.

    Returns:
        CommandResult con message y exit_code.
    """
    p = get_paths(context)
    os.makedirs(p["base"], exist_ok=True)
    m = load_manifest(context)
    if not m:
        m = create_initial_manifest(context)


    if not try_create_lockfile(context):
        existing = m.get("lock", {})
        acquired_at = existing.get("acquired_at")
        ttl_existing = existing.get("ttl_seconds", ttl)
        stale = False
        if acquired_at:
            elapsed = (datetime.now() - datetime.fromisoformat(acquired_at)).total_seconds()
            stale = elapsed > ttl_existing
        else:
            # Orphan lockfile: a peer died between creating .lock and recording
            # its metadata. Without a fallback the staleness check silently
            # evaluates to False and the session deadlocks forever, so age the
            # lock by the file's own mtime instead.
            try:
                elapsed = time.time() - os.path.getmtime(p["lock"])
                stale = elapsed > ttl_existing
            except OSError:
                # Lockfile vanished between the failed create and this stat —
                # another agent released it; fall through and retry the create.
                stale = True

        if not stale:
            return CommandResult(
                f"FAIL|LOCK_HELD|{existing.get('acquired_by')}",
                EXIT_LOCK_HELD,
            )

        try:
            os.remove(p["lock"])
        except FileNotFoundError:
            # Another agent released or took over the lock first; the create
            # below is what decides who actually wins.
            pass
        if not try_create_lockfile(context):
            return CommandResult("FAIL|LOCK_CONTENDED", EXIT_LOCK_CONTENDED)

    m["lock"] = {
        "held": True,
        "acquired_at": datetime.now().isoformat(),
        "acquired_by": generate_agent_id(),
        "ttl_seconds": ttl,
    }
    save_manifest(context, m)
    return CommandResult("SUCCESS|LOCK_ACQUIRED", EXIT_OK)
