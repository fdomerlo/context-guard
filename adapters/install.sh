#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Context Guard: adapter installer (Claude Code / OpenCode / Antigravity)
# ============================================================================
# Pass the target project as the first positional argument, default is the
# current directory. All three hosts install per-project.
#
#   ./install.sh [target-project-dir] [--host claude|opencode|antigravity|all]
#
# --host all (the default) keeps the existing detect-and-skip behavior per
# host. Naming a single host installs it unconditionally — asking for it
# explicitly is itself the signal, so detection does not apply.

usage() {
    echo "Usage: ./install.sh [target-project-dir] [--host claude|opencode|antigravity|all]"
    echo "Installs the context-guard adapters for Claude Code, OpenCode, and"
    echo "Antigravity, all per-project."
    echo "  --host <name>  Install only this host, regardless of detection."
    echo "                 One of: claude, opencode, antigravity, all (default: all)."
}

TARGET_ARG="."
HOST="all"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            usage
            exit 0
            ;;
        --host)
            if [[ $# -lt 2 ]]; then
                echo "error: --host requires a value" >&2
                exit 1
            fi
            HOST="$2"
            shift 2
            ;;
        --host=*)
            HOST="${1#--host=}"
            shift
            ;;
        -*)
            echo "error: unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            TARGET_ARG="$1"
            shift
            ;;
    esac
done

case "$HOST" in
    claude|opencode|antigravity|all) ;;
    *)
        echo "error: invalid --host '$HOST' (expected claude|opencode|antigravity|all)" >&2
        exit 1
        ;;
esac

TARGET_DIR="$(cd "$TARGET_ARG" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
PHASES_SRC="$REPO_DIR/phases"

# A host installs if it was named explicitly, or if --host all left
# detection to decide. install_claude has no detection leg: Claude Code
# always installs under --host all, matching the pre-6.2 behavior.
install_claude=0
[[ "$HOST" == "claude" || "$HOST" == "all" ]] && install_claude=1

install_opencode=0
if [[ "$HOST" == "opencode" ]]; then
    install_opencode=1
elif [[ "$HOST" == "all" && ( -d "$HOME/.config/opencode" || "${FORCE_OPENCODE:-}" == "1" ) ]]; then
    install_opencode=1
fi

install_antigravity=0
if [[ "$HOST" == "antigravity" ]]; then
    install_antigravity=1
elif [[ "$HOST" == "all" && ( -d "$HOME/.gemini" || "${FORCE_ANTIGRAVITY:-}" == "1" ) ]]; then
    install_antigravity=1
fi

echo "Installing context-guard adapters into $TARGET_DIR ..."

# 1. Claude Code: slash commands + phases, per project
if [[ "$install_claude" == "1" ]]; then
mkdir -p "$TARGET_DIR/.claude/commands" "$TARGET_DIR/.context-guard/phases"
cp "$SCRIPT_DIR/claude-code/commands/"*.md "$TARGET_DIR/.claude/commands/"
cp "$PHASES_SRC/"*.md "$TARGET_DIR/.context-guard/phases/"
echo "  -> Claude Code: commands in .claude/commands/, phases in .context-guard/phases/"

python3 - "$TARGET_DIR" "$SCRIPT_DIR/claude-code/settings.snippet.json" <<'PY'
import json
import sys

target_dir, snippet_path = sys.argv[1], sys.argv[2]
settings_path = f"{target_dir}/.claude/settings.json"

with open(snippet_path, "r", encoding="utf-8") as f:
    snippet = json.load(f)
ask_new = snippet["permissions"]["ask"]
deny_new = snippet["permissions"].get("deny", [])

try:
    with open(settings_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {}

perms = cfg.setdefault("permissions", {})
ask = perms.setdefault("ask", [])
for entry in ask_new:
    if entry not in ask:
        ask.append(entry)
deny = perms.setdefault("deny", [])
for entry in deny_new:
    if entry not in deny:
        deny.append(entry)

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PY
echo "  -> Claude Code: cg approve added to the ask list in .claude/settings.json"
echo "     (what that prompt does and does not guarantee: adapters/claude-code/PERMISSIONS.md)"
else
    echo "  -> Claude Code: skipped (--host $HOST)"
fi

# 2. OpenCode: install per-project, mirroring Claude Code — commands and
# config both live in the target project, not in $HOME. The old per-user
# commands were generated pointing at this repo clone's own phases/
# directory (an absolute path that breaks the moment the clone moves) and
# merged into the host's global config instead of the project's.
OPENCODE_CFG="$TARGET_DIR/opencode.json"
if [[ "$install_opencode" == "1" ]]; then
    mkdir -p "$TARGET_DIR/.opencode/commands"
    cp "$SCRIPT_DIR/opencode/commands/"*.md "$TARGET_DIR/.opencode/commands/"

    python3 - "$OPENCODE_CFG" "$SCRIPT_DIR/opencode/agent.snippet.json" "$SCRIPT_DIR/opencode/permissions.snippet.json" <<'PY'
import json
import re
import sys

config_path, agent_snippet_path, permissions_snippet_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(agent_snippet_path, "r", encoding="utf-8") as f:
    agent_snippet = json.load(f)
with open(permissions_snippet_path, "r", encoding="utf-8") as f:
    permissions_snippet = json.load(f)

try:
    with open(config_path, "r", encoding="utf-8") as f:
        raw = re.sub(r"//.*?\n|/\*.*?\*/", "", f.read(), flags=re.S)
    cfg = json.loads(raw)
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {"$schema": "https://opencode.ai/config.json", "agent": {}}

cfg.setdefault("agent", {}).update(agent_snippet)

# Top-level "permission", not nested in the agent entry, so it applies
# regardless of which agent is running the command. Merged per-pattern so a
# pre-existing rule for a pattern we do not know about survives untouched,
# and re-running the installer never duplicates anything.
perm_cfg = cfg.setdefault("permission", {})
for category, rules in permissions_snippet.get("permission", {}).items():
    category_cfg = perm_cfg.setdefault(category, {})
    for pattern, mode in rules.items():
        category_cfg.setdefault(pattern, mode)

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PY
    echo "  -> OpenCode: commands in .opencode/commands/, config merged into opencode.json"
    echo "     (permission setup, unverified against a real host: adapters/opencode/PERMISSIONS.md)"
elif [[ "$HOST" == "all" ]]; then
    echo "  -> OpenCode: not detected, skipped (pass FORCE_OPENCODE=1 or --host opencode to install anyway)"
else
    echo "  -> OpenCode: skipped (--host $HOST)"
fi

# 3. Antigravity: install the rule file into the target project. The old
# approach injected the bootstrap block into the global ~/.gemini/GEMINI.md,
# which contaminated every project the user has with a control meant to
# apply to this one. The workspace rule file is read by IDE, CLI, and
# Manager alike, and travels with the repo instead of the user's machine.
if [[ "$install_antigravity" == "1" ]]; then
    mkdir -p "$TARGET_DIR/.agents/rules"
    cp "$SCRIPT_DIR/antigravity/rules/context-guard.md" "$TARGET_DIR/.agents/rules/context-guard.md"
    echo "  -> Antigravity: rule installed at .agents/rules/context-guard.md"
    echo "     (permission setup, unverified against a real host: adapters/antigravity/PERMISSIONS.md)"
elif [[ "$HOST" == "all" ]]; then
    echo "  -> Antigravity: not detected, skipped (pass FORCE_ANTIGRAVITY=1 or --host antigravity to install anyway)"
else
    echo "  -> Antigravity: skipped (--host $HOST)"
fi

echo "Done."
