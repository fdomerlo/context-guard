"""Migration from the two legacy layouts into the multi-change layout.

Two sources are supported:

  - state-guard's `.state-guard/changes/{name}/state.ini` (schema v2, INI)
  - context-guard 1.x's flat `.context-guard/manifest.json`

Both are *copied*, never moved: if a migration produces something wrong the
user still has the original to go back to. Migration is idempotent, and it
refuses to overwrite a change that already exists — the one thing worse than
not migrating is migrating over live work.
"""

import configparser
import os
import shutil

from .manifest import (
    DEFAULT_PIPELINE,
    SCHEMA_VERSION,
    create_initial_manifest,
    load_manifest,
    save_manifest,
)
from .paths import (
    DEFAULT_CHANGE,
    get_archive_dir,
    get_base,
    get_changes_dir,
    get_paths,
    get_root,
    list_changes,
)
from .errors import CommandResult, EXIT_OK, EXIT_VALIDATION

STATE_GUARD_DIRNAME = ".state-guard"

# state-guard writes phases in lowercase; this pipeline is uppercase. A missed
# conversion leaves lock_phase="execute", which matches no valid phase and
# locks the change out of every transition.
_NO_PHASE = {"", "none", "None"}

# Artifacts that must exist for the normal gates to work. A migrated change
# genuinely lacks some of them, and saying so with [PENDING] routes it through
# the usual validation instead of pretending it is complete.
_REQUIRED_ARTIFACTS = {
    "objective.md": "[PENDING] Define objective here",
    "snapshot.md": "[PENDING] Define snapshot here",
    "tasks.md": "[PENDING] Define tasks here",
    "review-report.md": "[PENDING] Write static review here",
    "verify-report.md": "[PENDING] Write dynamic verification here",
}


def _normalise_phase(value, default="PLAN"):
    if value is None:
        return default
    value = value.strip()
    if value in _NO_PHASE:
        return default
    return value.upper()


def _normalise_phase_list(value):
    if not value:
        return []
    out = []
    for item in value.split(","):
        item = item.strip()
        if item and item not in _NO_PHASE:
            out.append(item.upper())
    return out


def _split_recognised_phases(phases):
    """Separate phases this pipeline knows about from ones it does not.

    state-guard tracked pseudo-phases (a 'hotfix' bypass state, in the audit
    that found this) that are not PLAN/EXECUTE/VERIFY. Carrying one straight
    into completed_phases plants a value no future DAG invariant check would
    expect. Silently dropping it would be just as wrong — it is real history
    the user might want back — so the unrecognised ones go to legacy_phases
    instead of vanishing.
    """
    recognised = [p for p in phases if p in DEFAULT_PIPELINE]
    unrecognised = [p for p in phases if p not in DEFAULT_PIPELINE]
    return recognised, unrecognised


def _state_guard_changes_dir(context):
    return os.path.join(get_root(context), STATE_GUARD_DIRNAME, "changes")


def _find_state_guard_changes(context):
    """Names of state-guard changes that carry a state.ini."""
    root = _state_guard_changes_dir(context)
    if not os.path.isdir(root):
        return []
    names = []
    for entry in sorted(os.listdir(root)):
        if entry == "archive":
            continue
        if os.path.exists(os.path.join(root, entry, "state.ini")):
            names.append(entry)
    return names


def _manifest_from_state_ini(context, change, ini_path):
    """Translate a state-guard state.ini (schema v2) into a manifest v3."""
    config = configparser.ConfigParser()
    config.read(ini_path, encoding="utf-8")

    manifest = create_initial_manifest(context, change)

    current = _normalise_phase(config.get("Graph", "current_phase", fallback=None))
    lock_phase = _normalise_phase(config.get("Graph", "lock_phase", fallback=None))
    completed_raw = _normalise_phase_list(
        config.get("Graph", "completed_phases", fallback=""))
    completed, legacy_phases = _split_recognised_phases(completed_raw)
    pending = _normalise_phase_list(
        config.get("Graph", "pending_phases", fallback=""))

    manifest["current_phase"] = current
    manifest["lock_phase"] = lock_phase
    manifest["completed_phases"] = completed
    manifest["pending_phases"] = pending or [
        p for p in DEFAULT_PIPELINE if p not in completed
    ]
    if legacy_phases:
        manifest["legacy_phases"] = legacy_phases

    summary = config.get("Session", "session_summary", fallback="").strip()
    if summary:
        manifest.setdefault("session", {})["session_summary"] = summary

    # A recorded human approval is preserved. Discarding it would make the user
    # re-approve work they already signed off on. Read only — the approval flow
    # itself is not wired up here.
    if config.has_section("Gate"):
        approved_at = config.get("Gate", "plan_approved_at", fallback="").strip()
        approved_by = config.get("Gate", "plan_approved_by", fallback="").strip()
        if approved_at or approved_by:
            approval = {"by": approved_by or "unknown", "at": approved_at or None}
            reason = config.get("Gate", "hotfix_bypass_reason", fallback="").strip()
            if reason:
                approval["hotfix"] = True
                approval["reason"] = reason
            manifest["approval"] = approval

    manifest["migrated_from"] = "state-guard/state.ini"
    return manifest


