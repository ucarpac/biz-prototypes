# biz-prototypes 完全移行チェックリスト

## 事前確認

- `gcloud auth list` で Cloud Run / GCS / IAP を操作できるアカウントが active。
- `BIZ_PROTO_BUCKET` に private bucket 名を設定。
- `BIZ_PROTO_BASE_URL` に IAP 配信URLを設定。
- アユダンテの許可ドメインは `ayudante.jp`。
- Slack共有チャンネルは `#zm05_ayudante` (`C049FPP511Q`)。
- GCS bucket をActionsで作成する場合は `BIZ_PROTO_CREATE_BUCKET=1` を設定する。
- private GCS 自動同期を開始するタイミングで `BIZ_PROTO_SYNC_ENABLED=1` を設定する。
- GitHub Actions のサービスアカウントは `github-push-dashboard@ucarpac-uapp.iam.gserviceaccount.com`。

## 初回GCP権限

Cloud Run へ IAP を直接付ける。HTTPS Load Balancer は使わない。

初回だけ、次のどちらかで進める。

### A. GitHub Actionsで初回作成まで実行

`github-push-dashboard@ucarpac-uapp.iam.gserviceaccount.com` に、少なくとも以下を付与する。

- `roles/run.admin`
- `roles/iap.admin`
- `roles/iap.settingsAdmin`
- `roles/oauthconfig.editor`
- `roles/iam.serviceAccountUser`
- `roles/cloudbuild.builds.editor`
- `roles/artifactregistry.admin`
- `roles/storage.admin`

API未有効の場合は `ENABLE_SERVICES=1` も使うため、追加で `roles/serviceusage.serviceUsageAdmin` が必要。

### B. 管理者がバケットだけ作成

管理者が `gs://ucarpac-biz-prototypes-pages` を `uniform bucket-level access` / `public access prevention` で作成する。

その後、同サービスアカウントへバケット単位で `roles/storage.admin` を付与し、デプロイ時は `CREATE_BUCKET=0` のまま実行する。

## デプロイ

```bash
PROJECT_ID=ucarpac-uapp \
REGION=asia-northeast1 \
BIZ_PROTO_BUCKET=ucarpac-biz-prototypes-pages \
scripts/deploy_cloud_run.sh
```

GitHub Actionsでバケット作成まで行う場合だけ、`BIZ_PROTO_CREATE_BUCKET=1` を repo variable に設定する。
バケット作成と初回同期が通るまでは `BIZ_PROTO_SYNC_ENABLED` を未設定または `0` のままにする。

## IAP設定

- Cloud Run viewer は direct IAP で保護する。
- Cloud Run invoker に IAP service agent を付与する。
- IAP に `roles/iap.httpsResourceAccessor` を付与する。
  - `domain:ucarpac.co.jp`
  - `domain:ayudante.jp`
- GCS bucket は private のまま維持する。
- アユダンテは外部Google Workspaceドメインなので、初回は Cloud Run の Security 画面で外部向け OAuth 設定が必要になる場合がある。

## 動作確認

- 社内Googleアカウントで `/` が 200。
- アユダンテGoogleアカウントで `/agency/` が 200。
- アユダンテGoogleアカウントで `/reports/` が 403。
- 未認証アクセスが 401。
- `/auth.js` でパスワード入力が出ず、既存パンくずが維持される。
- `scripts/upload_share.py --scope agency` のURLがアユダンテで開ける。
- GitHub Actions `sync-private-pages` が success。
- GitHub Actions `deploy-cloud-run-viewer` が success。

## GitHub Pages停止

新URLの確認が完了してから実行する。

```bash
CONFIRM=disable-github-pages scripts/disable_github_pages.sh
```
