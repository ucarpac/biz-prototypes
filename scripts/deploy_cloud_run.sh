#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_ID="${PROJECT_ID:-ucarpac-uapp}"
REGION="${REGION:-asia-northeast1}"
SERVICE="${SERVICE:-biz-prototypes-viewer}"
BUCKET="${BIZ_PROTO_BUCKET:-ucarpac-biz-prototypes-pages}"
BUCKET_LOCATION="${BUCKET_LOCATION:-ASIA-NORTHEAST1}"

cd "$ROOT_DIR"

gcloud config set project "$PROJECT_ID" >/dev/null

gcloud services enable \
  run.googleapis.com \
  storage.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  iap.googleapis.com

if ! gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BUCKET}" \
    --project "$PROJECT_ID" \
    --location "$BUCKET_LOCATION" \
    --uniform-bucket-level-access
fi

BIZ_PROTO_BUCKET="$BUCKET" scripts/sync_pages_to_gcs.sh

gcloud run deploy "$SERVICE" \
  --source cloud-run-viewer \
  --region "$REGION" \
  --no-allow-unauthenticated \
  --set-env-vars "BIZ_PROTO_BUCKET=${BUCKET},BIZ_PROTO_SHARE_INDEX=_config/share-index.json,BIZ_PROTO_STRIP_PREFIXES=/biz-prototypes/"

cat <<EOF

Cloud Run service was deployed.

Next required control-plane steps:
1. Put an HTTPS Load Balancer + IAP in front of this Cloud Run service, or enable native Cloud Run IAP if available in this project.
2. Grant roles/iap.httpsResourceAccessor to:
   - domain:ucarpac.co.jp
   - domain:ayudante.jp
3. Keep the bucket private. Do not grant allUsers/allAuthenticatedUsers on gs://${BUCKET}.
4. After the IAP URL is verified, disable GitHub Pages for ucarpac/biz-prototypes.
EOF
