#!/usr/bin/env bash
# Publish this repo to GitHub using a token YOU supply via $GH_TOKEN.
# The token is read from the environment only — never hard-coded, never echoed,
# never written into the git remote URL or config. Idempotent: creates the repo
# if missing, otherwise just pushes.
#
# Per the access policy, a human pulls the token; this script consumes it:
#   GH_TOKEN="$(ssh -i ~/.ssh/k root@10.13.0.50 \
#       'pct exec 100 -- /usr/local/bin/vault-get "<github item>"')" \
#     ./packaging/publish.sh
#
# Or simplest of all, with the GitHub CLI and no raw token:
#   gh repo create AkuchiS/yap --private --source=. --remote=origin --push
set -euo pipefail

OWNER="${YAP_GH_OWNER:-AkuchiS}"
REPO="${YAP_GH_REPO:-yap}"
PRIVATE="${YAP_GH_PRIVATE:-true}"

: "${GH_TOKEN:=${1:-}}"
if [ -z "${GH_TOKEN:-}" ]; then
  echo "Set GH_TOKEN in the environment (do not paste it into chat)." >&2
  exit 1
fi
export GH_TOKEN

ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
[ -d .git ] || { echo "Not a git repository: $ROOT" >&2; exit 1; }

# 1. Create the repo if it doesn't exist yet (HTTP 404 => create).
code="$(curl -fsS -o /dev/null -w '%{http_code}' \
  -H "Authorization: token $GH_TOKEN" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$OWNER/$REPO" || true)"
if [ "$code" = "404" ]; then
  echo "Creating $OWNER/$REPO (private=$PRIVATE)…"
  curl -fsS -o /dev/null \
    -H "Authorization: token $GH_TOKEN" -H "Accept: application/vnd.github+json" \
    https://api.github.com/user/repos \
    -d "{\"name\":\"$REPO\",\"private\":$PRIVATE}"
else
  echo "$OWNER/$REPO already exists (HTTP $code) — pushing to it."
fi

# 2. Push. The credential helper echoes the token from the env at request time,
#    so it never touches the remote URL, git config, or shell history. $OWNER is
#    expanded now by this shell; \$GH_TOKEN stays literal for the helper subshell
#    (which inherits the exported GH_TOKEN).
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/$OWNER/$REPO.git"
git branch -M main
git -c credential.helper="!f(){ echo username=$OWNER; echo password=\$GH_TOKEN; }; f" \
    push -u origin main

echo "✓ published → https://github.com/$OWNER/$REPO"
