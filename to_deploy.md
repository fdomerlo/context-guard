# 1. Commitear el bump de versión (usando bypass por ser > 2 archivos fuera de tx)
git add pyproject.toml CHANGELOG.md tests/test_release.py
CONTEXT_GUARD_BYPASS=1 CONTEXT_GUARD_BYPASS_REASON="bump version to 2.7.0" git commit -m "chore(release): bump version to 2.7.0"

# 2. Pushear a main
git push origin main

# 3. Crear el tag y release v2.7.0 en GitHub (o vía gh CLI) para que dispare publish.yml:
gh release create v2.7.0 --title "v2.7.0" --notes "Release 2.7.0"