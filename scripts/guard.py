#!/usr/bin/env python3
import argparse
import json
import os
import re
import time
import socket
import sys
from datetime import datetime

MAX_ARTIFACT_CHARS = 2000  # ~500 tokens, mismo criterio que Agentify SDD

EXIT_OK = 0
EXIT_LOCK_HELD = 1         # otra sesión activa, no reintentar automáticamente
EXIT_LOCK_CONTENDED = 2    # perdiste la carrera contra otro takeover de lock stale
EXIT_VALIDATION = 3        # artefacto mal formado o excede el cap de tokens
EXIT_GENERIC = 4           # manifest corrupto u otro error irrecuperable

TASK_LINE_RE = re.compile(r"^\s*-\s*\[( |x|X)\]\s*(.*)$")


# ---------------------------------------------------------------------------
# Rutas — relativas a cwd, namespaced por contexto
# ---------------------------------------------------------------------------

def _paths(context):
    """Todas las rutas de sesión, relativas a cwd, namespaced por contexto."""
    base = os.path.join(".context-guard", "sessions", context)
    return {
        "base": base,
        "manifest": os.path.join(base, "manifest.json"),
        "blockers": os.path.join(base, "blockers_todo.md"),
        "lock": os.path.join(base, ".lock"),
        "write_lock": os.path.join(base, ".write.lock"),
        "archive": os.path.join(".context-guard", "archive"),
    }


def _generate_agent_id():
    """Identidad consistente para locks de sesión y de tarea."""
    return f"{os.getpid()}-{socket.gethostname()}-{int(time.time())}"


# ---------------------------------------------------------------------------
# Manifest I/O — siempre requiere contexto
# ---------------------------------------------------------------------------

