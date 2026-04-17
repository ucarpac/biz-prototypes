# biz-prototypes

GitHub Pages で配信する UcarPAC の社内共有ハブです。
日々のプロトタイプ・分析レポートを UCP 内部と代理店共有で管理します。

## 構成

```
index.html          ← UCP 内部向けハブ
auth.js             ← 共通認証ゲート（2パスワード対応）
ucarpac-app/        ← 日々のプロトタイプ一覧
ops/                ← 継続更新の定点レポート（Auto KPI など）
reports/            ← 単発の分析レポート（UCP 内部向け一覧）
agency/             ← 代理店共有向けハブ
```

## 公開 URL

| 対象 | URL |
|------|-----|
| UCP 内部ハブ | `https://ucarpac.github.io/biz-prototypes/` |
| レポート一覧（内部） | `https://ucarpac.github.io/biz-prototypes/reports/` |
| 代理店共有ハブ | `https://ucarpac.github.io/biz-prototypes/agency/` |
| Auto KPI | `https://ucarpac.github.io/biz-prototypes/ops/auto-kpi/` |

## 認証の仕組み

`auth.js` は2つのアクセスレベルをサポートします。

| レベル | パスワード | 閲覧できるページ |
|--------|-----------|----------------|
| `full` | ucarpac2026 | 全ページ |
| `agency` | agency2026 | `required: "agency"` のページのみ |

各ページの `<head>` 内で以下を設定します：

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

## 新しいレポートを追加するとき

### 作業前に必ず最新を取得

```bash
git fetch origin
git rebase origin/main   # または git pull
```

### UCP 内部レポートとして追加

1. `reports/<slug>/index.html` を作成（`slug` は `topic-YYYYMMDD-xxxxxxxx`）
2. ページ先頭に `PROTO_AUTH_CONFIG`（`required` は省略）と `auth.js` を挿入
3. `← Reports に戻る` リンクを配置（`href="../"`）
4. `reports/index.html` にカードを追加

### 代理店共有レポートとして追加

上記に加えて：

5. `PROTO_AUTH_CONFIG` に `required: "agency"` を追加
6. `agency/index.html` にもカードを追加

### push

```bash
git add <変更ファイル>
git commit -m "Add <レポート名>"
git push origin HEAD:main
```

## 代理店への共有方法

URL とパスワードをセットで伝えます：

```
URL: https://ucarpac.github.io/biz-prototypes/agency/
パスワード: agency2026
```

詳細ルールは `AGENTS.md` を参照してください。
