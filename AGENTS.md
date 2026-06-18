# AGENTS.md

このリポジトリは private GCS + Cloud Run + IAP で社内/代理店向けに静的配信する前提で運用する。
日々のプロトタイプと分析レポートを同じ配信基盤で管理するため、追加時は以下のルールに従うこと。

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
- 認証の正は Cloud Run + IAP のGoogle認証とし、`auth.js` は既存ページの表示制御互換に使う
- 社内は `ucarpac.co.jp`、アユダンテ共有は `ayudante.jp` を許可ドメインとする
- デフォルトは 24 時間保持とする
- ページごとのタイトルや説明は `window.PROTO_AUTH_CONFIG` で上書きする
- 新規 HTML を追加するときは、`auth.js` の相対パスが正しいか必ず確認する

## 社内 / 代理店の置き分けルール

- `full`（社内）は全ページ閲覧可。`agency`（代理店）は共有指定ページのみ
- 代理店共有にするには、`infra/share-index.json` の `rules` に対象 prefix を追加する
- 既存表示制御との互換として、ページ単位で `required:"agency"` を付けるか、
  `auth.js` の `AGENCY_PATH_PREFIXES` に同じパスを追加する
- 代理店共有にしたら必ず `agency/index.html` にカードを追加（許可とハブ掲載はセット）
- 代理店ユーザーのパンくずは自動で `← 代理店ハブ` 起点になる（社内導線は見せない）。
  社内専用ページへの手書きリンクを代理店共有ページに置かないこと

## ナビゲーション（戻りリンク）ルール

- 戻りリンク（パンくず）は `auth.js` が URL から**自動生成**する。各ページに手書きしない
- ページ作成者は `auth.js` を読み込み、`PROTO_AUTH_CONFIG.title` にページ名を入れるだけ
- 手書きの「戻る／Hub」リンクは置かない（auth.js の自動パンくずと二重表示になる）
- 新セクション／カテゴリを足したら `auth.js` の `SECTION_LABELS` / `SUBSECTION_LABELS` にラベルを追加する

## レポート追加ルール

- 既存 HTML を載せるときは、先頭に認証設定と `auth.js` を差し込む
- `PROTO_AUTH_CONFIG.title` を設定する（パンくず末尾に出る）
- `reports/index.html` にカードを追加する
- 文字化けして見えても、PowerShell 表示由来の可能性があるため、`Select-String` で実ファイル内容を確認してから直す
- 内容解釈に誤解が出やすい指標は、公開前にラベルや注記で補正する

## Cloud Run/IAP 運用ルール

- このリポは自動更新が多いため、作業開始時に最新 `origin/main` を基準にする
- すでにローカル `main` が古い場合は、そのまま積まずに最新 `origin/main` から作業ブランチを切る
- `main` へ反映する前に `git fetch origin` と `git rebase origin/main` を行い、fast-forward で push する
- 反映後は private GCS 同期と Cloud Run/IAP 配信URLの HTTP ステータスが期待通りかを確認する
- GCS bucket は private のままにし、`allUsers` / `allAuthenticatedUsers` を付けない
- 追加ページは一覧ページと個別 URL の両方で反映確認する

## 確認項目

- `reports/index.html` または該当ハブに新規カードがある
- 対象ページで認証ゲートが有効
- 自動生成パンくずの Hub・セクションリンクが機能する（手書きの戻りリンクを足していない）
- 公開 URL が `200`
- ページ本文に期待するタイトルや文言が含まれる