def load_manifest(context):
    """Carga el manifest del contexto dado. Devuelve None si no existe.
    Sale con EXIT_GENERIC si el JSON está corrupto."""
    p = _paths(context)
    if not os.path.exists(p["manifest"]):
        return None
    try:
        with open(p["manifest"], "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"FAIL|CORRUPT_MANIFEST|{e}")
        sys.exit(EXIT_GENERIC)


def save_manifest(context, data):
    """Escribe el manifest con write atómico (tmp + rename)."""
    p = _paths(context)
    os.makedirs(os.path.dirname(p["manifest"]), exist_ok=True)
    tmp_path = p["manifest"] + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.rename(tmp_path, p["manifest"])


# ---------------------------------------------------------------------------
# Write lock — mutex de milisegundos para serializar read-modify-write
# ---------------------------------------------------------------------------

def with_write_lock(context, fn, timeout=5, retry_interval=0.05):
    """Mutex de milisegundos para serializar read-modify-write.
    Independiente del lock de negocio (que dura toda la sesión)."""
    p = _paths(context)
    lockfile = p["write_lock"]
    os.makedirs(os.path.dirname(lockfile), exist_ok=True)
    start = time.time()
    while True:
        try:
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
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
# Lock de sesión — lockfile a nivel de SO
# ---------------------------------------------------------------------------

def _try_create_lockfile(context):
    """Atomic test-and-set at the OS level. Returns True if acquired."""
    p = _paths(context)
    os.makedirs(os.path.dirname(p["lock"]), exist_ok=True)
    try:
        fd = os.open(p["lock"], os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _acquire(context, ttl):
    """Lógica compartida de claim/acquire: intenta tomar el lock, hace
    stale-takeover si corresponde. Devuelve (ok: bool, msg: str)."""
    p = _paths(context)
    os.makedirs(p["base"], exist_ok=True)
    m = load_manifest(context)
    if not m:
        m = {
            "context_name": context,
            "lock": {},
            "reference_docs": [],
            "files_in_scope": [],
        }

    if not _try_create_lockfile(context):
        existing = m.get("lock", {})
        acquired_at = existing.get("acquired_at")
        ttl_existing = existing.get("ttl_seconds", ttl)
        stale = False
        if acquired_at:
            elapsed = (datetime.now() - datetime.fromisoformat(acquired_at)).total_seconds()
            stale = elapsed > ttl_existing

        if not stale:
            return False, f"FAIL|LOCK_HELD|{existing.get('acquired_by')}"

        os.remove(p["lock"])
        if not _try_create_lockfile(context):
            return None, "FAIL|LOCK_CONTENDED"  # None = otro caso de exit code

    m["lock"] = {
        "held": True,
        "acquired_at": datetime.now().isoformat(),
        "acquired_by": _generate_agent_id(),
        "ttl_seconds": ttl,
    }
    save_manifest(context, m)
    return True, "SUCCESS|LOCK_ACQUIRED"


# ---------------------------------------------------------------------------
# Comandos CLI — sesión
# ---------------------------------------------------------------------------

def cmd_check_lock(args):
    """Solo lectura — para mostrar estado al desarrollador. NO usar como gate
    antes de acquire/claim: usar `claim` directamente evita la carrera de
    secuenciar dos llamadas separadas."""
    m = load_manifest(args.context)
    if not m or not m.get("lock", {}).get("held", False):
        print("FREE")
        sys.exit(EXIT_OK)

    acquired = datetime.fromisoformat(m["lock"]["acquired_at"])
    elapsed = int((datetime.now() - acquired).total_seconds())
    ttl = m["lock"].get("ttl_seconds", 1800)

    if elapsed > ttl:
        print(f"STALE|{elapsed}|{ttl}")
    else:
        print(f"ACTIVE|{elapsed}|{ttl}|{m['lock'].get('acquired_by')}")
    sys.exit(EXIT_OK)


def cmd_claim(args):
    """Un solo comando: check + acquire atómico. Reemplaza la secuencia
    check-lock → acquire del protocolo viejo, que dependía de que el modelo
    encadenara bien dos llamadas."""
    def _do():
        ok, msg = _acquire(args.context, args.ttl)
        print(msg)
        if ok is True:
            sys.exit(EXIT_OK)
        elif ok is False:
            sys.exit(EXIT_LOCK_HELD)
        else:
            sys.exit(EXIT_LOCK_CONTENDED)
    with_write_lock(args.context, _do)


def cmd_acquire(args):
    """Alias retrocompatible de claim."""
    cmd_claim(args)


def cmd_release(args):
    def _do():
        p = _paths(args.context)
        m = load_manifest(args.context)
        if m and "lock" in m:
            m["lock"]["held"] = False
            m["lock"]["acquired_at"] = None
            m["lock"]["acquired_by"] = None
            save_manifest(args.context, m)
        if os.path.exists(p["lock"]):
            os.remove(p["lock"])
        print("SUCCESS|LOCK_RELEASED")
        sys.exit(EXIT_OK)
    with_write_lock(args.context, _do)


# ---------------------------------------------------------------------------
# Comandos CLI — tareas (lock granular por ítem)
# ---------------------------------------------------------------------------

def cmd_claim_task(args):
    agent_id = args.agent_id if args.agent_id else _generate_agent_id()

    def _do():
        m = load_manifest(args.context)
        if not m:
            print("FAIL|NO_SESSION")
            sys.exit(EXIT_LOCK_HELD)
        tasks = m.setdefault("task_claims", {})
        existing = tasks.get(args.task_id)
        if existing and existing["status"] == "claimed":
            print(f"FAIL|TASK_CLAIMED|{existing['agent_id']}")
            sys.exit(EXIT_LOCK_HELD)
        tasks[args.task_id] = {
            "status": "claimed",
            "agent_id": agent_id,
            "claimed_at": datetime.now().isoformat(),
        }
        save_manifest(args.context, m)
        print(f"SUCCESS|TASK_CLAIMED|{args.task_id}")
        sys.exit(EXIT_OK)
    with_write_lock(args.context, _do)


def cmd_release_task(args):
    def _do():
        m = load_manifest(args.context)
        if not m:
            print("FAIL|NO_SESSION")
            sys.exit(EXIT_LOCK_HELD)
        tasks = m.get("task_claims", {})
        task = tasks.get(args.task_id)
        if not task or task["status"] != "claimed":
            print(f"FAIL|TASK_NOT_CLAIMED|{args.task_id}")
            sys.exit(EXIT_LOCK_HELD)
        task["status"] = "done"
        task["released_at"] = datetime.now().isoformat()
        save_manifest(args.context, m)
        print(f"SUCCESS|TASK_RELEASED|{args.task_id}")
        sys.exit(EXIT_OK)
    with_write_lock(args.context, _do)


# ---------------------------------------------------------------------------
# Comandos CLI — utilidades
# ---------------------------------------------------------------------------

def cmd_check_completion(args):
    """Parser determinista de blockers_todo.md — el modelo no cuenta
    checkboxes a mano."""
    p = _paths(args.context)
    if not os.path.exists(p["blockers"]):
        print("total=0")
        print("completed=0")
        print("all_complete=false")
        sys.exit(EXIT_OK)

    with open(p["blockers"], "r", encoding="utf-8") as f:
        lines = f.readlines()

    total = completed = 0
    for line in lines:
        m = TASK_LINE_RE.match(line)
        if not m:
            continue
        total += 1
        if m.group(1).lower() == "x":
            completed += 1

    all_complete = total > 0 and completed == total
    print(f"total={total}")
    print(f"completed={completed}")
    print(f"all_complete={'true' if all_complete else 'false'}")
    sys.exit(EXIT_OK)


def cmd_validate(args):
    """Lint de los artefactos de sesión antes de dar por cerrado el cold boot
    o el checkpoint: existencia + cap de longitud. Determinista, no depende
    de que el modelo se autoevalúe."""
    p = _paths(args.context)
    session_dir = p["base"]
    targets = ["objective.md", "snapshot.md", "blockers_todo.md"]
    failures = []

    for fname in targets:
        path = os.path.join(session_dir, fname)
        if not os.path.exists(path):
            failures.append(f"MISSING|{fname}")
            continue
        size = os.path.getsize(path)
        if size > MAX_ARTIFACT_CHARS:
            failures.append(f"TOO_LONG|{fname}|{size}/{MAX_ARTIFACT_CHARS}")

    if failures:
        for f in failures:
            print(f"FAIL|{f}")
        sys.exit(EXIT_VALIDATION)

    print("SUCCESS|VALIDATE_OK")
    sys.exit(EXIT_OK)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Context Guard State Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # -- Sesión --
    p_check = subparsers.add_parser("check-lock")
    p_check.add_argument("--context", required=True)

    p_claim = subparsers.add_parser("claim")
    p_claim.add_argument("--context", required=True)
    p_claim.add_argument("--ttl", type=int, default=1800)

    p_acq = subparsers.add_parser("acquire")
    p_acq.add_argument("--context", required=True)
    p_acq.add_argument("--ttl", type=int, default=1800)

    p_release = subparsers.add_parser("release")
    p_release.add_argument("--context", required=True)

    # -- Tareas --
    p_claim_task = subparsers.add_parser("claim-task")
    p_claim_task.add_argument("--context", required=True)
    p_claim_task.add_argument("--task-id", required=True)
    p_claim_task.add_argument("--agent-id", default=None)

    p_release_task = subparsers.add_parser("release-task")
    p_release_task.add_argument("--context", required=True)
    p_release_task.add_argument("--task-id", required=True)

    # -- Utilidades --
    p_completion = subparsers.add_parser("check-completion")
    p_completion.add_argument("--context", required=True)

    p_validate = subparsers.add_parser("validate")
    p_validate.add_argument("--context", required=True)

    args = parser.parse_args()
    {
        "check-lock": cmd_check_lock,
        "claim": cmd_claim,
        "acquire": cmd_acquire,
        "release": cmd_release,
        "claim-task": cmd_claim_task,
        "release-task": cmd_release_task,
        "check-completion": cmd_check_completion,
        "validate": cmd_validate,
    }[args.command](args)