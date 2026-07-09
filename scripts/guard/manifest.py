"""Manifest I/O with atomic writes for guard middleware."""

import json
import os

from guard.paths import get_paths
from guard.errors import ManifestCorruptError


def load_manifest(context):
    """Carga el manifest del contexto dado.

    Returns:
        dict or None: El manifest parseado, o None si no existe.

    Raises:
        ManifestCorruptError: Si el archivo existe pero no es JSON válido.
    """
    p = get_paths(context)
    if not os.path.exists(p["manifest"]):
        return None
    try:
        with open(p["manifest"], "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError) as e:
        raise ManifestCorruptError(str(e))


def save_manifest(context, data):
    """Escribe el manifest con write atómico (tmp + rename).

    Crea los directorios necesarios si no existen.
    """
    p = get_paths(context)
    os.makedirs(os.path.dirname(p["manifest"]), exist_ok=True)
    tmp_path = p["manifest"] + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.rename(tmp_path, p["manifest"])
