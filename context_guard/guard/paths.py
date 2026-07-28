"""Path resolution and agent identity for guard middleware."""

import os
import re
import socket
import time

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

MAX_ARTIFACT_CHARS = 6000  # ~1500 tokens, cap de longitud para artefactos

TASK_LINE_RE = re.compile(r"^\s*-\s*\[( |x|X|/)\]\s*(.*)$")


# ---------------------------------------------------------------------------
# Rutas — absolutas, ancladas al directorio del proyecto (context)
# ---------------------------------------------------------------------------

def get_paths(context):
    """Rutas de sesión ancladas al directorio del proyecto.

    Args:
        context: Ruta absoluta al directorio del proyecto. Se normaliza
                 con os.path.abspath() para garantizar rutas absolutas.

    Returns:
        dict con rutas absolutas: base, manifest, tasks, lock, write_lock, archive.
    """
    root = os.path.abspath(context)
    base = os.path.join(root, ".context-guard")
    return {
        "base": base,
        "manifest": os.path.join(base, "manifest.json"),
        "tasks": os.path.join(base, "tasks.md"),
        "lock": os.path.join(base, ".lock"),
        "write_lock": os.path.join(base, ".write.lock"),
        "archive": os.path.join(root, ".context-guard", "archive"),
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
