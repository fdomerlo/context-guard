"""Accessors for the artifacts shipped as package data (PLAN-2.1 F1).

Everything a host needs — the three phase documents, each host's slash
commands, rule files and config snippets — lives under `context_guard/_data/`
and is reached through `importlib.resources`. Never through paths relative to
this file or to the working directory: the package has to work installed from
a wheel, with no clone of the repo anywhere on the machine.

Names are validated against a fixed allowlist rather than joined onto the data
directory. These accessors are called with values that come from CLI flags, so
a joined path would turn `cg` into a reader for arbitrary files.
"""

from importlib import resources

from .errors import EXIT_GENERIC, GuardError

PHASES = ("plan", "execute", "verify")

HOSTS = ("claude-code", "opencode", "antigravity", "cursor")

# Which snippets each host ships, keyed by the short name callers pass. The
# file is always "<name>.snippet.json"; the mapping exists to be an allowlist,
# not to spell out a naming convention.
SNIPPETS = {
    "claude-code": ("settings", "mcp"),
    "opencode": ("agent", "permissions", "mcp"),
    "antigravity": ("hooks",),
    "cursor": ("mcp",),
}


class AssetNotFoundError(GuardError):
    """A requested phase, host or snippet is not part of the packaged data."""

    def __init__(self, message):
        super().__init__(f"FAIL|ASSET_NOT_FOUND|{message}", EXIT_GENERIC)


def _data_root():
    """The `_data` directory as a Traversable.

    `files()` targets the package and joins from there, so this resolves the
    same whether the package sits in a source checkout or in site-packages.
    """
    return resources.files("context_guard").joinpath("_data")


def get_phase(name):
    """Return the text of `_data/phases/<name>.md`.

    `name` must be one of PHASES — anything else raises, including a value that
    happens to name a real file elsewhere in the tree.
    """
    if name not in PHASES:
        raise AssetNotFoundError(f"unknown phase '{name}' (expected one of {', '.join(PHASES)})")
    return _data_root().joinpath("phases", f"{name}.md").read_text(encoding="utf-8")


def iter_host_files(host):
    """Yield `(relpath, text)` for every file this host installs.

    `relpath` is relative to the host's directory and always uses forward
    slashes, because callers join it onto a target directory to write the file
    out. Raises for an unknown host instead of yielding nothing: a `cg setup`
    that installs zero files and exits 0 looks exactly like success."""
    if host not in HOSTS:
        raise AssetNotFoundError(f"unknown host '{host}' (expected one of {', '.join(HOSTS)})")

    root = _data_root().joinpath("hosts", host)

    def walk(node, prefix):
        # Sorted so the file order — and therefore any output listing what was
        # installed — is stable across platforms and filesystems.
        for child in sorted(node.iterdir(), key=lambda c: c.name):
            relpath = f"{prefix}{child.name}"
            if child.is_dir():
                yield from walk(child, f"{relpath}/")
            else:
                yield relpath, child.read_text(encoding="utf-8")

    yield from walk(root, "")


def read_snippet(host, name):
    """Return the text of `_data/hosts/<host>/<name>.snippet.json`."""
    if host not in HOSTS:
        raise AssetNotFoundError(f"unknown host '{host}' (expected one of {', '.join(HOSTS)})")
    if name not in SNIPPETS[host]:
        raise AssetNotFoundError(
            f"host '{host}' has no '{name}' snippet "
            f"(expected one of {', '.join(SNIPPETS[host])})")
    return _data_root().joinpath(
        "hosts", host, f"{name}.snippet.json").read_text(encoding="utf-8")
