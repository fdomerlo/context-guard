"""`cg init` — Initialize repository for the Context Guard protocol.

Unified replacement for disciplined-scaffold bootstrap:
- Generates/updates declarative agent contract (AGENTS.md) with ownership markers.
- Writes CLAUDE.md pointing to AGENTS.md (@AGENTS.md).
- Initializes .context-guard/ and materializes reference phase documents.
- Installs Git hooks: Conventional Commits (commit-msg) and pre-commit gate.
- Configures git core.hooksPath when inside a git repository.
- Detects agent hosts (Antigravity, Cursor, etc.) and materializes workspace rules.
"""

import os
import shutil
import subprocess

from .assets import PHASES, get_phase
from .errors import CommandResult, EXIT_OK, EXIT_VALIDATION, GuardError
from .setup import (
    antigravity_detected,
    cursor_detected,
    materialise_antigravity_rule,
    materialise_cursor_rule,
    materialise_phases,
)

OWNERSHIP_MARKER_BEGIN = "<!-- context-guard:begin -->"
OWNERSHIP_MARKER_END = "<!-- context-guard:end -->"

DEFAULT_COMMIT_TYPES = "feat, fix, docs, refactor, test, chore, release"

COMMIT_MSG_HOOK_SCRIPT = """#!/bin/sh
# Installed by Context Guard (cg init)
# Rejects commit messages that don't follow Conventional Commits.
# Bypass in an emergency with: git commit --no-verify

msg_file="$1"
first_line=$(head -n1 "$msg_file")

pattern='^(feat|fix|docs|refactor|test|chore|release)(\\([a-zA-Z0-9_.-]+\\))?!?: .+'

if ! echo "$first_line" | grep -Eq "$pattern"; then
  echo "commit-msg hook: message doesn't look like a conventional commit."
  echo "  got:      $first_line"
  echo "  expected: type(scope): description   (types: feat fix docs refactor test chore release)"
  echo "  bypass with: git commit --no-verify"
  exit 1
fi
"""

PRE_COMMIT_HOOK_SCRIPT = """#!/usr/bin/env python3
# Installed by Context Guard (cg init)
# Pre-commit gate: rejects commits touching more than threshold files outside protocol.
import json
import os
import subprocess
import sys
from datetime import datetime

DEFAULT_FILE_THRESHOLD = 2
BYPASS_LOG = ".context-guard/bypass.log"
GUARD_DIR = ".context-guard"


def repo_root():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    except Exception:
        return os.path.abspath(".")


def staged_files():
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only"], text=True
        )
        return [f for f in out.splitlines() if f.strip()]
    except Exception:
        return []


def manifest_paths(root):
    base = os.path.join(root, ".context-guard")
    paths = []
    changes_dir = os.path.join(base, "changes")
    if os.path.isdir(changes_dir):
        for entry in sorted(os.listdir(changes_dir)):
            if entry == "archive":
                continue
            candidate = os.path.join(changes_dir, entry, "manifest.json")
            if os.path.exists(candidate):
                paths.append(candidate)
    flat = os.path.join(base, "manifest.json")
    if os.path.exists(flat):
        paths.append(flat)
    return paths


def load_manifests(root):
    manifests = []
    for path in manifest_paths(root):
        try:
            with open(path) as f:
                manifests.append(json.load(f))
        except (OSError, ValueError):
            continue
    return manifests


def file_threshold(manifests):
    from_env = os.environ.get("CONTEXT_GUARD_FILE_THRESHOLD")
    if from_env is not None:
        try:
            return int(from_env)
        except ValueError:
            pass

    configured = []
    for manifest in manifests:
        value = manifest.get("hook", {}).get("file_threshold")
        try:
            configured.append(int(value))
        except (TypeError, ValueError):
            continue
    return min(configured) if configured else DEFAULT_FILE_THRESHOLD


def protocol_engaged(manifests):
    for manifest in manifests:
        txn = manifest.get("transaction", {})
        if manifest.get("completed_phases") or txn.get("txn_status") == "in_progress":
            return True
        phases = manifest.get("phases", [])
        if any(p.get("status") in ("in_progress", "completed") for p in phases):
            return True
    return False


def log_bypass(root, files, reason):
    path = os.path.join(root, ".context-guard")
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "bypass.log"), "a") as f:
        f.write(f"{datetime.now().isoformat()}|{reason}|files={len(files)}|{','.join(files)}\\n")


def main():
    root = repo_root()
    files = staged_files()
    manifests = load_manifests(root)

    threshold = file_threshold(manifests)
    if len(files) <= threshold:
        sys.exit(0)

    if protocol_engaged(manifests):
        sys.exit(0)

    if os.environ.get("CONTEXT_GUARD_BYPASS") == "1":
        reason = os.environ.get("CONTEXT_GUARD_BYPASS_REASON", "unspecified")
        log_bypass(root, files, reason)
        print(f"[context-guard] BYPASS recorded in {BYPASS_LOG}", file=sys.stderr)
        sys.exit(0)

    print(
        f"[context-guard] COMMIT REJECTED: {len(files)} files staged "
        f"(threshold={threshold}) with no phase engaged.\\n"
        f"  -> Start the protocol first: cg plan <requirement>, cg new <change> or cg begin --phase <PHASE>.\\n"
        f"  -> Escape hatch: CONTEXT_GUARD_BYPASS=1 CONTEXT_GUARD_BYPASS_REASON='...' git commit ...\\n",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
"""