def _copy_artifacts(src_dir, dest_dir, skip=()):
    """Copy every regular file from a legacy change directory."""
    os.makedirs(dest_dir, exist_ok=True)
    for entry in sorted(os.listdir(src_dir)):
        if entry in skip:
            continue
        src = os.path.join(src_dir, entry)
        if not os.path.isfile(src):
            continue
        shutil.copy2(src, os.path.join(dest_dir, entry))


def _scaffold_missing_artifacts(dest_dir):
    for name, placeholder in _REQUIRED_ARTIFACTS.items():
        path = os.path.join(dest_dir, name)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(placeholder)


def _migrate_state_guard(context, findings):
    """Copy every state-guard change into changes/{name}/."""
    src_root = _state_guard_changes_dir(context)
    for name in _find_state_guard_changes(context):
        src_dir = os.path.join(src_root, name)
        p = get_paths(context, name)

        # Idempotence and safety are the same rule here: an existing change may
        # already carry work done after a previous migration.
        if os.path.exists(p["manifest"]):
            findings.append(f"SKIP|{name}|already migrated")
            continue

        os.makedirs(p["base"], exist_ok=True)
        _copy_artifacts(src_dir, p["base"], skip=("state.ini",))
        _scaffold_missing_artifacts(p["base"])
        manifest = _manifest_from_state_ini(
            context, name, os.path.join(src_dir, "state.ini"))
        save_manifest(context, manifest, name)
        findings.append(f"MIGRATED|{name}|from state-guard")


def _migrate_flat_layout(context, findings):
    """Move a context-guard 1.x flat layout into changes/default/."""
    base = get_base(context)
    flat_manifest = os.path.join(base, "manifest.json")
    if not os.path.exists(flat_manifest):
        return None

    dest = get_paths(context, DEFAULT_CHANGE)
    if os.path.exists(dest["manifest"]):
        # The flat data and a live `default` change cannot both be right, and
        # picking one silently would destroy the other.
        return CommandResult(
            f"FAIL|MIGRATE_CONFLICT|{DEFAULT_CHANGE}|"
            "a flat 1.x manifest and an existing change both claim this name",
            EXIT_VALIDATION,
        )

    with open(flat_manifest, "r", encoding="utf-8") as f:
        import json
        manifest = json.load(f)

    manifest["schema_version"] = SCHEMA_VERSION
    manifest["change_name"] = DEFAULT_CHANGE
    manifest["migrated_from"] = "context-guard/1.x-flat"

    os.makedirs(dest["base"], exist_ok=True)
    for entry in sorted(os.listdir(base)):
        if entry in ("manifest.json", "changes", "archive"):
            continue
        src = os.path.join(base, entry)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dest["base"], entry))

    _scaffold_missing_artifacts(dest["base"])
    save_manifest(context, manifest, DEFAULT_CHANGE)

    # The flat manifest has to go, or is_legacy_flat_layout keeps firing and
    # the context stays permanently "unmigrated".
    os.remove(flat_manifest)
    findings.append(f"MIGRATED|{DEFAULT_CHANGE}|from context-guard 1.x flat layout")
    return None


def _migrate_flat_archive(context, findings):
    """Copy a 1.x flat layout's own archive/ subdirectories into
    changes/archive/.

    _migrate_flat_layout only ever copied files (`if os.path.isfile(src)`),
    so a 1.x archive/ full of completed changes was silently left behind,
    orphaned next to the new (empty) changes/archive/ — two archive
    directories where the old one nothing pointed at anymore. Runs
    independently of whether a flat manifest.json still exists, since the
    archive can outlive it (e.g. the main manifest was already migrated by
    an older `cg migrate` before this fix shipped).

    Copies, not moves, like every other path in this module: if this
    produces something wrong the original archive is still there.
    """
    old_archive = os.path.join(get_base(context), "archive")
    if not os.path.isdir(old_archive):
        return

    new_archive = get_archive_dir(context)
    for entry in sorted(os.listdir(old_archive)):
        src = os.path.join(old_archive, entry)
        if not os.path.isdir(src):
            continue
        dest = os.path.join(new_archive, entry)
        if os.path.exists(dest):
            findings.append(f"SKIP|archive/{entry}|already migrated")
            continue
        os.makedirs(new_archive, exist_ok=True)
        shutil.copytree(src, dest)
        findings.append(f"MIGRATED|archive/{entry}|from context-guard 1.x flat archive")


def cmd_migrate(context):
    """Convierte los layouts legacy al layout multi-change.

    Idempotent: changes that already exist are skipped, not overwritten.
    """
    findings = []

    conflict = _migrate_flat_layout(context, findings)
    if conflict is not None:
        return conflict

    _migrate_flat_archive(context, findings)
    _migrate_state_guard(context, findings)

    if not findings:
        return CommandResult("SUCCESS|NOTHING_TO_MIGRATE", EXIT_OK)
    return CommandResult("\n".join(findings), EXIT_OK)
