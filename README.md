# biz-prototypes

GitHub Pages で配信する UcarPAC の社内共有ハブです。
日々のプロトタイプ・分析レポート・運用監視レポートを UCP 内部と代理店共有で管理します。

---

## サイトマップ

```
/                          ← TOP ハブ（全セクションへの入口）
├── ucarpac-app/           ← App プロトタイプ一覧（自動生成 + 手動作成）
│   ├── index.html         ← 一覧ページ（フィルター・日付別グループ）
│   ├── app-enhancement/
│   │   └── prototype/     ← 手動設計プロトタイプ（v1〜v4 + 統合ビュー）
│   │       ├── index-all.html   ← 統合ビュー（メインリンク先）
│   │       ├── index.html       ← v1
│   │       ├── v2-lifecycle.html
│   │       ├── v3-refined.html
│   │       └── v4-final.html
│   ├── 01-price-graph.html      ← 手動作成プロトタイプ群
│   ├── codex-*.html             ← Codex 自動生成プロトタイプ群
│   └── claude-*.html            ← Claude 自動生成プロトタイプ群
├── reports/               ← 単発分析レポート（UCP 内部向け）
│   └── <slug>/index.html
├── ops/                   ← 継続監視レポート（自動更新）
│   ├── index.html         ← ops ハブ
│   ├── auto-kpi/          ← 週次 KPI ダッシュボード
│   ├── competitor-watch/  ← 競合定点観測
│   └── appsflyer/         ← AppsFlyer アトリビューション
└── agency/                ← 代理店共有ハブ（agency パスワードでアクセス可）
```

## 公開 URL

| 対象 | URL |
|------|-----|
| TOP ハブ | `https://ucarpac.github.io/biz-prototypes/` |
| App プロトタイプ一覧 | `https://ucarpac.github.io/biz-prototypes/ucarpac-app/` |
| App Enhancement 統合ビュー | `https://ucarpac.github.io/biz-prototypes/ucarpac-app/app-enhancement/prototype/index-all.html` |
| 運用監視ハブ | `https://ucarpac.github.io/biz-prototypes/ops/` |
| Auto KPI | `https://ucarpac.github.io/biz-prototypes/ops/auto-kpi/` |
| 競合ウォッチ | `https://ucarpac.github.io/biz-prototypes/ops/competitor-watch/` |
| 分析レポート一覧 | `https://ucarpac.github.io/biz-prototypes/reports/` |
| 代理店共有ハブ | `https://ucarpac.github.io/biz-prototypes/agency/` |

---

## 認証の仕組み（auth.js）

`auth.js` はクライアントサイドの SHA-256 パスワードゲートです。認証状態は 24 時間 localStorage に保持されます。

| レベル | パスワード | 閲覧できるページ |
|--------|-----------|----------------|
| `full` | ucarpac2026 | 全ページ（UCP 社内向け） |
| `agency` | agency2026 | 代理店共有に指定したページのみ |

### 社内 / 代理店の置き分け（レポートを代理店共有にする）

レポートを代理店から見えるようにするには、次のどちらか：

1. **ページ単位**: そのページの `PROTO_AUTH_CONFIG` に `required: "agency"` を付ける
2. **パス一括**: `auth.js` 冒頭の `AGENCY_PATH_PREFIXES` にパスを追加（config を触らず共有可。
   自動生成レポートや「社内 Reports と代理店ハブの両方に出すレポート」向け）

そのうえで **`agency/index.html` にカードを追加**します（アクセス許可とハブ掲載は必ずセット）。
現状 `ops/auto-kpi/` と `reports/ai-inflow-...` は `AGENCY_PATH_PREFIXES` で共有しています。

各ページの `<head>` 末尾に以下を挿入します：

```html
<script>
  window.PROTO_AUTH_CONFIG = {
    title: "ページタイトル",
    subtitle: "説明文",
    required: "agency"   // 省略または "full" で UCP のみ閲覧可
  };
</script>
<script src="../../auth.js"></script>  <!-- パスは階層に合わせる -->
```

### auth.js のパス（階層別）

| ファイルの場所 | auth.js の src |
|--------------|----------------|
| ルート直下 | `./auth.js` |
| `ucarpac-app/` | `../auth.js` |
| `reports/<slug>/` | `../../auth.js` |
| `ops/auto-kpi/` | `../../auth.js` |
| `ucarpac-app/app-enhancement/prototype/` | `../../../auth.js` |

---

## ナビゲーション（Hub 戻りリンク）

**戻りリンク（パンくず）は `auth.js` が自動生成します。各ページに手書きしないでください。**

`auth.js` は現在の URL とリポジトリのベースパス（`/biz-prototypes/`）から
`← Hub / セクション / 現在ページ` を**絶対リンク**で生成します。
絶対リンクなので、ファイルがどの階層にあってもリンクは壊れません
（従来は `../../../` の階層数を間違えてリンク切れが多発していました。これを構造的に解消しています）。

### ページ作成者がやること

1. `auth.js` を読み込む（`src` の相対パスは下表に合わせる）
2. `PROTO_AUTH_CONFIG.title` に**そのページ名**を入れる（パンくずの末尾に出ます）
3. これだけ。パンくずは自動表示されます。**手書きの「戻る」リンクは置かないでください**（二重表示になります）

### 自動生成されるパンくず

