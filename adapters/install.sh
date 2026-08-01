#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Context Guard: adapter installer (Claude Code / OpenCode / Antigravity)
# ============================================================================
# Pass the target project as the first argument, default is the current
# directory. All three hosts install per-project.

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: ./install.sh [target-project-dir]"
    echo "Installs the context-guard adapters for Claude Code, OpenCode, and"
    echo "Antigravity, all per-project."
    exit 0
fi

TARGET_DIR="$(cd "${1:-.}" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
PHASES_SRC="$REPO_DIR/phases"

echo "Installing context-guard adapters into $TARGET_DIR ..."

# 1. Claude Code: slash commands + phases, per project
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

# 2. OpenCode: install per-project, mirroring Claude Code — commands and
# config both live in the target project, not in $HOME. The old per-user
# commands were generated pointing at this repo clone's own phases/
# directory (an absolute path that breaks the moment the clone moves) and
# merged into the host's global config instead of the project's.
OPENCODE_CFG="$TARGET_DIR/opencode.json"
if [[ -d "$HOME/.config/opencode" || "${FORCE_OPENCODE:-}" == "1" ]]; then
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
else
    echo "  -> OpenCode: no ~/.config/opencode found, skipped (pass FORCE_OPENCODE=1 to install anyway)"
fi

# 3. Antigravity: install the rule file into the target project. The old
# approach injected the bootstrap block into the global ~/.gemini/GEMINI.md,
# which contaminated every project the user has with a control meant to
# apply to this one. The workspace rule file is read by IDE, CLI, and
# Manager alike, and travels with the repo instead of the user's machine.
if [[ -d "$HOME/.gemini" || "${FORCE_ANTIGRAVITY:-}" == "1" ]]; then
    mkdir -p "$TARGET_DIR/.agents/rules"
    cp "$SCRIPT_DIR/antigravity/rules/context-guard.md" "$TARGET_DIR/.agents/rules/context-guard.md"
    echo "  -> Antigravity: rule installed at .agents/rules/context-guard.md"
    echo "     (permission setup, unverified against a real host: adapters/antigravity/PERMISSIONS.md)"
else
    echo "  -> Antigravity: no ~/.gemini found, skipped (pass FORCE_ANTIGRAVITY=1 to install anyway)"
fi

echo "Done."
