"""`cg setup` — install the host adapters (PLAN-2.1 F2).

Replaces the shell installer that 2.0 shipped under adapters/. Two things
changed beyond the language:

- **Scope.** 2.0 installed per-project by default, which meant visiting every
  project. The default here is global — one command per machine — with
  `--project` keeping the old mode for teams that want the config committed.
- **Source.** The artifacts come from the package's embedded data, not from a
  clone of the repository sitting next to the target.

Every merge preserves configuration the user already had and is idempotent by
construction: existing keys are never replaced, list entries are appended only
when absent, and output is always written with the same formatting, so a
second run produces byte-identical files.
"""

import json
import os

from .assets import iter_host_files, read_snippet
from .errors import CommandResult, EXIT_OK, EXIT_VALIDATION, GuardError

# CLI host names map to the packaged directory names, which are not identical:
# the host is called "claude", its adapter directory "claude-code".
HOST_DIRS = {
    "claude": "claude-code",
    "opencode": "opencode",
    "antigravity": "antigravity",
}
VALID_HOSTS = tuple(HOST_DIRS) + ("all",)


class ConfigCorruptError(GuardError):
    """An existing config file could not be parsed.

    The shell installer caught this and carried on with an empty dict, which
    silently overwrote whatever the user had — the bug that made a stray
    "//" in a URL destroy a config file. Refusing is the only safe move: this
    code cannot tell a file it fails to parse from one it would destroy.
    """

    def __init__(self, path):
        super().__init__(
            f"FAIL|CONFIG_UNPARSEABLE|{path}|refusing to overwrite it — "
            "fix or move the file and re-run",
            EXIT_VALIDATION,
        )


def _home():
    return os.path.expanduser("~")


