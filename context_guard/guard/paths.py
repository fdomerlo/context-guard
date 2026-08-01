"""Path resolution and agent identity for guard middleware."""

import os
import re
import socket
import time

from .errors import (
    AmbiguousChangeError,
    CommandResult,
    EXIT_GENERIC,
    LegacyLayoutError,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

MAX_ARTIFACT_CHARS = 6000  # ~1500 tokens, cap de longitud para artefactos

TASK_LINE_RE = re.compile(r"^\s*-\s*\[( |x|X|/)\]\s*(.*)$")

BASE_DIRNAME = ".context-guard"
CHANGES_DIRNAME = "changes"
ARCHIVE_DIRNAME = "archive"

# Name used when a context has no changes yet, and the destination of a
# migrated context-guard 1.x flat layout.
DEFAULT_CHANGE = "default"

# A change name becomes a directory name, so it must not be able to escape the
# changes directory or collide with the archive.
CHANGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# ---------------------------------------------------------------------------
# Rutas — absolutas, ancladas al directorio del proyecto (context)
# ---------------------------------------------------------------------------

def get_root(context):
    """Directorio del proyecto, normalizado a ruta absoluta."""
    return os.path.abspath(context)


def get_base(context):
    """Directorio raíz de context-guard dentro del proyecto."""
    return os.path.join(get_root(context), BASE_DIRNAME)


def get_changes_dir(context):
    """Directorio que contiene un subdirectorio por change."""
    return os.path.join(get_base(context), CHANGES_DIRNAME)


def get_archive_dir(context):
    """Destino de los changes completados."""
    return os.path.join(get_changes_dir(context), ARCHIVE_DIRNAME)


def validate_change_name(name):
    """Rechaza nombres que no pueden ser un directorio seguro.

    A change name is used verbatim as a directory name, so path traversal and
    collisions with the archive directory are rejected here rather than
    discovered later as a corrupted layout.
    """
    if not name or not CHANGE_NAME_RE.match(name):
        raise AmbiguousChangeError(
            f"FAIL|INVALID_CHANGE_NAME|{name}|"
            "must start alphanumeric and contain only [A-Za-z0-9._-]"
        )
    if name == ARCHIVE_DIRNAME:
        raise AmbiguousChangeError(
            f"FAIL|INVALID_CHANGE_NAME|{name}|reserved for archived changes"
        )
    return name


def list_changes(context):
    """Nombres de los changes activos, ordenados.

    The ordering is for display only. It must never be used to pick a change
    implicitly — see resolve_change.
    """
    changes_dir = get_changes_dir(context)
    if not os.path.isdir(changes_dir):
        return []
    names = []
    for entry in sorted(os.listdir(changes_dir)):
        if entry == ARCHIVE_DIRNAME:
            continue
        if os.path.isdir(os.path.join(changes_dir, entry)):
            names.append(entry)
    return names


def is_legacy_flat_layout(context):
    """True si el contexto usa el layout plano de context-guard 1.x.

    A 1.x context keeps manifest.json directly under .context-guard/ with no
    changes/ directory. Treating that as "no changes yet" would silently start
    an empty session and make the user's existing work look like it vanished.
    """
    base = get_base(context)
    if os.path.isdir(get_changes_dir(context)):
        return False
    return os.path.exists(os.path.join(base, "manifest.json"))


def resolve_change(context, change=None):
    """Determina sobre qué change opera un comando.

    Rules, in order:
      - an explicit name is always honoured;
      - a legacy 1.x layout is an error telling the user to migrate, never a
        silent fresh start;
      - exactly one active change is used implicitly;
      - several active changes is an error naming them all.

    That last rule is the point of this function. state-guard resolved
    ambiguity by taking the alphabetically first change, so an agent working
    on "zebra" silently operated on "alpha" and nothing ever said so.
    """
    if change:
        return validate_change_name(change)

    if is_legacy_flat_layout(context):
        raise LegacyLayoutError(get_base(context))

    names = list_changes(context)
    if not names:
        return DEFAULT_CHANGE
    if len(names) == 1:
        return names[0]
    raise AmbiguousChangeError(
        "FAIL|AMBIGUOUS_CHANGE|" + ",".join(names) +
        "|pass --change to say which one"
    )


def missing_session_result(context, change=None):
    """What to report when a command finds no manifest to operate on.

    Two different failures used to share one message. A caller who named a
    change and mistyped it got FAIL|NO_SESSION, which reads as "this project
    has no session" and sends them looking for a broken project instead of at
    the name they just typed. That lands hardest at the approval gate, the one
    place a human types a change name by hand.

    Deliberately not raised from resolve_change: `cg new` resolves a name that
    does not exist yet, by definition.
    """
    if change:
        available = list_changes(context)
        listed = ", ".join(available) if available else "(none)"
        return CommandResult(
            f"FAIL|CHANGE_NOT_FOUND|{change}|available: {listed}",
            EXIT_GENERIC,
        )
    return CommandResult("FAIL|NO_SESSION", EXIT_GENERIC)


def get_paths(context, change=None):
    """Rutas de sesión ancladas a un change dentro del proyecto.

    Args:
        context: Ruta absoluta al directorio del proyecto. Se normaliza
                 con os.path.abspath() para garantizar rutas absolutas.
        change:  Nombre del change. Si es None se resuelve con resolve_change.

    Returns:
        dict con rutas absolutas: base, manifest, tasks, lock, write_lock,
        archive, change.
    """
    name = resolve_change(context, change)
    base = os.path.join(get_changes_dir(context), name)
    return {
        "base": base,
        "manifest": os.path.join(base, "manifest.json"),
        "tasks": os.path.join(base, "tasks.md"),
        "lock": os.path.join(base, ".lock"),
        "write_lock": os.path.join(base, ".write.lock"),
        "archive": get_archive_dir(context),
        "change": name,
    }


# ---------------------------------------------------------------------------
# Identidad del agente
# ---------------------------------------------------------------------------

def generate_agent_id():
    """Identidad consistente para locks de sesión y de tarea.

    Incluye PID + hostname + timestamp para unicidad global.
    Para ownership tracking entre claim/release, usar el agent_id
    retornado por claim y pasarlo explícitamente a release.
    """
    return f"{os.getpid()}-{socket.gethostname()}-{int(time.time())}"
