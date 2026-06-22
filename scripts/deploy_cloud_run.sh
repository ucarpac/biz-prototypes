#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_ID="${PROJECT_ID:-ucarpac-uapp}"
REGION="${REGION:-asia-northeast1}"
SERVICE="${SERVICE:-biz-prototypes-viewer}"
BUCKET="${BIZ_PROTO_BUCKET:-ucarpac-biz-prototypes-pages}"
BUCKET_LOCATION="${BUCKET_LOCATION:-ASIA-NORTHEAST1}"
ENABLE_SERVICES="${ENABLE_SERVICES:-0}"
CREATE_BUCKET="${CREATE_BUCKET:-0}"
USE_IAP="${USE_IAP:-1}"
CONFIGURE_IAP_ACCESS="${CONFIGURE_IAP_ACCESS:-1}"
IAP_MEMBERS="${IAP_MEMBERS:-domain:ucarpac.co.jp,domain:ayudante.jp}"

cd "$ROOT_DIR"

gcloud config set project "$PROJECT_ID" >/dev/null

if [[ "$ENABLE_SERVICES" == "1" ]]; then
  gcloud services enable \
    run.googleapis.com \
    storage.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    iap.googleapis.com
fi

if ! gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
  if [[ "$CREATE_BUCKET" != "1" ]]; then
    cat >&2 <<EOF
gs://${BUCKET} が存在しないか、このアカウントでは参照できません。
初回だけ CREATE_BUCKET=1 で作成するか、uniform bucket-level access 付きで手動作成してください。
EOF
    exit 2
  fi

  gcloud storage buckets create "gs://${BUCKET}" \
    --project "$PROJECT_ID" \
    --location "$BUCKET_LOCATION" \
    --uniform-bucket-level-access \
    --public-access-prevention
fi

BIZ_PROTO_BUCKET="$BUCKET" scripts/sync_pages_to_gcs.sh

deploy_args=(
  gcloud run deploy "$SERVICE"
  --source cloud-run-viewer \
  --region "$REGION" \
  --no-allow-unauthenticated \
  --set-env-vars "BIZ_PROTO_BUCKET=${BUCKET},BIZ_PROTO_SHARE_INDEX=_config/share-index.json,BIZ_PROTO_STRIP_PREFIXES=/biz-prototypes/"
)

if [[ -n "${BIZ_PROTO_GITHUB_TOKEN:-}" ]]; then
  deploy_args+=(--update-env-vars "BIZ_PROTO_GITHUB_TOKEN=${BIZ_PROTO_GITHUB_TOKEN}")
fi

if [[ "$USE_IAP" == "1" ]]; then
  deploy_args+=(--iap)
fi

"${deploy_args[@]}"

if [[ "$USE_IAP" == "1" ]]; then
  PROJECT_NUMBER="${PROJECT_NUMBER:-$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')}"

  gcloud run services add-iam-policy-binding "$SERVICE" \
    --region="$REGION" \
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com" \
    --role=roles/run.invoker

  if [[ "$CONFIGURE_IAP_ACCESS" == "1" ]]; then
    IFS=',' read -r -a members <<< "$IAP_MEMBERS"
    for member in "${members[@]}"; do
      member="$(echo "$member" | xargs)"
      if [[ -n "$member" ]]; then
        gcloud iap web add-iam-policy-binding \
          --member="$member" \
          --role=roles/iap.httpsResourceAccessor \
          --region="$REGION" \
          --resource-type=cloud-run \
          --service="$SERVICE"
      fi
    done
  fi
fi

SERVICE_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"

cat <<EOF

Cloud Run service was deployed.
Service URL: ${SERVICE_URL}

Required verification:
1. ${SERVICE} の IAP Enabled が true であること。
2. IAP access に次が含まれていること。
   - domain:ucarpac.co.jp
   - domain:ayudante.jp
3. gs://${BUCKET} は private のまま維持し、allUsers/allAuthenticatedUsers を付与しないこと。
4. 確認後、OpenClaw/html-share に BIZ_PROTO_BASE_URL=${SERVICE_URL} を設定すること。
5. IAP URL の確認後、ucarpac/biz-prototypes の GitHub Pages を停止すること。
EOF
