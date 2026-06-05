# OneSignal Spreadsheet Setup

## シート構成

1. `daily_kpi`
2. `summary`
3. `charts`

## `daily_kpi` の主な列

- `cumulative_effective_dl`
- `onesignal_registered`
- `onesignal_registered_rate`
- `subscribed_count`
- `permission_rate_by_dl`
- `permission_rate_by_os`
- `unsubscribed_or_deleted`
- `unsubscribed_rate`
- `effective_target_count`
- `delivered_count`
- `delivery_rate`
- `click_count`
- `ctr`
- `push_dl_count`
- `push_dl_rate`

## `summary` に置く値

- OneSignal登録率
- 通知許諾率
- 到達率
- CTR
- 有効DL累計
- 通知許諾数
- 解除率
- Push経由DL数

## 運用メモ

- 日付は `YYYY-MM-DD`
- 母数は BigQuery で取れるものを優先
- 有効DL累計だけは当面フォールバック値の運用を許容
- Push経由DL数は後から AppsFlyer 連携で埋める