| URL | 表示 |
|-----|------|
| `/`（TOP ハブ） | （非表示。ここが起点） |
| `/reports/` | `← Hub / Reports` |
| `/reports/<slug>/` | `← Hub / Reports / <title>` |
| `/ops/competitor-watch/` | `← Hub / 運用監視レポート / 競合ウォッチ` |
| `/ucarpac-app/<file>.html` | `← Hub / App プロトタイプ / <title>` |
| `/ucarpac-app/app-enhancement/prototype/<file>.html` | `← Hub / App プロトタイプ / App Enhancement / <title>` |

配色はセクションで自動判定します（`ucarpac-app/` はダーク、その他はライト）。

### 社内 / 代理店でパンくずを自動分岐

パンくずは**閲覧者の認証レベル**に応じて変わり、押せないリンクを代理店ユーザーに見せません。

| 閲覧者 | 代理店共有ページでのパンくず |
|--------|--------------------------|
| `full`（社内） | `← Hub / Reports / <title>` など通常の社内導線 |
| `agency`（代理店） | `← 代理店ハブ / <title>`（必ず `/agency/` 起点。代理店ハブ自身では非表示） |

代理店ユーザーは社内 Hub・Reports・ops 等の認証壁に当たりません。追加設定は不要です。

### `PROTO_AUTH_CONFIG` でのナビ制御（任意）

```js
window.PROTO_AUTH_CONFIG = {
  title: "ページ名",      // パンくず末尾ラベル（省略時は <title>）
  // navTheme: "dark",    // 配色を強制（"dark" | "light"）
  // breadcrumb: false,   // パンくずを出さない
  // nav: [               // 完全に手動指定したい場合（href はベースパス相対）
  //   { label: "Hub", href: "" },
  //   { label: "Reports", href: "reports/" },
  //   { label: "このページ" }   // 末尾＝現在ページ。リンクなし
  // ],
};
```

### セクション名・配色の定義場所

パンくずのラベルと配色は `auth.js` 冒頭の以下で管理しています。
**新しいセクション／カテゴリを追加したら、ここにラベルを足してください**（足さないとフォルダ名がそのまま出ます）。

- `SECTION_LABELS` … トップ階層（`ucarpac-app` → 「App プロトタイプ」など）
- `SUBSECTION_LABELS` … 第2階層（`ops/competitor-watch` → 「競合ウォッチ」など）
- `DARK_NAV_SECTIONS` … ダーク配色にするセクション

---

## コンテンツの種類と追加方法

### A. App プロトタイプを追加（自動生成）

ファイル命名規則: `<source>-<theme>-<variant>-<YYYY-MM-DD>.html`

- Codex 生成: `codex-` プレフィックス
- Claude 生成: `claude-` プレフィックス
- 手動作成: `01-`, `02-` などの番号プレフィックス

`auth.js`（`../auth.js`）を読み込み、`PROTO_AUTH_CONFIG.title` を設定します（パンくずは自動）。
追加後に `ucarpac-app/index.html` のカードリスト・ファイル数カウントを更新します。

### B. App Enhancement プロトタイプを追加（手動設計）

`ucarpac-app/app-enhancement/prototype/` 以下に配置します。
- ダークテーマ（`--charcoal: #1A1A2E`）で統一
- `auth.js`（`../../../auth.js`）を読み込み、`PROTO_AUTH_CONFIG.title` を設定
- `index-all.html` の統合ビューに新バージョンを追加
- パンくずは自動生成（手書き不要）

### C. 単発分析レポートを追加（UCP 内部向け）

1. `reports/<slug>/index.html` を作成（`slug` 例: `topic-YYYYMMDD-xxxxxxxx`）
2. `PROTO_AUTH_CONFIG`（`required` 省略）と `auth.js`（`../../auth.js`）を挿入し、`title` を設定
3. パンくずは自動生成されるので**手書きしない**
4. `reports/index.html` にカードを追加

### D. 代理店共有レポートを追加

上記 C に加えて、代理店共有にする（どちらか）：

5. ページ単位 → `PROTO_AUTH_CONFIG` に `required: "agency"` を追加、または
   パス一括 → `auth.js` の `AGENCY_PATH_PREFIXES` にそのパスを追加
6. `agency/index.html` にもカードを追加（アクセス許可とハブ掲載はセット）

代理店ユーザーのパンくずは自動で `← 代理店ハブ / <title>` になります（社内導線は出ません）。

### E. 運用監視レポートを追加（ops/）

1. `ops/<category>/index.html` に配置し、`auth.js`（`../../auth.js`）＋ `PROTO_AUTH_CONFIG.title` を設定
2. 新カテゴリなら `auth.js` の `SUBSECTION_LABELS` にラベルを追加（例: `ops/<category>` → 表示名）
3. パンくずは自動生成（手書き不要）
4. 必要なら `ops/index.html` にカードを追加

---

## デプロイ（push）

GitHub Pages は `main` ブランチから自動配信されます。
ローカルの作業ブランチは `codex/pages-hub`。

```bash
# 必ず最新を取得してから作業
git fetch origin
git rebase origin/main

# 変更をコミット
git add <変更ファイル>
git commit -m "Add/Update <内容>"

# main に push → GitHub Pages に即反映（数分以内）
git push origin HEAD:main
```

---

## 代理店への共有方法

URL とパスワードをセットで伝えます：

```
URL: https://ucarpac.github.io/biz-prototypes/agency/
パスワード: agency2026
```

詳細ルールは `AGENTS.md` を参照してください。
