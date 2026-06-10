# OneSignal KPI Dashboard

このフォルダは、OneSignal の月次ダッシュボードを GitHub Pages で公開するための一式です。

## Files

- `index.html`
  ダッシュボード本体です。現在値の表示に加えて、保存済みスナップショットをタブ切替で見られます。
- `push_notification_dashboard_data.js`
  現在表示用のデータです。
- `dashboard_config.json`
  更新時の補助設定です。
- `dashboard_history.js`
  履歴タブの一覧です。
- `history/<YYYY-MM>/`
  更新前に保存した月次スナップショットです。

## Update Flow

1. 更新前に現在のダッシュボードを履歴として保存
2. `push_notification_dashboard_data.js` などを新しい月の内容に更新
3. GitHub に push して公開反映

## Save Snapshot

更新前に次のコマンドを実行します。

```powershell
py scripts/archive_push_dashboard_snapshot.py --report-dir reports/push-notification-20260528-p7k4m2q8
```

これで次の2つが更新されます。

- `reports/push-notification-20260528-p7k4m2q8/history/<YYYY-MM>/`
- `reports/push-notification-20260528-p7k4m2q8/dashboard_history.js`

## Notes

- 履歴はリンク一覧ではなく、現在ページ内のタブからページ遷移なしで確認できます。
- スナップショット側では履歴欄を自動で隠すため、入れ子表示にはなりません。
