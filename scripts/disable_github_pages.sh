#!/usr/bin/env bash
set -euo pipefail

REPO="${REPO:-ucarpac/biz-prototypes}"
CONFIRM="${CONFIRM:-}"

if [[ "$CONFIRM" != "disable-github-pages" ]]; then
  echo "Refusing to disable GitHub Pages without CONFIRM=disable-github-pages" >&2
  exit 2
fi

gh api -X DELETE "repos/${REPO}/pages"
echo "GitHub Pages disabled for ${REPO}"
