# Cloud Run Viewer

`biz-prototypes` の GitHub Pages 配信を、private GCS + Cloud Run + IAP に移すための viewer です。

## 認証

- Cloud Run/IAP が付与する `X-Goog-Authenticated-User-Email` を信頼します。
- 社内は `ucarpac.co.jp` を `full` として扱います。
- 代理店共有は `ayudante.jp` を `agency` として扱います。
- 既存の `auth.js` は残しつつ、Cloud Run 配信時だけ認証済み state を注入して、パスワード入力を省略します。

## 共有ルール

`infra/share-index.json` を GCS の `_config/share-index.json` に置きます。

- `agency/`
- `ops/auto-kpi/`
- `reports/ai-inflow-20260331-n6x3p8r4k2/`
- `shares/ayudante/`

上記はアユダンテ向けに許可します。それ以外は社内のみです。

## ローカル確認

```bash
cd cloud-run-viewer
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
BIZ_PROTO_LOCAL_ROOT=.. BIZ_PROTO_LOCAL_AUTH_EMAIL=yabe@ucarpac.co.jp flask --app main run
```
