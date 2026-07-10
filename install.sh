#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# context-guard — Install Script
# Instala la skill en la ruta global ~/.agents/skills/ y el motor en scripts/
# Soporta targets: antigravity, opencode. Sin --target, instala en ambos.
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$SCRIPT_DIR"
SKILL_SRC="$REPO_DIR/SKILL.md"
SKILL_SLIM_SRC="$REPO_DIR/SKILL-slim.md"
REFERENCES_SRC="$REPO_DIR/references"
GUARD_SHIM="$REPO_DIR/scripts/guard.py"
GUARD_PKG="$REPO_DIR/scripts/guard"

SKILLS_DIR="$HOME/.agents/skills"
SKILL_DEST="$SKILLS_DIR/context-guard"
SCRIPTS_DEST="$SKILL_DEST/scripts"
REFERENCES_DEST="$SKILL_DEST/references"

MARKER_BEGIN="<!-- context-guard:begin -->"
MARKER_END="<!-- context-guard:end -->"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
info() { echo -e "  ${CYAN}→${NC} $1"; }

[ -f "$SKILL_SRC" ] || { echo "Error: SKILL.md not found in $REPO_DIR"; exit 1; }
[ -f "$GUARD_SHIM" ] || { echo "Error: guard.py not found in $REPO_DIR/scripts"; exit 1; }
[ -d "$GUARD_PKG" ] || { echo "Error: guard/ package not found in $REPO_DIR/scripts"; exit 1; }

# ---------------------------------------------------------------------------
# Core installation — shared por todos los targets
# ---------------------------------------------------------------------------

install_core() {
    local profile="${1:-full}"
    info "Copiando archivos base (profile: $profile)..."
    mkdir -p "$SCRIPTS_DEST"

    if [ "$profile" == "slim" ]; then
        if [ ! -f "$SKILL_SLIM_SRC" ]; then
            echo "Error: SKILL-slim.md not found in $REPO_DIR"; exit 1
        fi
        cp "$SKILL_SLIM_SRC" "$SKILL_DEST/SKILL.md"
        ok "Perfil slim instalado (SKILL-slim.md → SKILL.md)"
    else
        cp "$SKILL_SRC" "$SKILL_DEST/"
        if [ -d "$REFERENCES_SRC" ]; then
            mkdir -p "$REFERENCES_DEST"
            cp -r "$REFERENCES_SRC"/* "$REFERENCES_DEST/"
            ok "Referencias copiadas a $REFERENCES_DEST"
        fi
    fi

    cp "$GUARD_SHIM" "$SCRIPTS_DEST/"
    cp -r "$GUARD_PKG" "$SCRIPTS_DEST/"
    chmod +x "$SCRIPTS_DEST/guard.py"

    ok "Core y Middleware instalados en $SKILL_DEST"
}

# ---------------------------------------------------------------------------
# Boot prompt injection — lógica común
# ---------------------------------------------------------------------------

inject_boot_prompt() {
    local target_file="$1"
    local target_name="$2"

    info "Inyectando boot prompt en $target_name ($target_file)..."
    mkdir -p "$(dirname "$target_file")"

    if [ -f "$target_file" ] && grep -q "$MARKER_BEGIN" "$target_file"; then
        awk "/$MARKER_BEGIN/{flag=1} /$MARKER_END/{flag=0; next} !flag" "$target_file" > "${target_file}.tmp" && mv "${target_file}.tmp" "$target_file"
    fi

    {
        echo ""
        echo "$MARKER_BEGIN"
        echo "## ACTIVE PERSISTENCE CONTRACT: context-guard"
        echo "MANDATORY BOOTSTRAP — execute before responding to anything:"
        echo "1. Call read_file on \`$SKILL_DEST/SKILL.md\`."
        echo "2. Follow every instruction in that file as your absolute state contract."
        echo "3. Check for an active context at \`.context-guard/sessions/{context}/manifest.json\`"
        echo "4. Act accordingly to the context state (Cold Boot, Resume, or Recovery)."
        echo "$MARKER_END"
    } >> "$target_file"

    ok "Integración con $target_name completada."
}

install_antigravity_hook() {
    inject_boot_prompt "$HOME/.gemini/GEMINI.md" "Antigravity"
}

install_opencode_hook() {
    inject_boot_prompt "$HOME/.config/opencode/AGENTS.md" "OpenCode"
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

uninstall() {
    local target="$1"
    info "Desinstalando Context Guard..."
    rm -rf "$SKILL_DEST"
    ok "Archivos base eliminados de $SKILL_DEST."

    local gemini="$HOME/.gemini/GEMINI.md"
    local agents_md="$HOME/.config/opencode/AGENTS.md"

    if [ "$target" == "antigravity" ] || [ -z "$target" ]; then
        if [ -f "$gemini" ] && grep -q "$MARKER_BEGIN" "$gemini"; then
            awk "/$MARKER_BEGIN/{flag=1} /$MARKER_END/{flag=0; next} !flag" "$gemini" > "${gemini}.tmp" && mv "${gemini}.tmp" "$gemini"
            ok "Prompt removido de GEMINI.md"
        fi
    fi

    if [ "$target" == "opencode" ] || [ -z "$target" ]; then
        if [ -f "$agents_md" ] && grep -q "$MARKER_BEGIN" "$agents_md"; then
            awk "/$MARKER_BEGIN/{flag=1} /$MARKER_END/{flag=0; next} !flag" "$agents_md" > "${agents_md}.tmp" && mv "${agents_md}.tmp" "$agents_md"
            ok "Prompt removido de AGENTS.md"
        fi
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

echo -e "\n${CYAN}${BOLD}Context Guard — Installer${NC}"
echo -e "  Skills path: $SKILL_DEST\n"

TARGET=""
PROFILE="full"
UNINSTALL=false
while [ $# -gt 0 ]; do
  case "$1" in
    --target)    TARGET="$2"; shift 2 ;;
    --profile)   PROFILE="$2"; shift 2 ;;
    --uninstall) UNINSTALL=true; shift 1 ;;
    *) echo "Usage: install.sh [--target antigravity|opencode] [--profile full|slim] | --uninstall [--target ...]"; exit 1 ;;
  esac
done

if [ "$UNINSTALL" == "true" ]; then
    uninstall "$TARGET"
    exit 0
fi

install_core "$PROFILE"

if [ "$TARGET" == "antigravity" ]; then
    install_antigravity_hook
elif [ "$TARGET" == "opencode" ]; then
    install_opencode_hook
elif [ -n "$TARGET" ]; then
    echo "Target no soportado: $TARGET"
    exit 1
else
    info "Sin --target especificado: instalando ambos canales."
    install_antigravity_hook
    install_opencode_hook
fi