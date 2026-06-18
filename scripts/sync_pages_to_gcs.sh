#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUCKET="${BIZ_PROTO_BUCKET:-${1:-}}"

if [[ -z "$BUCKET" ]]; then
  echo "BIZ_PROTO_BUCKET or first argument is required" >&2
  exit 2
fi

cd "$ROOT_DIR"

gcloud storage rsync . "gs://${BUCKET}" \
  --recursive \
  --delete-unmatched-destination-objects \
  --exclude '(^|/)(\.git|\.github|cloud-run-viewer|infra|scripts)(/|$)|(^|/)(README\.md|AGENTS\.md|\.gitignore|\.gcloudignore|gha-creds-[^/]+\.json)$'

gcloud storage cp infra/share-index.json "gs://${BUCKET}/_config/share-index.json"
