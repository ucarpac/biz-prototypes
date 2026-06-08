# OneSignal KPI Dashboard

このフォルダは、OneSignal の通知 KPI を GitHub 上で管理しつつ、BigQuery からの自動更新にもつなげるための最小構成です。

## 含まれるもの

- `index.html`
  ダッシュボード表示本体
- `push_notification_dashboard_data.js`
  フロント表示用のデータ
- `dashboard_config.json`
  BigQuery 参照先と表示用テキスト
- `source/`
  集計メモ、テンプレート CSV、スプレッドシート運用メモ

## 現在の前提

- 2026-05-19 時点のスナップショットを初期値として反映
- 有効DL累計は `33,855` をフォールバック値として使用
- Push 経由 DL 数は未反映
- クリック数は `onesignal_notifications_raw.raw_json.clicked` を利用

## 更新方法

1. GitHub Actions から `scripts/generate_push_dashboard_data.py` を実行
2. `push_notification_dashboard_data.js` を更新
3. `index.html` は固定表示レイヤーとして使い回す

## 補足

履歴系列はまだ薄いため、今回のコミットでは「確定しているスナップショットを安全に残す」ことを優先しています。今後、BigQuery から過去月系列を埋めることで、チャートの継続監視にもそのまま広げられます。