def _strip_jsonc_comments(raw):
    """Remove // and /* */ comments, ignoring anything inside a string.

    A regex cannot do this correctly and the project has now been bitten
    twice proving it. First `//.*` ate the rest of the line starting at the
    "//" in "https://opencode.ai/config.json"; the negative lookbehind added
    to fix that left `/\\*.*?\\*/` free to eat the "/**/" in the glob
    ".context-guard/**/manifest.json" — a pattern this installer writes
    itself, so the corruption appeared on the second run and broke
    idempotency.

    Tracking string state is the only thing that distinguishes a comment from
    a comment-shaped substring of a value, so that is what this does.
    """
    out = []
    i, n = 0, len(raw)
    in_string = False
    while i < n:
        ch = raw[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(raw[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if raw.startswith("//", i):
            end = raw.find("\n", i)
            i = n if end == -1 else end
            continue
        if raw.startswith("/*", i):
            end = raw.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _read_json(path, jsonc=False):
    """Existing config, or None when there is no file yet."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    if jsonc:
        raw = _strip_jsonc_comments(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ConfigCorruptError(path)


def _write_json(path, cfg):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def _write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _append_missing(target, entries):
    for entry in entries:
        if entry not in target:
            target.append(entry)


# ---------------------------------------------------------------------------
# Per-host installers. Each returns the list of paths it touched, relative to
# the scope root, so the caller can print exactly what changed.
# ---------------------------------------------------------------------------

def _install_claude(root, with_mcp, global_scope):
    touched = []

    for relpath, text in iter_host_files("claude-code"):
        if not relpath.startswith("commands/"):
            continue
        name = relpath.split("/", 1)[1]
        _write_text(os.path.join(root, ".claude", "commands", name), text)
        touched.append(f".claude/commands/{name}")

    settings_path = os.path.join(root, ".claude", "settings.json")
    snippet = json.loads(read_snippet("claude-code", "settings"))
    cfg = _read_json(settings_path) or {}
    perms = cfg.setdefault("permissions", {})
    _append_missing(perms.setdefault("ask", []), snippet["permissions"]["ask"])
    _append_missing(perms.setdefault("deny", []), snippet["permissions"].get("deny", []))
    _write_json(settings_path, cfg)
    touched.append(".claude/settings.json")

    if with_mcp:
        # User scope lives in ~/.claude.json; a project keeps its servers in
        # .mcp.json, which is the file Claude Code reads per repository.
        # Keyed off the scope rather than off comparing root to $HOME, which
        # would pick the wrong file for `--project ~`.
        mcp_rel = ".claude.json" if global_scope else ".mcp.json"
        mcp_path = os.path.join(root, mcp_rel)
        snippet = json.loads(read_snippet("claude-code", "mcp"))
        cfg = _read_json(mcp_path) or {}
        cfg.setdefault("mcpServers", {}).setdefault(
            "context-guard", snippet["mcpServers"]["context-guard"])
        _write_json(mcp_path, cfg)
        touched.append(mcp_rel)

    return touched


def _install_opencode(root, with_mcp, global_scope):
    touched = []

    commands_dir = (os.path.join(".config", "opencode", "commands")
                    if global_scope else os.path.join(".opencode", "commands"))
    for relpath, text in iter_host_files("opencode"):
        if not relpath.startswith("commands/"):
            continue
        name = relpath.split("/", 1)[1]
        _write_text(os.path.join(root, commands_dir, name), text)
        touched.append(f"{commands_dir}/{name}".replace(os.sep, "/"))

    cfg_rel = (os.path.join(".config", "opencode", "opencode.json")
               if global_scope else "opencode.json")
    cfg_path = os.path.join(root, cfg_rel)
    cfg = _read_json(cfg_path, jsonc=True)
    if cfg is None:
        cfg = {"$schema": "https://opencode.ai/config.json", "agent": {}}

    cfg.setdefault("agent", {}).update(json.loads(read_snippet("opencode", "agent")))

    # Top-level "permission", not nested in the agent entry, so it applies
    # regardless of which agent runs the command. Merged per-pattern so a rule
    # the user set for a pattern we do not know about survives untouched.
    permissions = json.loads(read_snippet("opencode", "permissions"))
    perm_cfg = cfg.setdefault("permission", {})
    for category, rules in permissions.get("permission", {}).items():
        category_cfg = perm_cfg.setdefault(category, {})
        for pattern, mode in rules.items():
            category_cfg.setdefault(pattern, mode)

    if with_mcp:
        snippet = json.loads(read_snippet("opencode", "mcp"))
        cfg.setdefault("mcp", {}).setdefault(
            "context-guard", snippet["mcp"]["context-guard"])

    _write_json(cfg_path, cfg)
    touched.append(cfg_rel.replace(os.sep, "/"))
    return touched


# Antigravity's global customization root. Confirmed against a real install
# (PLAN-2.2 F3.0): the CLI's own bundled `agy-customizations` skill documents
# `~/.gemini/config/` as the machine-local discovery location, and it is
# already where hooks.json, mcp_config.json and plugins/ live. Not
# `~/.gemini/antigravity-cli/`, which is the CLI's own state directory — its
# `builtin/` subtree carries a checksum the updater rewrites, so a skill
# installed there would be reverted by the next CLI update.
ANTIGRAVITY_GLOBAL_ROOT = (".gemini", "config")
ANTIGRAVITY_SKILL_REL = ANTIGRAVITY_GLOBAL_ROOT + ("skills", "context-guard", "SKILL.md")

# Both artifacts we write into a user's tree as whole files carry this marker,
# so a later run can tell its own output from a file of the same name the user
# wrote themselves.
OWNERSHIP_MARKER = "<!-- context-guard:begin -->"

HOOKS_MANUAL_FIX = ("left untouched; add the deny hook manually "
                    "(see docs/adapters/antigravity/PERMISSIONS.md)")

# Annotated in the touched list because installing the hook is the one thing
# `cg setup` does that takes something away from the agent. Consented is not
# the same as silent: the line has to say what it is and how to decline it.
HOOKS_NOTE = "(deny hook for cg approve — skip with --no-hooks)"


def _hooks_shape_problem(cfg):
    """Why this config cannot be merged into, or None if it can.

    The merge used to assume the shape and reach straight for
    `.setdefault("hooks", {}).setdefault("PreToolUse", [])`. Against a
    `{"hooks": [...]}` it raised AttributeError and printed a traceback at a
    user holding a perfectly ordinary file we simply did not expect.

    Absent keys are fine: `{}` is what a fresh config looks like, and a check
    strict enough to reject it would break the common case for the rare one.
    Only a key present with the wrong type is a problem.
    """
    if not isinstance(cfg, dict):
        return "the root of the file is not a JSON object"
    hooks = cfg.get("hooks")
    if hooks is None:
        return None
    if not isinstance(hooks, dict):
        return '"hooks" is not a JSON object'
    pre_tool_use = hooks.get("PreToolUse")
    if pre_tool_use is not None and not isinstance(pre_tool_use, list):
        return '"hooks.PreToolUse" is not a list'
    return None


def _embedded_antigravity_file(relpath):
    for name, text in iter_host_files("antigravity"):
        if name == relpath:
            return text
    return None


def _write_owned(path, text):
    """Write one of our marked files, unless something else already owns it.

    Returns `(written, skip)`. A file carrying OWNERSHIP_MARKER is one of ours
    and is refreshed, which is what lets a `cg` upgrade actually reach the
    artifacts an earlier version installed. Anything else is left exactly as
    it is: `context-guard` is a plausible name for a skill or a rule the user
    wrote themselves, and this code cannot reconstruct what it would destroy.

    Not a failure. A name collision means the user has a file here on purpose;
    it says so and moves on, rather than deciding the machine is broken.
    """
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            if OWNERSHIP_MARKER not in f.read():
                return False, f"SKIP|SKILL_EXISTS|{path}|not written by context-guard, left as is"
    _write_text(path, text)
    return True, None


def _install_antigravity(root, global_scope, no_hooks=False):
    """Global scope installs the discovery skill and the deny hook; project
    scope installs the workspace rule.

    The split follows what each artifact is for. The hook lives in user config
    by definition, so it has no meaning in a project install; the workspace
    rule travels with the repository. Until 2.2 the global case installed the
    hook alone — enforcement with nothing to discover it by — and the only
    bootstrap artifact was written by `cg new`, which nobody runs before they
    know `cg` exists. The skill closes that loop: Antigravity loads it by
    progressive disclosure, so it costs nothing until the model picks it.

    Returns `(touched, failure, skips)`. Unlike the other hosts this one
    writes into files it did not create and cannot fully predict, so it needs
    both a way to fail without taking the whole run down and a way to decline
    a single artifact without failing at all.
    """
    if not global_scope:
        text = _embedded_antigravity_file("rules/context-guard.md")
        if text is None:
            return [], None, []
        rule_rel = os.path.join(".agents", "rules", "context-guard.md")
        _write_text(os.path.join(root, rule_rel), text)
        return [rule_rel.replace(os.sep, "/")], None, []

    touched = []
    skips = []

    skill_text = _embedded_antigravity_file("skills/context-guard/SKILL.md")
    if skill_text is not None:
        skill_rel = os.path.join(*ANTIGRAVITY_SKILL_REL)
        written, skip = _write_owned(os.path.join(root, skill_rel), skill_text)
        if written:
            touched.append(skill_rel.replace(os.sep, "/"))
        if skip:
            skips.append(skip)

    # `--no-hooks` declines the enforcement, not the discovery. A user who
    # does not want the deny hook still wants their agent to know the tool
    # is there.
    if no_hooks:
        return touched, None, skips

    hooks_rel = os.path.join(*ANTIGRAVITY_GLOBAL_ROOT, "hooks.json")
    hooks_path = os.path.join(root, hooks_rel)

    try:
        cfg = _read_json(hooks_path)
    except ConfigCorruptError:
        return touched, f"FAIL|HOOKS_UNPARSEABLE|{hooks_path}|{HOOKS_MANUAL_FIX}", skips
    if cfg is None:
        cfg = {}

    problem = _hooks_shape_problem(cfg)
    if problem:
        # Reported and left alone rather than normalised. Rewriting a config
        # into the shape this code prefers would discard whatever the user's
        # own tooling put there, and we cannot know what that was for.
        return (touched,
                f"FAIL|HOOKS_UNRECOGNISED|{hooks_path}|{HOOKS_MANUAL_FIX} ({problem})",
                skips)

    snippet = json.loads(read_snippet("antigravity", "hooks"))
    new_hook = snippet["hooks"]["PreToolUse"][0]

    pre_tool_use = cfg.setdefault("hooks", {}).setdefault("PreToolUse", [])
    already = any(
        isinstance(h, dict)
        and h.get("matcher", {}).get("tool") == new_hook["matcher"]["tool"]
        and h.get("matcher", {}).get("commandPattern") == new_hook["matcher"]["commandPattern"]
        for h in pre_tool_use
    )
    if not already:
        pre_tool_use.append(new_hook)
    _write_json(hooks_path, cfg)
    touched.append(f"{hooks_rel.replace(os.sep, '/')} {HOOKS_NOTE}")
    return touched, None, skips


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _detected(host, home):
    """Whether a host looks installed on this machine.

    Same heuristic the shell installer used — a config directory — plus the
    binary on
    PATH, which catches a fresh install that has not written a config yet.
    Claude Code has no detection leg: it always installs under `--host all`,
    matching 2.0's behaviour.
    """
    if host == "claude":
        return True
    if host == "opencode":
        return (os.path.isdir(os.path.join(home, ".config", "opencode"))
                or _on_path("opencode"))
    if host == "antigravity":
        return os.path.isdir(os.path.join(home, ".gemini")) or _on_path("antigravity")
    return False


def _on_path(binary):
    import shutil
    return shutil.which(binary) is not None


def hosts_to_install(host, home):
    """Which hosts a given --host value resolves to.

    Naming a host installs it regardless of detection: asking for it
    explicitly is itself the signal.
    """
    if host != "all":
        return [host]
    return [h for h in HOST_DIRS if _detected(h, home)]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_setup(host="all", with_mcp=False, project=None, no_hooks=False):
    """Install the adapters and return a CommandResult listing what changed."""
    if host not in VALID_HOSTS:
        return CommandResult(
            f"FAIL|INVALID_HOST|{host}|expected one of {', '.join(VALID_HOSTS)}",
            EXIT_VALIDATION,
        )

    global_scope = project is None
    root = _home() if global_scope else os.path.abspath(project)
    selected = hosts_to_install(host, _home())

    lines = [f"Installing context-guard adapters into {root} ..."]
    touched = []
    failures = []
    skips = []

    for name in selected:
        if name == "claude":
            touched += _install_claude(root, with_mcp, global_scope)
            lines.append("  -> Claude Code: commands installed, cg approve on the ask list")
        elif name == "opencode":
            touched += _install_opencode(root, with_mcp, global_scope)
            lines.append("  -> OpenCode: commands installed, config merged")
        elif name == "antigravity":
            # One command configures three independent hosts. A host that
            # cannot be configured reports and steps aside: letting it abort
            # the run would let one unrelated file on disk decide that the
            # tool does not work on this machine.
            host_touched, failure, host_skips = _install_antigravity(
                root, global_scope, no_hooks)
            touched += host_touched
            skips += host_skips
            if failure:
                failures.append(failure)
                lines.append("  -> Antigravity: hooks.json left untouched, see below")
            elif not global_scope:
                lines.append("  -> Antigravity: workspace rule installed")
            elif no_hooks:
                lines.append("  -> Antigravity: skill installed, deny hook "
                             "skipped (--no-hooks)")
            else:
                lines.append("  -> Antigravity: skill installed, deny hook merged "
                             "into ~/.gemini/config/hooks.json")

    for name in HOST_DIRS:
        if name in selected:
            continue
        # Two different reasons to skip, and telling a user their host was
        # "not detected" when they asked for a different one sends them
        # debugging a detection problem they do not have.
        if host == "all":
            lines.append(f"  -> {name}: not detected, skipped "
                         f"(pass --host {name} to install it anyway)")
        else:
            lines.append(f"  -> {name}: skipped (--host {host})")

    if global_scope:
        lines.append("")
        lines.append("Phase files are materialised per project by `cg new`.")
    lines.append("")
    lines.append("Files touched:")
    if touched:
        lines.extend(f"  {path}" for path in touched)
    else:
        lines.append("  (none)")

    # Listed apart from both the touched files and the failures: nothing was
    # written, and nothing is wrong. Kept visible anyway, because the user is
    # otherwise left with a host that installed "successfully" and still has
    # no entry point.
    if skips:
        lines.append("")
        lines.append("Skipped (a file of ours already exists, written by someone else):")
        lines.extend(f"  {skip}" for skip in skips)

    if failures:
        lines.append("")
        lines.append("Failed:")
        lines.extend(f"  {failure}" for failure in failures)

    # A run where one host could not be configured is not a success, even
    # though the others were: exiting 0 would let a caller script past a host
    # that silently has no enforcement.
    return CommandResult("\n".join(lines),
                         EXIT_VALIDATION if failures else EXIT_OK)


# ---------------------------------------------------------------------------
# Project scaffolding, used by `cg new`
# ---------------------------------------------------------------------------

def materialise_phases(context):
    """Write the embedded phase documents into a project, without clobbering.

    A phase file that already exists is left exactly as it is, even when it
    differs from the embedded copy: the project may have customised it, and
    silently restoring the stock text would delete a team's own process.
    `cg doctor` surfaces the difference instead.
    """
    written = []
    phases_dir = os.path.join(context, ".context-guard", "phases")
    from .assets import PHASES, get_phase
    for name in PHASES:
        path = os.path.join(phases_dir, f"{name}.md")
        if os.path.exists(path):
            continue
        _write_text(path, get_phase(name))
        written.append(path)
    return written


def materialise_antigravity_rule(context):
    """Write the workspace rule file, unless the project already has one."""
    path = os.path.join(context, ".agents", "rules", "context-guard.md")
    if os.path.exists(path):
        return []
    for relpath, text in iter_host_files("antigravity"):
        if relpath == "rules/context-guard.md":
            _write_text(path, text)
            return [path]
    return []


def antigravity_detected():
    return _detected("antigravity", _home())


def diverged_phases(context):
    """Phase files that exist but differ from the embedded copy."""
    from .assets import PHASES, get_phase
    out = []
    for name in PHASES:
        path = os.path.join(context, ".context-guard", "phases", f"{name}.md")
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            if f.read() != get_phase(name):
                out.append(f"{name}.md")
    return out
