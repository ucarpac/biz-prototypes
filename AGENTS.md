# AGENTS.md

このリポジトリは GitHub Pages で社内向けに静的配信する前提で運用する。
日々のプロトタイプと分析レポートを同じ Pages 配下で管理するため、追加時は以下のルールに従うこと。

## 目的

- `ucarpac-app/` は日々のプロトタイプ置き場
- `ops/` は継続更新される定点レポート置き場
- `reports/` は単発の分析レポート置き場

## ディレクトリルール

- ルートの `index.html` はハブ。`ucarpac-app/` と `reports/` への入口にする
- 単発レポートは `reports/<slug>/index.html` に置く
- `<slug>` は `topic-YYYYMMDD-random` の形式にする
- ランダム部分は 8 文字前後の英数字でよい
- 継続更新レポートは `ops/<name>/index.html` に置く

## 認証ルール

- 公開ページは共通の `auth.js` を読み込む
- 認証はクライアント側の簡易ゲートであり、機微情報の厳密保護用途ではない
- デフォルトは 24 時間保持とする
- ページごとのタイトルや説明は `window.PROTO_AUTH_CONFIG` で上書きする
- 新規 HTML を追加するときは、`auth.js` の相対パスが正しいか必ず確認する

## レポート追加ルール

- 既存 HTML を載せるときは、先頭に認証設定と `auth.js` を差し込む
- `Reports に戻る` リンクを追加する
- `reports/index.html` にカードを追加する
- 文字化けして見えても、PowerShell 表示由来の可能性があるため、`Select-String` で実ファイル内容を確認してから直す
- 内容解釈に誤解が出やすい指標は、公開前にラベルや注記で補正する

## GitHub Pages 運用ルール

- このリポは自動更新が多いため、作業開始時に最新 `origin/main` を基準にする
- すでにローカル `main` が古い場合は、そのまま積まずに最新 `origin/main` から作業ブランチを切る
- `main` へ反映する前に `git fetch origin` と `git rebase origin/main` を行い、fast-forward で push する
- 公開後は URL の HTTP ステータスが `200` かを確認する
- 追加ページは一覧ページと個別 URL の両方で反映確認する

## 確認項目

- `reports/index.html` または該当ハブに新規カードがある
- 対象ページで認証ゲートが有効
- 戻りリンクが機能する
- 公開 URL が `200`
- ページ本文に期待するタイトルや文言が含まれる
