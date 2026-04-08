# biz-prototypes

GitHub Pages で配信する UcarPAC の社内共有ハブです。
日々のプロトタイプと分析レポートを分けて管理します。

## 構成

- `index.html`
  - ハブページ
- `auth.js`
  - 共通の簡易認証ゲート
- `ucarpac-app/`
  - 日々のプロトタイプ
- `ops/`
  - 継続更新の定点レポート
- `reports/`
  - 単発の分析レポート

## 公開 URL

- Hub: `https://ucarpac.github.io/biz-prototypes/`
- Reports: `https://ucarpac.github.io/biz-prototypes/reports/`
- Auto KPI: `https://ucarpac.github.io/biz-prototypes/ops/auto-kpi/`

## 新しいレポートを追加するとき

1. `reports/<slug>/index.html` を作る
2. ページ先頭に `window.PROTO_AUTH_CONFIG` と `auth.js` を入れる
3. `Reports に戻る` リンクを置く
4. `reports/index.html` にカードを追加する
5. `git fetch origin` 後に最新 `origin/main` 基準で反映する
6. 公開 URL が `200` かと、一覧から辿れるかを確認する

## 認証について

- `auth.js` は簡易なクライアント側認証です
- 認証状態は 24 時間保持します
- 厳密な秘匿用途ではなく、社内共有を前提にしています

詳細ルールは `AGENTS.md` を参照してください。
