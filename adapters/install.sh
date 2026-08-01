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
    echo "Usage: ./install.sh [target-project-dir] [--host claude|opencode|antigravity|all] [--with-mcp]"
    echo "Installs the context-guard adapters for Claude Code, OpenCode, and"
    echo "Antigravity, all per-project."
    echo "  --host <name>  Install only this host, regardless of detection."
    echo "                 One of: claude, opencode, antigravity, all (default: all)."
    echo "  --with-mcp     Also register the context-guard-mcp server for the"
    echo "                 hosts being installed. Optional: every adapter works"
    echo "                 completely without it — MCP is an alternative"
    echo "                 transport, not a requirement."
    echo "  --with-antigravity-hook"
    echo "                 Merge the PreToolUse deny hook for 'cg approve' into"
    echo "                 ~/.gemini/config/hooks.json. Optional hardening; touches"
    echo "                 user config, not the project, so it is opt-in."
}

TARGET_ARG="."
HOST="all"
WITH_MCP=0
WITH_ANTIGRAVITY_HOOK=0

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
        --with-mcp)
            WITH_MCP=1
            shift
            ;;
        --with-antigravity-hook)
            WITH_ANTIGRAVITY_HOOK=1
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
# The artifacts moved into the package as data (PLAN-2.1 F1). This script is
# the last consumer that still reads them off the repo tree; `cg setup` (F2)
# replaces it and resolves them through importlib.resources instead.
DATA_SRC="$REPO_DIR/context_guard/_data"
PHASES_SRC="$DATA_SRC/phases"
HOSTS_SRC="$DATA_SRC/hosts"

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

TOUCHED=()
record() { TOUCHED+=("$1"); }

echo "Installing context-guard adapters into $TARGET_DIR ..."

# 1. Claude Code: slash commands + phases, per project
if [[ "$install_claude" == "1" ]]; then
mkdir -p "$TARGET_DIR/.claude/commands" "$TARGET_DIR/.context-guard/phases"
cp "$HOSTS_SRC/claude-code/commands/"*.md "$TARGET_DIR/.claude/commands/"
cp "$PHASES_SRC/"*.md "$TARGET_DIR/.context-guard/phases/"
for f in "$HOSTS_SRC/claude-code/commands/"*.md; do
    record ".claude/commands/$(basename "$f")"
done
for f in "$PHASES_SRC/"*.md; do
    record ".context-guard/phases/$(basename "$f")"
done
echo "  -> Claude Code: commands in .claude/commands/, phases in .context-guard/phases/"

python3 - "$TARGET_DIR" "$HOSTS_SRC/claude-code/settings.snippet.json" <<'PY'
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
record ".claude/settings.json"
echo "  -> Claude Code: cg approve added to the ask list in .claude/settings.json"
echo "     (what that prompt does and does not guarantee: docs/adapters/claude-code/PERMISSIONS.md)"

if [[ "$WITH_MCP" == "1" ]]; then
    python3 - "$TARGET_DIR/.mcp.json" "$HOSTS_SRC/claude-code/mcp.snippet.json" <<'PY'
import json
import sys

config_path, snippet_path = sys.argv[1], sys.argv[2]
with open(snippet_path, "r", encoding="utf-8") as f:
    snippet = json.load(f)

try:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {}

servers = cfg.setdefault("mcpServers", {})
servers.setdefault("context-guard", snippet["mcpServers"]["context-guard"])

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PY
    record ".mcp.json"
    echo "  -> Claude Code: context-guard-mcp registered in .mcp.json"
fi
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
    cp "$HOSTS_SRC/opencode/commands/"*.md "$TARGET_DIR/.opencode/commands/"
    for f in "$HOSTS_SRC/opencode/commands/"*.md; do
        record ".opencode/commands/$(basename "$f")"
    done

    python3 - "$OPENCODE_CFG" "$HOSTS_SRC/opencode/agent.snippet.json" "$HOSTS_SRC/opencode/permissions.snippet.json" <<'PY'
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
        raw = re.sub(r"(?<!:)//.*?\n|/\*.*?\*/", "", f.read(), flags=re.S)
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
    record "opencode.json"
    if [[ "$WITH_MCP" == "1" ]]; then
        python3 - "$OPENCODE_CFG" "$HOSTS_SRC/opencode/mcp.snippet.json" <<'PY'
import json
import re
import sys

config_path, snippet_path = sys.argv[1], sys.argv[2]
with open(snippet_path, "r", encoding="utf-8") as f:
    snippet = json.load(f)

with open(config_path, "r", encoding="utf-8") as f:
    raw = re.sub(r"(?<!:)//.*?\n|/\*.*?\*/", "", f.read(), flags=re.S)
cfg = json.loads(raw)

servers = cfg.setdefault("mcp", {})
servers.setdefault("context-guard", snippet["mcp"]["context-guard"])

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PY
        echo "  -> OpenCode: context-guard-mcp registered in opencode.json"
    fi
    echo "  -> OpenCode: commands in .opencode/commands/, config merged into opencode.json"
    echo "     (permission setup, unverified against a real host: docs/adapters/opencode/PERMISSIONS.md)"
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
    cp "$HOSTS_SRC/antigravity/rules/context-guard.md" "$TARGET_DIR/.agents/rules/context-guard.md"
    record ".agents/rules/context-guard.md"
    echo "  -> Antigravity: rule installed at .agents/rules/context-guard.md"
    echo "     (permission setup, unverified against a real host: docs/adapters/antigravity/PERMISSIONS.md)"

    if [[ "$WITH_ANTIGRAVITY_HOOK" == "1" ]]; then
        ANTIGRAVITY_HOOKS_CFG="$HOME/.gemini/config/hooks.json"
        mkdir -p "$(dirname "$ANTIGRAVITY_HOOKS_CFG")"
        python3 - "$ANTIGRAVITY_HOOKS_CFG" "$HOSTS_SRC/antigravity/hooks.snippet.json" <<'PY'
import json
import sys

config_path, snippet_path = sys.argv[1], sys.argv[2]
with open(snippet_path, "r", encoding="utf-8") as f:
    snippet = json.load(f)
new_hook = snippet["hooks"]["PreToolUse"][0]

try:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {}

pre_tool_use = cfg.setdefault("hooks", {}).setdefault("PreToolUse", [])
already_present = any(
    h.get("matcher", {}).get("tool") == new_hook["matcher"]["tool"]
    and h.get("matcher", {}).get("commandPattern") == new_hook["matcher"]["commandPattern"]
    for h in pre_tool_use
)
if not already_present:
    pre_tool_use.append(new_hook)

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PY
        record "$ANTIGRAVITY_HOOKS_CFG (user config, not project)"
        echo "  -> Antigravity: deny hook merged into ~/.gemini/config/hooks.json"
    fi
elif [[ "$HOST" == "all" ]]; then
    echo "  -> Antigravity: not detected, skipped (pass FORCE_ANTIGRAVITY=1 or --host antigravity to install anyway)"
else
    echo "  -> Antigravity: skipped (--host $HOST)"
fi

echo ""
echo "Files touched:"
if [[ ${#TOUCHED[@]} -eq 0 ]]; then
    echo "  (none)"
else
    for f in "${TOUCHED[@]}"; do
        echo "  $f"
    done
fi
echo "Done."