def _detect_test_command(context):
    """Detect default test command based on repository files."""
    if os.path.isfile(os.path.join(context, "pyproject.toml")):
        try:
            with open(os.path.join(context, "pyproject.toml"), "r", encoding="utf-8") as f:
                content = f.read()
            if "pytest" in content:
                return "pytest"
        except Exception:
            pass
        return "python -m unittest discover -s tests"
    if os.path.isfile(os.path.join(context, "package.json")):
        return "npm test"
    if os.path.isfile(os.path.join(context, "Cargo.toml")):
        return "cargo test"
    if os.path.isfile(os.path.join(context, "go.mod")):
        return "go test ./..."
    return "pytest"


def build_contract_block(project_name, test_cmd=None, commit_types=None):
    """Build the AGENTS.md contract text wrapped in ownership markers."""
    test_command = test_cmd or "pytest"
    types = commit_types or DEFAULT_COMMIT_TYPES
    lines = [
        OWNERSHIP_MARKER_BEGIN,
        f"# {project_name} — Contributor & Agent Contract",
        "",
        "## Core Disciplines",
        "- **Language**: Code, comments, commit messages, and artifacts: **English**. Chat with human: user's preferred language.",
        f"- **Testing**: Run `{test_command}` before your first change and after each logical unit. Never leave the test suite red at a commit boundary.",
        f"- **Commits**: Atomic commits, one concern each, Conventional Commits: `{types}`.",
        "- **Dependencies**: No new dependencies without explicit human approval.",
        "- **TDD / Red-Green**: For bugfixes and new features, write the failing test first (RED), then implement the fix, then verify passing (GREEN).",
        "",
        "## Context Guard Protocol",
        "- **Governance**: All multi-step work is governed by Context Guard (`cg`). Never hand-edit state files in `.context-guard/`.",
        "- **Pipeline**: Strict `PLAN → EXECUTE → VERIFY → ARCHIVE` pipeline. Reference guides in `.context-guard/phases/`.",
        "- **Human Gate**: `cg approve` is required before entering `EXECUTE`. **Never run `cg approve` yourself** — ask the human for approval.",
        "- **Phases**: Work on exactly ONE phase per session. Never skip phases silently.",
        "- **Demonstrable Criteria**: Mark acceptance criteria only when demonstrably verified by tests or concrete command outputs.",
        "- **Verification**: Run `cg verify` to validate acceptance criteria and test suite health before phase completion.",
        "- **Stop on Ambiguity**: If a requirement or plan is ambiguous, STOP and ask the human instead of guessing.",
        OWNERSHIP_MARKER_END,
    ]
    return "\n".join(lines) + "\n"


def _update_agents_md(path, project_name, test_cmd=None, commit_types=None):
    """Create or update AGENTS.md while preserving any human modifications."""
    block = build_contract_block(project_name, test_cmd, commit_types)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(block)
        return "created"

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if OWNERSHIP_MARKER_BEGIN in content and OWNERSHIP_MARKER_END in content:
        start = content.index(OWNERSHIP_MARKER_BEGIN)
        end = content.index(OWNERSHIP_MARKER_END) + len(OWNERSHIP_MARKER_END)
        new_content = content[:start] + block.strip() + content[end:]
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return "updated"

    # AGENTS.md exists without markers: append the contract block cleanly
    separator = "\n\n" if not content.endswith("\n\n") else ""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content + separator + block)
    return "appended"


def _update_claude_md(path):
    """Write CLAUDE.md with @AGENTS.md if it does not already exist."""
    if os.path.exists(path):
        return "exists"
    with open(path, "w", encoding="utf-8") as f:
        f.write("@AGENTS.md\n")
    return "created"


