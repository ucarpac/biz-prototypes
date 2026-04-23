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
| `agency` | agency2026 | `required: "agency"` のページのみ（代理店共有） |

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

## ナビゲーションのルール

ページには必ず「戻る」導線を設置します。

### 基本パターン（ライトテーマ用）

```html
<p style="margin:0 0 14px;font-size:13px;font-weight:600;color:#5f7182;">
  <a href="../../" style="color:#1a5cd8;text-decoration:none;">&#8592; Hub</a>
  <span style="margin:0 6px;color:#b0bccc;">/</span>
  <a href="../" style="color:#1a5cd8;text-decoration:none;">親セクション名</a>
</p>
```

### 固定ヘッダーパターン（個別プロトタイプページ用）

```html
<div style="position:fixed;top:0;left:0;right:0;z-index:9999;background:rgba(17,24,39,0.92);backdrop-filter:blur(8px);padding:10px 20px;font-size:13px;font-weight:600;border-bottom:1px solid rgba(255,255,255,0.08);">
  <a href="../" style="color:#94a3b8;text-decoration:none;">&#8592; プロトタイプ一覧</a>
  <span style="margin:0 8px;color:#374151;">/</span>
  <a href="../../../" style="color:#64748b;text-decoration:none;">Hub</a>
</div>
<div style="height:42px;"></div>
```

### ダークテーマページ用パンくず（app-enhancement など）

```html
<nav style="background:rgba(255,255,255,0.06);border-bottom:1px solid rgba(255,255,255,0.1);padding:12px 40px;font-size:13px;font-weight:600;">
  <a href="../../../" style="color:#94a3b8;text-decoration:none;">&#8592; Hub</a>
  <span style="margin:0 8px;color:#475569;">/</span>
  <a href="../../" style="color:#94a3b8;text-decoration:none;">App プロトタイプ</a>
  <span style="margin:0 8px;color:#475569;">/</span>
  <span style="color:#e2e8f0;">App Enhancement</span>
</nav>
```

---

## コンテンツの種類と追加方法

### A. App プロトタイプを追加（自動生成）

ファイル命名規則: `<source>-<theme>-<variant>-<YYYY-MM-DD>.html`

- Codex 生成: `codex-` プレフィックス
- Claude 生成: `claude-` プレフィックス
- 手動作成: `01-`, `02-` などの番号プレフィックス

追加後に `ucarpac-app/index.html` のカードリスト・ファイル数カウントを更新します。

### B. App Enhancement プロトタイプを追加（手動設計）

`ucarpac-app/app-enhancement/prototype/` 以下に配置します。
- ダークテーマ（`--charcoal: #1A1A2E`）で統一
- `index-all.html` の統合ビューに新バージョンを追加
- パンくずナビをページ先頭に追加（上記ダークテーマパターン参照）

### C. 単発分析レポートを追加（UCP 内部向け）

1. `reports/<slug>/index.html` を作成（`slug` 例: `topic-YYYYMMDD-xxxxxxxx`）
2. `PROTO_AUTH_CONFIG`（`required` 省略）と `auth.js` を挿入
3. パンくずナビを配置（`href="../../"` → Hub、`href="../"` → Reports）
4. `reports/index.html` にカードを追加

### D. 代理店共有レポートを追加

上記 C に加えて：

5. `PROTO_AUTH_CONFIG` に `required: "agency"` を追加
6. `agency/index.html` にもカードを追加

### E. 運用監視レポートを追加（ops/）

1. `ops/<category>/` にファイルを配置
2. パンくずナビ（Hub → 運用監視レポート）を追加
3. 必要なら `ops/index.html` にカードを追加

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
