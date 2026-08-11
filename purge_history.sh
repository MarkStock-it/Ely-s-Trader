# Purge history helper script

# WARNING: This script rewrites git history and force-pushes. Use only after backing up and understanding consequences.

set -euo pipefail

REPO_URL="https://github.com/MarkStock-it/Ely-s-Trader.git"
WORKDIR="Ely-s-Trader.git"
REMOVE_FILE_LIST="remove_paths.txt"

cat > "$REMOVE_FILE_LIST" <<'EOF'
.env
.env.*
.env.production
.env.local
credentials.json
secrets.yml
# add other paths you want removed from history, one per line
EOF

# Backup (mirror clone)
rm -rf "${WORKDIR}.backup"
git clone --mirror "$REPO_URL" "${WORKDIR}.backup"

# Work mirror
rm -rf "$WORKDIR"
git clone --mirror "$REPO_URL" "$WORKDIR"
cd "$WORKDIR"

# Run git-filter-repo to remove listed paths
if ! command -v git-filter-repo >/dev/null 2>&1; then
  echo "git-filter-repo not found; try: pip install git-filter-repo"
  exit 1
fi

# The --invert-paths flag removes the listed paths from history
git filter-repo --invert-paths --paths-from-file ../$REMOVE_FILE_LIST

# Optional: perform literal token replacement if you know specific tokens.
# See purge_history.sh README for replace-text format.

# Cleanup
git reflog expire --expire=now --all
git gc --prune=now --aggressive

echo "Verification: clone cleaned repo to ../Ely-s-Trader-clean and inspect"
cd ..
rm -rf Ely-s-Trader-clean
git clone "$WORKDIR" Ely-s-Trader-clean
cd Ely-s-Trader-clean

echo "Check for .env in history (should produce no results):"
git log --all --pretty=format:%H --name-only | grep -E '\.env' || echo "no .env references found"

# If verification is OK, force-push cleaned history back to GitHub
# WARNING: This will rewrite the remote history and require collaborators to re-clone.
read -p "Ready to force-push cleaned history to origin? (type YES to proceed) " CONFIRM
if [ "$CONFIRM" = "YES" ]; then
  cd ../$WORKDIR
  git push --force --all
  git push --force --tags
  echo "Push complete."
else
  echo "Aborting push. Cleaned mirror remains at $WORKDIR but nothing pushed."
fi
