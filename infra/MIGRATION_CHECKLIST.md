# biz-prototypes 完全移行チェックリスト

## 事前確認

- `gcloud auth list` で Cloud Run / GCS / IAP を操作できるアカウントが active。
- `BIZ_PROTO_BUCKET` に private bucket 名を設定。
- `BIZ_PROTO_BASE_URL` に IAP 配信URLを設定。
- アユダンテの許可ドメインは `ayudante.jp`。
- Slack共有チャンネルは `#zm05_ayudante` (`C049FPP511Q`)。

## デプロイ

```bash
PROJECT_ID=ucarpac-uapp \
REGION=asia-northeast1 \
BIZ_PROTO_BUCKET=ucarpac-biz-prototypes-pages \
scripts/deploy_cloud_run.sh
```

## IAP設定

- Cloud Run viewer の前段に HTTPS Load Balancer + IAP を置く。
- IAP に `roles/iap.httpsResourceAccessor` を付与する。
  - `domain:ucarpac.co.jp`
  - `domain:ayudante.jp`
- GCS bucket は private のまま維持する。

## 動作確認

- 社内Googleアカウントで `/` が 200。
- アユダンテGoogleアカウントで `/agency/` が 200。
- アユダンテGoogleアカウントで `/reports/` が 403。
- 未認証アクセスが 401。
- `/auth.js` でパスワード入力が出ず、既存パンくずが維持される。
- `scripts/upload_share.py --scope agency` のURLがアユダンテで開ける。

## GitHub Pages停止

新URLの確認が完了してから実行する。

```bash
CONFIRM=disable-github-pages scripts/disable_github_pages.sh
```
