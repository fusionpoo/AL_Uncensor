#!/usr/bin/env bash
# One-time publish of this repo to GitHub, including the Release with the zip and GitHub Pages from docs/.
# Needs: git, GitHub CLI logged in (gh auth login). Run from inside the repo folder.
#   ./publish.sh <your-github-username> [version]
set -euo pipefail
USER=${1:?github username}; VER=${2:-0.9.1}; REPO=AL_Uncensor
# fill in the username in README and docs links
sed -i "s/__GH_USER__/$USER/g" README.md docs/index.html
git init -q 2>/dev/null || true; git add -A; git commit -qm "$REPO $VER" || true; git branch -M main
gh repo create "$USER/$REPO" --public --source=. --remote=origin --push --description "Uncensor mod for Amanatsu Location (BepInEx 6 IL2CPP)"
# GitHub Pages from the docs/ folder on main
gh api -X POST "repos/$USER/$REPO/pages" -f "source[branch]=main" -f "source[path]=/docs" >/dev/null && echo "Pages: https://$USER.github.io/$REPO/"
# Release with the installable zip
gh release create "v$VER" dist/AL_Uncensor_${VER}.zip --title "$REPO $VER" --notes-file CHANGELOG.md
echo "done: https://github.com/$USER/$REPO"
