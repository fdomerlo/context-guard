#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# context-guard — Install Script (Antigravity CLI / Swarm Edition)
# Instala la skill en la ruta global ~/.agents/skills/ y el motor en bin/
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SKILL_SRC="$REPO_DIR/SKILL.md"
MANAGER_SRC="$SCRIPT_DIR/cg_manager.py"

# Standard Agent Skills Spec global path
SKILLS_DIR="$HOME/.agents/skills"
SKILL_DEST="$SKILLS_DIR/context-guard"
BIN_DEST="$SKILL_DEST/bin"

MARKER_BEGIN="<!-- context-guard:begin -->"
MARKER_END="<!-- context-guard:end -->"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
info() { echo -e "  ${CYAN}→${NC} $1"; }

[ -f "$SKILL_SRC" ] || { echo "Error: SKILL.md not found in $REPO_DIR"; exit 1; }
[ -f "$MANAGER_SRC" ] || { echo "Error: cg_manager.py not found in $SCRIPT_DIR"; exit 1; }

install_core() {
    info "Copiando archivos base..."
    mkdir -p "$BIN_DEST"
    cp "$SKILL_SRC" "$SKILL_DEST/"
    cp "$MANAGER_SRC" "$BIN_DEST/"
    chmod +x "$BIN_DEST/cg_manager.py"
    ok "Core y Middleware instalados en $SKILL_DEST"
}

# ---------------------------------------------------------------------------

install_antigravity() {
    install_core
    local gemini="$HOME/.gemini/GEMINI.md"
    
    info "Inyectando boot prompt en Antigravity ($gemini)..."
    mkdir -p "$(dirname "$gemini")"
    
    # Remover bloque viejo si existe
    if [ -f "$gemini" ] && grep -q "$MARKER_BEGIN" "$gemini"; then
        awk "/$MARKER_BEGIN/{flag=1} /$MARKER_END/{flag=0; next} !flag" "$gemini" > "${gemini}.tmp" && mv "${gemini}.tmp" "$gemini"
    fi
    
    echo -e "\n$MARKER_BEGIN" >> "$gemini"
    echo "## ACTIVE PERSISTENCE CONTRACT: context-guard" >> "$gemini"
    echo "MANDATORY BOOTSTRAP — execute before responding to anything:" >> "$gemini"
    echo "1. Call read_file on \`$SKILL_DEST/SKILL.md\`." >> "$gemini"
    echo "2. Follow every instruction in that file as your absolute state contract." >> "$gemini"
    echo "3. Check for an active context at \`.context-guard/active_session/manifest.json\`" >> "$gemini"
    echo "   and act accordingly (Cold Boot, Resume, or Recovery)." >> "$gemini"
    echo "$MARKER_END" >> "$gemini"
    
    ok "Integración con Antigravity CLI completada."
}

# ---------------------------------------------------------------------------

install_opencode() {
    install_core
    # OpenCode carga instrucciones globales desde AGENTS.md en su config dir,
    # de forma análoga a como Antigravity carga GEMINI.md.
    # Verificá esta ruta contra tu versión de opencode.json (campo "instructions")
    # antes de asumirla como definitiva.
    local agents_md="$HOME/.config/opencode/AGENTS.md"

    info "Inyectando boot prompt en OpenCode ($agents_md)..."
    mkdir -p "$(dirname "$agents_md")"

    if [ -f "$agents_md" ] && grep -q "$MARKER_BEGIN" "$agents_md"; then
        awk "/$MARKER_BEGIN/{flag=1} /$MARKER_END/{flag=0; next} !flag" "$agents_md" > "${agents_md}.tmp" && mv "${agents_md}.tmp" "$agents_md"
    fi

    {
        echo ""
        echo "$MARKER_BEGIN"
        echo "## ACTIVE PERSISTENCE CONTRACT: context-guard"
        echo "MANDATORY BOOTSTRAP — execute before responding to anything:"
        echo "1. Call read_file on \`$SKILL_DEST/SKILL.md\`."
        echo "2. Follow every instruction in that file as your absolute state contract."
        echo "3. Check for an active context at \`.context-guard/active_session/manifest.json\`"
        echo "   and act accordingly (Cold Boot, Resume, or Recovery)."
        echo "$MARKER_END"
    } >> "$agents_md"

    ok "Integración con OpenCode completada."
}

# ---------------------------------------------------------------------------

uninstall() {
    info "Desinstalando Context Guard..."
    rm -rf "$SKILL_DEST"
    ok "Archivos base eliminados."
    
    local gemini="$HOME/.gemini/GEMINI.md"
    if [ -f "$gemini" ] && grep -q "$MARKER_BEGIN" "$gemini"; then
        awk "/$MARKER_BEGIN/{flag=1} /$MARKER_END/{flag=0; next} !flag" "$gemini" > "${gemini}.tmp" && mv "${gemini}.tmp" "$gemini"
        ok "Prompt removido de GEMINI.md"
    fi
}

echo -e "\n${CYAN}${BOLD}Context Guard — Installer${NC}"
echo -e "  Skills path: $SKILL_DEST\n"

TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target)    TARGET="$2"; shift 2 ;;
    --uninstall) uninstall; exit 0 ;;
    *) echo "Usage: install.sh --target antigravity | --target opencode | --uninstall"; exit 1 ;;
  esac
done

if [ "$TARGET" == "antigravity" ]; then
    install_antigravity
elif [ "$TARGET" == "opencode" ]; then
    install_opencode
else
    echo "Por favor, especifica el target: bash scripts/install.sh --target antigravity | --target opencode"
fi