def _install_git_hooks(context, no_hooks=False):
    """Install .githooks/commit-msg and .githooks/pre-commit, configuring core.hooksPath."""
    if no_hooks:
        return ["hooks skipped (--no-hooks)"]

    touched = []
    githooks_dir = os.path.join(context, ".githooks")
    os.makedirs(githooks_dir, exist_ok=True)

    commit_msg_path = os.path.join(githooks_dir, "commit-msg")
    with open(commit_msg_path, "w", encoding="utf-8") as f:
        f.write(COMMIT_MSG_HOOK_SCRIPT)
    os.chmod(commit_msg_path, 0o755)
    touched.append(".githooks/commit-msg")

    pre_commit_path = os.path.join(githooks_dir, "pre-commit")
    if not os.path.exists(pre_commit_path):
        with open(pre_commit_path, "w", encoding="utf-8") as f:
            f.write(PRE_COMMIT_HOOK_SCRIPT)
        os.chmod(pre_commit_path, 0o755)
        touched.append(".githooks/pre-commit")

    # Configure git core.hooksPath if inside a git repository
    try:
        git_dir = subprocess.check_output(
            ["git", "rev-parse", "--git-dir"], cwd=context, stderr=subprocess.DEVNULL, text=True
        ).strip()
        subprocess.run(
            ["git", "config", "core.hooksPath", ".githooks"],
            cwd=context, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        touched.append("git config core.hooksPath .githooks")
    except Exception:
        # Not a git repository yet, leave .githooks prepared
        pass

    return touched


def cmd_init(context=".", force=False, no_hooks=False, test_cmd=None, commit_types=None):
    """Initialize a repository under the Context Guard protocol.

    Idempotent, non-destructive, safe to rerun.
    """
    context_root = os.path.abspath(context)
    os.makedirs(context_root, exist_ok=True)
    project_name = os.path.basename(context_root)

    test_command = test_cmd or _detect_test_command(context_root)
    lines = [f"Initializing Context Guard in {context_root} ..."]
    touched = []

    # 1. AGENTS.md contract
    agents_path = os.path.join(context_root, "AGENTS.md")
    status = _update_agents_md(agents_path, project_name, test_command, commit_types)
    touched.append(f"AGENTS.md ({status})")
    lines.append(f"  -> AGENTS.md: {status}")

    # 2. CLAUDE.md link
    claude_path = os.path.join(context_root, "CLAUDE.md")
    c_status = _update_claude_md(claude_path)
    if c_status == "created":
        touched.append("CLAUDE.md")
        lines.append("  -> CLAUDE.md: created (@AGENTS.md)")
    else:
        lines.append("  -> CLAUDE.md: exists, preserved")

    # 3. .context-guard/ directory and reference phase documents
    cg_dir = os.path.join(context_root, ".context-guard")
    os.makedirs(os.path.join(cg_dir, "changes"), exist_ok=True)
    phases_written = materialise_phases(context_root)
    if phases_written:
        for p in phases_written:
            rel = os.path.relpath(p, context_root).replace(os.sep, "/")
            touched.append(rel)
        lines.append("  -> .context-guard/phases/: reference guides materialized")
    else:
        lines.append("  -> .context-guard/phases/: existing guides preserved")

    # 4. Git hooks
    hooks_touched = _install_git_hooks(context_root, no_hooks=no_hooks)
    touched.extend(hooks_touched)
    lines.append(f"  -> Git hooks: {', '.join(hooks_touched)}")

    # 5. Agent host rules
    if antigravity_detected() or os.path.isdir(os.path.join(context_root, ".agents")):
        ag_rules = materialise_antigravity_rule(context_root)
        if ag_rules:
            touched.extend([os.path.relpath(r, context_root).replace(os.sep, "/") for r in ag_rules])
            lines.append("  -> Antigravity: workspace rule installed (.agents/rules/context-guard.md)")

    if cursor_detected() or os.path.isdir(os.path.join(context_root, ".cursor")):
        cur_rules = materialise_cursor_rule(context_root)
        if cur_rules:
            touched.extend([os.path.relpath(r, context_root).replace(os.sep, "/") for r in cur_rules])
            lines.append("  -> Cursor: workspace rule installed (.cursor/rules/context-guard.mdc)")

    lines.append("")
    lines.append("Repository ready under Context Guard protocol.")
    lines.append("Next steps:")
    lines.append("  1. Review AGENTS.md conventions")
    lines.append("  2. Plan work with: cg plan \"<requirement>\"")
    lines.append("  3. Ask human to approve: cg approve")
    lines.append("  4. Execute with: cg begin")

    return CommandResult("\n".join(lines), EXIT_OK)
