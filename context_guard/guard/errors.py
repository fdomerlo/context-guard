"""Exit codes, typed exceptions, and command result type for guard middleware."""

from collections import namedtuple

# ---------------------------------------------------------------------------
# Exit codes — machine-readable, consumidos por el harness
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_GENERIC = 1             # corrupt manifest, missing session
EXIT_LOCK_HELD = 2           # another agent holds the lock/claim — retry with backoff
EXIT_LOCK_CONTENDED = 3      # lost the takeover race — retryable
EXIT_VALIDATION = 4          # artifact missing / [PENDING] / too long / wrong language
EXIT_BAD_TRANSITION = 5      # phase not authorized by the DAG — do NOT retry
EXIT_APPROVAL_REQUIRED = 6   # human approval missing — only a human resolves it


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


class ValidationError(GuardError):
    """Un artefacto no pasó validación (faltante, excede cap, etc.)."""
    def __init__(self, failures):
        msg = "\n".join(f"FAIL|{f}" for f in failures)
        super().__init__(msg, EXIT_VALIDATION)


class AmbiguousChangeError(GuardError):
    """Varios changes activos y ninguno indicado explícitamente.

    Never resolved by picking one: guessing here means the agent operates on a
    change it did not choose while believing it did.
    """
    def __init__(self, message):
        super().__init__(message, EXIT_VALIDATION)


class LegacyLayoutError(GuardError):
    """El contexto usa el layout plano de 1.x y necesita migración.

    Reported rather than silently ignored: starting a fresh empty change on
    top of a 1.x context makes the user's existing work look like it vanished.
    """
    def __init__(self, base):
        super().__init__(
            f"FAIL|LEGACY_LAYOUT|{base}|run `cg migrate` to convert it",
            EXIT_GENERIC,
        )

