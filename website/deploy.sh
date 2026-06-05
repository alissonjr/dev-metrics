#!/usr/bin/env bash
#
# Publica o site no GitHub Pages SEM pipeline (modo "deploy from a branch").
# Builda website/dist localmente e faz force-push para a branch gh-pages,
# com um .nojekyll na raiz (senão o Jekyll do Pages descarta a pasta _astro/).
#
# Uso:  bash website/deploy.sh
#
# Pre-requisito (uma vez): em Settings > Pages, deixar
#   Source = "Deploy from a branch", Branch = gh-pages, pasta = / (root).
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/website/dist"
REMOTE="$(git -C "$ROOT" remote get-url origin)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> build"
( cd "$ROOT/website" && npm ci && npm run build )

echo "==> publica em gh-pages"
cp -a "$DIST/." "$TMP/"
touch "$TMP/.nojekyll"
cd "$TMP"
git init -q
git checkout -q -b gh-pages
git add -A
git commit -q -m "deploy: site estatico ($(date -u '+%Y-%m-%d %H:%MZ'))"
git remote add origin "$REMOTE"
git push -f origin gh-pages

echo "==> publicado: https://alissonjr.github.io/dev-metrics/"
