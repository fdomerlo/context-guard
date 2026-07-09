"""Exit codes, typed exceptions, and command result type for guard middleware."""

from collections import namedtuple

# ---------------------------------------------------------------------------
# Exit codes — machine-readable, consumidos por el harness
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_LOCK_HELD = 1         # otra sesión activa, no reintentar automáticamente
EXIT_LOCK_CONTENDED = 2    # perdiste la carrera contra otro takeover de lock stale
EXIT_VALIDATION = 3        # artefacto mal formado o excede el cap de tokens
EXIT_GENERIC = 4           # manifest corrupto u otro error irrecuperable


# ---------------------------------------------------------------------------
# Command result — retornado por toda función de negocio
# ---------------------------------------------------------------------------

CommandResult = namedtuple("CommandResult", ["message", "exit_code"])


# ---------------------------------------------------------------------------
# Typed exceptions — para errores irrecuperables
# ---------------------------------------------------------------------------

class GuardError(Exception):
    """Error base del middleware. Incluye exit_code para que cli.py traduzca."""
    def __init__(self, message, exit_code=EXIT_GENERIC):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class ManifestCorruptError(GuardError):
    """manifest.json existe pero no es JSON válido."""
    def __init__(self, message):
        super().__init__(f"FAIL|CORRUPT_MANIFEST|{message}", EXIT_GENERIC)


class LockHeldError(GuardError):
    """El lock de sesión está ocupado por otro agente."""
    def __init__(self, owner=None):
        msg = f"FAIL|LOCK_HELD|{owner}" if owner else "FAIL|LOCK_HELD"
        super().__init__(msg, EXIT_LOCK_HELD)


class LockContendedError(GuardError):
    """Otro agente ganó la carrera por un lock stale."""
    def __init__(self):
        super().__init__("FAIL|LOCK_CONTENDED", EXIT_LOCK_CONTENDED)


class ValidationError(GuardError):
    """Un artefacto no pasó validación (faltante, excede cap, etc.)."""
    def __init__(self, failures):
        msg = "\n".join(f"FAIL|{f}" for f in failures)
        super().__init__(msg, EXIT_VALIDATION)
