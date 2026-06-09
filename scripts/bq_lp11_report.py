#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LP11 アプリ経由 CPA月次レポートジェネレーター（動的版）
実行するたびに「先月末まで」の実績を最新BQデータで生成する。

Usage:
  python bq_lp11_report.py        # → lp11_cpa_report.html を生成して自動オープン
"""
import sys, os, webbrowser, json, io, csv, subprocess
from datetime import date, timedelta, datetime
from collections import defaultdict
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

sys.stdout.reconfigure(encoding='utf-8')

# SA キーファイルが環境変数で指定されている場合は project_id を明示的に取得
# これにより google-github-actions/auth が設定する GOOGLE_CLOUD_PROJECT（ucarpac-uapp）の干渉を回避する
_sa_key_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
if _sa_key_path and os.path.exists(_sa_key_path):
    with open(_sa_key_path) as _f:
        _sa_info = json.load(_f)
    _sa_project = _sa_info.get('project_id', 'ucarpac-uapp')
    _credentials = service_account.Credentials.from_service_account_info(
        _sa_info,
        scopes=['https://www.googleapis.com/auth/cloud-platform']
    )
    client = bigquery.Client(project=_sa_project, credentials=_credentials)
    print(f'BQ: SAプロジェクト={_sa_project} で実行します')
else:
    client = bigquery.Client(project='ucarpac-uapp')

# ============================================================
# 集計期間の動的計算（先月末まで）
# ============================================================
today = date.today()
last_day_prev_month = date(today.year, today.month, 1) - timedelta(days=1)
first_day_data = date(2025, 7, 1)  # LP11アプリ流入データ開始月

START_DATE = first_day_data.strftime('%Y-%m-%d')
END_DATE = today.strftime('%Y-%m-%d')

print(f"集計期間: {START_DATE} 〜 {END_DATE}")

# キャンペーンID（LP11アプリ向け広告）
APP_CAMPAIGN_IDS = [
    22209354661, 22618223504, 22563843801, 22570164617,
    22411984951, 23520368820, 23638330077, 23638330296,
    22135376777,
]
IDS_STR = ', '.join(str(x) for x in APP_CAMPAIGN_IDS)

# ============================================================
# BQクエリ: 申込数・成約数・利益
# ============================================================
print("BQ: 申込・成約・利益データ取得中...")

q_conv = f"""
WITH lp11_app AS (
  SELECT
    id AS guest_id,
    FORMAT_DATE('%Y/%m', DATE(TIMESTAMP(created_at))) AS ym
  FROM `ucarpac-uapp.ucarpac_data.guests`
  WHERE (
    (inflow LIKE 'LP11%' OR inflow LIKE 'lp11%')
    OR from_app = '1'
  )
  AND DATE(TIMESTAMP(created_at)) >= '{START_DATE}'
  AND DATE(TIMESTAMP(created_at)) <= '{END_DATE}'
),
listed AS (
  SELECT DISTINCT a.guest_id
  FROM `ucarpac-uapp.ucarpac_data.assessments` a
  JOIN `ucarpac-uapp.ucarpac_data.auctions` au ON a.item_id = au.item_id
),
contracted AS (
  SELECT DISTINCT a.guest_id
  FROM `ucarpac-uapp.ucarpac_data.assessments` a
  JOIN `ucarpac-uapp.ucarpac_data.item_transitions` it ON a.item_id = it.item_id
  WHERE it.to_state = 'c2b_deal_passed'
),
-- 売上・利益: 取締役会KPI (bq_kpi_source.py) のロジックに準拠
profit_raw AS (
  SELECT
    a.guest_id,
    -- 利益のベース（実質的な手数料収入）
    CAST(COALESCE(o.commission_price,'0') AS INT64) AS commission,
    -- 売上額（取締役会基準: 手数料 + 消費税調整分 - 各種控除）
    GREATEST(
      CAST(COALESCE(o.commission_price,'0') AS INT64)
      + CAST(FLOOR(CAST(COALESCE(o.price,'0') AS INT64) * 0.1 / 1.1) AS INT64)
      - CAST(FLOOR(CAST(COALESCE(o.additional_amount,'0') AS INT64) / 1.1) AS INT64)
      - CAST(FLOOR(CAST(COALESCE(o.bidcoupon,'0') AS INT64) / 1.1) AS INT64)
    , 0) AS ucp_revenue
  FROM `ucarpac-uapp.ucarpac_data.orders` o
  JOIN `ucarpac-uapp.ucarpac_data.assessments` a ON CAST(a.item_id AS STRING) = CAST(o.item_id AS STRING)
  WHERE o.kind = 'C2B'
)
SELECT
  la.ym,
  COUNT(DISTINCT la.guest_id) AS applications,
  COUNT(DISTINCT l.guest_id) AS listings,
  COUNT(DISTINCT c.guest_id) AS contracts,
  ROUND(SAFE_DIVIDE(COUNT(DISTINCT c.guest_id), COUNT(DISTINCT la.guest_id)) * 100, 1) AS cvr,
  ROUND(SUM(p.commission) / 10000, 1) AS profit_man_yen,
  ROUND(SUM(p.ucp_revenue) / 10000, 1) AS revenue_man_yen,
  COUNT(DISTINCT p.guest_id) AS profit_matched
FROM lp11_app la
LEFT JOIN listed l ON la.guest_id = l.guest_id
LEFT JOIN contracted c ON la.guest_id = c.guest_id
LEFT JOIN profit_raw p ON la.guest_id = p.guest_id
GROUP BY 1
ORDER BY 1
"""

df_conv = client.query(q_conv).to_dataframe()
print(df_conv.to_string())

# ============================================================
# BQクエリ: 広告費
# ============================================================
print("\nBQ: 広告費データ取得中...")

q_cost = f"""
    WITH stats AS (
        SELECT 
            segments_date,
            campaign_id,
            metrics_cost_micros / 1000000 as cost,
            metrics_conversions as installs
        FROM `ucarpac-uapp.google_ads_reports.ads_CampaignBasicStats_9108194620`
        WHERE segments_date BETWEEN '{START_DATE}' AND '{END_DATE}'
        AND campaign_id IN ({IDS_STR})
    ),
    camps AS (
        SELECT campaign_id, MAX(campaign_name) as campaign_name
        FROM `ucarpac-uapp.google_ads_reports.ads_Campaign_9108194620`
        GROUP BY campaign_id
    )
    SELECT 
        FORMAT_DATE('%Y/%m', s.segments_date) as ym,
        SUM(CASE WHEN LOWER(c.campaign_name) LIKE '%android%' OR LOWER(c.campaign_name) LIKE '%andoroid%' THEN s.cost ELSE 0 END) as gads_android_cost_direct,
        SUM(CASE WHEN LOWER(c.campaign_name) LIKE '%ios%' OR LOWER(c.campaign_name) LIKE '%apple%' THEN s.cost ELSE 0 END) as gads_ios_cost_direct,
        SUM(CASE WHEN (LOWER(c.campaign_name) NOT LIKE '%android%' AND LOWER(c.campaign_name) NOT LIKE '%andoroid%') AND LOWER(c.campaign_name) NOT LIKE '%ios%' AND LOWER(c.campaign_name) NOT LIKE '%apple%' THEN s.cost ELSE 0 END) as gads_other_cost,
        SUM(s.cost) as total_cost_jpy,
        SUM(CASE WHEN LOWER(c.campaign_name) LIKE '%android%' OR LOWER(c.campaign_name) LIKE '%andoroid%' THEN s.installs ELSE 0 END) as bq_gads_android_installs,
        SUM(CASE WHEN LOWER(c.campaign_name) LIKE '%ios%' OR LOWER(c.campaign_name) LIKE '%apple%' THEN s.installs ELSE 0 END) as bq_gads_ios_installs
    FROM stats s
    LEFT JOIN camps c ON s.campaign_id = c.campaign_id
    GROUP BY 1 ORDER BY 1
"""
df_cost = client.query(q_cost).to_dataframe()

# ============================================================
# AppsFlyer API: インストール数（Android + iOS）
# ============================================================
print("\nAppsFlyer: インストール数取得中...")
AF_TOKEN = os.environ.get("APPSFLYER_TOKEN")
if not AF_TOKEN:
    raise RuntimeError("APPSFLYER_TOKEN is required to update the LP11 CPA report")
AF_APPS = [
    ("com.ucarpac.uapp", "android"),
    ("id6476742396",     "ios"),
]
af_monthly      = defaultdict(int)   # 全体installs
af_gads_android = defaultdict(lambda: {"installs": 0, "cost": 0.0})  # Google Ads Android
af_gads_ios     = defaultdict(lambda: {"installs": 0, "cost": 0.0})  # Google Ads iOS
af_asa_monthly  = defaultdict(lambda: {"installs": 0, "cost": 0.0})  # ASA installs + cost

for _app_id, _os in AF_APPS:
    _url = (f"https://hq1.appsflyer.com/api/agg-data/export/app/{_app_id}/"
            f"partners_by_date_report/v5?from={START_DATE}&to={END_DATE}")
    _res = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Bearer {AF_TOKEN}", _url],
        capture_output=True, text=True, encoding="utf-8"
    )
    if _res.returncode != 0:
        print(f"  WARNING: AppsFlyer fetch failed for {_app_id}")
        continue
    _reader = csv.DictReader(io.StringIO(_res.stdout))
    for _row in _reader:
        _d_str = _row.get("Date", "")
        if not _d_str:
            continue
        try:
            _d    = date.fromisoformat(_d_str)
            _ym   = _d.strftime("%Y/%m")
            _pid  = _row.get("Media Source (pid)", "")
            _inst = int(float(_row.get("Installs", 0) or 0))
            _cost_raw = _row.get("Total Cost", "N/A")
            _cost = 0.0 if _cost_raw in ("", "N/A", None) else float(_cost_raw)
            # 全体
            af_monthly[_ym] += _inst
            # Google Ads (OS別)
            if _pid == "googleadwords_int":
                if _os == "android":
                    af_gads_android[_ym]["installs"] += _inst
                    af_gads_android[_ym]["cost"]     += _cost
                else:
                    af_gads_ios[_ym]["installs"] += _inst
                    af_gads_ios[_ym]["cost"]     += _cost
            # Apple Search Ads
            elif _pid == "Apple Search Ads":
                af_asa_monthly[_ym]["installs"] += _inst
                af_asa_monthly[_ym]["cost"]     += _cost
        except Exception:
            pass

df_af = pd.DataFrame([
    {
        "ym":                   k,
        "installs":             af_monthly[k],
        "gads_android_installs": af_gads_android[k]["installs"] if k in af_gads_android else 0,
        "gads_android_cost":    af_gads_android[k]["cost"]     if k in af_gads_android else 0.0,
        "gads_ios_installs":    af_gads_ios[k]["installs"]     if k in af_gads_ios     else 0,
        "gads_ios_cost":        af_gads_ios[k]["cost"]         if k in af_gads_ios     else 0.0,
        "asa_installs":         af_asa_monthly[k]["installs"]  if k in af_asa_monthly  else 0,
        "asa_cost":             af_asa_monthly[k]["cost"]      if k in af_asa_monthly  else 0.0,
    }
    for k in sorted(af_monthly.keys())
])
print(f"  AppsFlyer取得月数: {len(df_af)}")
print(df_af[['ym','installs','gads_android_installs','gads_ios_installs','asa_installs']].to_string(index=False))

# ============================================================
# データ統合 & CPA計算
# ============================================================
df = df_conv.merge(df_cost, on='ym', how='left').fillna(0)
df = df.merge(df_af, on='ym', how='left').fillna(0)

# Google Ads CPIはGoogle Ads側のコンバージョンを使用する要望に対応
df['gads_android_installs'] = df['bq_gads_android_installs']
df['gads_ios_installs']     = df['bq_gads_ios_installs']

# 広告費用の按分と手数料追加
# BQの cost_jpy を total_cost_jpy に置き換え
df['cost_jpy'] = df['total_cost_jpy'] * 1.2  # 代理店手数料20%追加

# 共通費(other_cost)をインストール比率で按分
def distribute_cost(r):
    total_gads_inst = r['gads_android_installs'] + r['gads_ios_installs']
    other_cost = r['gads_other_cost']
    if total_gads_inst > 0:
        and_ratio = r['gads_android_installs'] / total_gads_inst
        ios_ratio = r['gads_ios_installs'] / total_gads_inst
    else:
        # インストールがない場合は50:50
        and_ratio, ios_ratio = 0.5, 0.5
    
    r['gads_android_cost_final'] = (r['gads_android_cost_direct'] + other_cost * and_ratio) * 1.2
    r['gads_ios_cost_final']     = (r['gads_ios_cost_direct'] + other_cost * ios_ratio) * 1.2
    return r

df = df.apply(distribute_cost, axis=1)

# CPI計算
df['cpi'] = df.apply(
    lambda r: round(r['cost_jpy'] / r['installs']) if r['installs'] > 0 and r['cost_jpy'] > 0 else None, axis=1
)
df['gads_android_cpi'] = df.apply(
    lambda r: round(r['gads_android_cost_final'] / r['gads_android_installs']) if r['gads_android_installs'] > 0 else None, axis=1
)
df['gads_ios_cpi'] = df.apply(
    lambda r: round(r['gads_ios_cost_final'] / r['gads_ios_installs']) if r['gads_ios_installs'] > 0 else None, axis=1
)

df['apply_cpa'] = df.apply(
    lambda r: round(r['cost_jpy'] / r['applications']) if r['applications'] > 0 and r['cost_jpy'] > 0 else None, axis=1
)
df['contract_cpa'] = df.apply(
    lambda r: round(r['cost_jpy'] / r['contracts']) if r['contracts'] > 0 and r['cost_jpy'] > 0 else None, axis=1
)
df['revenue_per_car'] = df.apply(
    lambda r: round((r['revenue_man_yen'] * 10000) / r['contracts']) if r['contracts'] > 0 else None, axis=1
)
df['profit_per_car'] = df.apply(
    lambda r: round((r['profit_man_yen'] * 10000) / r['contracts']) if r['contracts'] > 0 else None, axis=1
)

# 詳細ファネル計算
df['listing_rate'] = df.apply(
    lambda r: round(r['listings'] / r['applications'] * 100, 1) if r['applications'] > 0 else 0, axis=1
)
df['contract_listing_rate'] = df.apply(
    lambda r: round(r['contracts'] / r['listings'] * 100, 1) if r['listings'] > 0 else 0, axis=1
)
df['clear_profit_man_yen'] = df.apply(
    lambda r: round(r['revenue_man_yen'] - (r['cost_jpy'] / 10000), 1), axis=1
)

# Google Ads 全体CPI
df['gads_cpi'] = df.apply(
    lambda r: round(r['cost_jpy'] / (r['gads_android_installs'] + r['gads_ios_installs']))
              if (r.get('gads_android_installs', 0) + r.get('gads_ios_installs', 0)) > 0 else None, axis=1
)

# Google Ads Android CPI
df['gads_android_cpi'] = df.apply(
    lambda r: round(r['gads_android_cost_final'] / r['gads_android_installs'])
              if r.get('gads_android_installs', 0) > 0 else None, axis=1
)
# Google Ads iOS CPI
df['gads_ios_cpi'] = df.apply(
    lambda r: round(r['gads_ios_cost_final'] / r['gads_ios_installs'])
              if r.get('gads_ios_installs', 0) > 0 else None, axis=1
)
# ASA CPI = AF Total Cost ÷ AF Apple Search Ads installs (ASAはAFコストを継続使用)
df['asa_cpi'] = df.apply(
    lambda r: round(r['asa_cost'] / r['asa_installs']) if r.get('asa_installs', 0) > 0 and r.get('asa_cost', 0) > 0 else None, axis=1
)

print("\n=== 最終集計 ===")
print(df[['ym','applications','contracts','installs','cost_jpy','cpi','apply_cpa','profit_man_yen']].to_string(index=False))

# CSV保存
df.to_csv('lp11_cpa_final.csv', encoding='utf-8-sig', index=False)

# ============================================================
# BQクエリ: 1ヶ月以上前登録ユーザーの月間申込数（実発生ベース）
# ============================================================
print("BQ: 既存ユーザー申込数（実発生ベース）取得中...")
q_old_apps = """
SELECT
  FORMAT_DATE('%Y/%m', DATE(TIMESTAMP(g.created_at))) AS app_ym,
  COUNT(DISTINCT g.id) AS old_user_apps
FROM `ucarpac-uapp.ucarpac_data.guests` g
JOIN `ucarpac-uapp.ucarpac_data.app_toc_guest_users` u ON g.id = u.ucp_guest_id
WHERE g.from_app = '1'
  AND DATE_DIFF(DATE(TIMESTAMP(g.created_at)), DATE(TIMESTAMP(u.created_at)), DAY) > 30
GROUP BY 1
ORDER BY 1
"""
df_old_user_apps = client.query(q_old_apps).to_dataframe()

# ============================================================
# BQクエリ: コホート申込率（登録から1ヶ月以内）
# ============================================================
print("\nBQ: コホート申込率データ取得中...")
from dateutil.relativedelta import relativedelta

# 【ロジック修正】
# 分母: App登録者数 (app_toc_guest_users)
# 分子: 上記ユーザーのうち、30日以内に「ゲスト登録（査定申込フロー開始）」に至った人数
# ※ユーザー提供数値 (2026/03: 3.10%) と近似するように集計
q_cohort = """
WITH app_users AS (
  SELECT
    id AS app_user_id,
    ucp_guest_id,
    DATE(TIMESTAMP(created_at)) AS registered_at,
    FORMAT_DATE('%Y/%m', DATE(TIMESTAMP(created_at))) AS reg_ym
  FROM `ucarpac-uapp.ucarpac_data.app_toc_guest_users`
  WHERE DATE(TIMESTAMP(created_at)) >= '2025-04-01'
),
guest_entries AS (
  -- インフロー問わず、アプリ経由で作成されたゲストレコード
  SELECT
    id AS guest_id,
    DATE(TIMESTAMP(created_at)) AS guest_created_at
  FROM `ucarpac-uapp.ucarpac_data.guests`
  WHERE from_app = '1'
)
SELECT
  u.reg_ym,
  COUNT(DISTINCT u.app_user_id)                                            AS total_users,
  COUNT(DISTINCT CASE
    WHEN g.guest_id IS NOT NULL
    AND DATE_DIFF(g.guest_created_at, u.registered_at, DAY) <= 30
    THEN u.app_user_id END)                                                AS applied_within_1m,
  ROUND(
    SAFE_DIVIDE(
      COUNT(DISTINCT CASE
        WHEN g.guest_id IS NOT NULL
        AND DATE_DIFF(g.guest_created_at, u.registered_at, DAY) <= 30
        THEN u.app_user_id END),
      COUNT(DISTINCT u.app_user_id)
    ) * 100, 2
  )                                                                        AS rate_within_1m,
  COUNT(DISTINCT CASE
    WHEN g.guest_id IS NOT NULL
    AND DATE_DIFF(g.guest_created_at, u.registered_at, DAY) > 30
    THEN u.app_user_id END)                                                AS applied_after_1m,
  ROUND(
    SAFE_DIVIDE(
      COUNT(DISTINCT CASE
        WHEN g.guest_id IS NOT NULL
        AND DATE_DIFF(g.guest_created_at, u.registered_at, DAY) > 30
        THEN u.app_user_id END),
      COUNT(DISTINCT u.app_user_id)
    ) * 100, 2
  )                                                                        AS rate_after_1m
FROM app_users u
LEFT JOIN guest_entries g ON u.ucp_guest_id = g.guest_id
GROUP BY 1
ORDER BY 1
"""

df_cohort = client.query(q_cohort).to_dataframe()

# ============================================================
# 今月アプリ登録コホート OS別（オーガニック含む全体）
# ============================================================
current_month_start = date(today.year, today.month, 1).strftime('%Y-%m-%d')
q_cohort_os = f"""
DECLARE start_date DATE DEFAULT DATE '{current_month_start}';
DECLARE end_date DATE DEFAULT CURRENT_DATE('Asia/Tokyo');

WITH latest_device AS (
  SELECT
    user_uuid,
    CASE
      WHEN LOWER(token_type) = 'android' THEN 'Android'
      WHEN LOWER(token_type) = 'ios' THEN 'iOS'
      ELSE 'OS不明'
    END AS os
  FROM `ucarpac-uapp.ucarpac_data.app_toc_device_tokens`
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY user_uuid
    ORDER BY SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%S', updated_at) DESC,
             SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%S', created_at) DESC,
             id DESC
  ) = 1
),
app_users AS (
  SELECT
    u.id AS app_user_id,
    u.user_uuid,
    CAST(u.ucp_guest_id AS STRING) AS ucp_guest_id,
    DATE(SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%S', u.created_at)) AS app_registered_date,
    COALESCE(d.os, 'OS不明') AS os
  FROM `ucarpac-uapp.ucarpac_data.app_toc_guest_users` u
  LEFT JOIN latest_device d USING (user_uuid)
  WHERE DATE(SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%S', u.created_at)) BETWEEN start_date AND end_date
),
within_1m AS (
  SELECT
    u.os,
    COUNT(DISTINCT u.app_user_id) AS registered_users,
    COUNT(DISTINCT IF(g.id IS NOT NULL, u.app_user_id, NULL)) AS applications_within_1m,
    COUNT(DISTINCT IF(it.item_id IS NOT NULL, u.app_user_id, NULL)) AS contracts_within_1m
  FROM app_users u
  LEFT JOIN `ucarpac-uapp.ucarpac_data.guests` g
    ON CAST(g.id AS STRING) = u.ucp_guest_id
   AND LOWER(COALESCE(g.from_app, '')) IN ('1', 'true', 't', 'yes')
   AND DATE(SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%S', g.created_at))
       BETWEEN u.app_registered_date AND DATE_ADD(u.app_registered_date, INTERVAL 30 DAY)
  LEFT JOIN `ucarpac-uapp.ucarpac_data.assessments` a ON a.guest_id = g.id
  LEFT JOIN `ucarpac-uapp.ucarpac_data.item_transitions` it
    ON it.item_id = a.item_id
   AND it.to_state = 'c2b_deal_passed'
  GROUP BY u.os
),
google_cost AS (
  WITH stats AS (
    SELECT campaign_id, SUM(metrics_cost_micros) / 1000000 AS media_cost_jpy
    FROM `ucarpac-uapp.google_ads_reports.ads_CampaignBasicStats_9108194620`
    WHERE segments_date BETWEEN start_date AND end_date
      AND campaign_id IN (
        22209354661, 22618223504, 22563843801, 22570164617, 22411984951,
        23520368820, 23638330077, 23638330296, 22135376777
      )
    GROUP BY campaign_id
  ),
  campaigns AS (
    SELECT campaign_id, campaign_name
    FROM `ucarpac-uapp.google_ads_reports.ads_Campaign_9108194620`
    QUALIFY ROW_NUMBER() OVER (PARTITION BY campaign_id ORDER BY _DATA_DATE DESC) = 1
  )
  SELECT
    CASE WHEN REGEXP_CONTAINS(UPPER(campaign_name), r'IOS') THEN 'iOS' ELSE 'Android' END AS os,
    ROUND(SUM(media_cost_jpy) * 1.2, 0) AS cost_jpy
  FROM stats
  LEFT JOIN campaigns USING (campaign_id)
  GROUP BY os
),
tiktok_cost AS (
  WITH dedup AS (
    SELECT *
    FROM `ucarpac-uapp.ucarpac_data.tiktok_ads_report_raw_v2`
    WHERE stat_time_day BETWEEN start_date AND end_date
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY stat_time_day, campaign_id, adgroup_id, ad_id
      ORDER BY extracted_at DESC
    ) = 1
  )
  SELECT
    CASE WHEN REGEXP_CONTAINS(LOWER(campaign_name), r'ios|iphone|apple') THEN 'iOS' ELSE 'Android' END AS os,
    ROUND(SUM(spend), 0) AS cost_jpy
  FROM dedup
  WHERE objective_type = 'APP_PROMOTION'
    AND app_promotion_type = 'APP_INSTALL'
  GROUP BY os
),
asa_cost AS (
  WITH dedup AS (
    SELECT *
    FROM `ucarpac-uapp.ucarpac_data.apple_search_ads_campaign_daily`
    WHERE report_date BETWEEN start_date AND end_date
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY report_date, campaign_id
      ORDER BY extracted_at DESC
    ) = 1
  )
  SELECT 'iOS' AS os, ROUND(SUM(local_spend), 0) AS cost_jpy
  FROM dedup
),
cost AS (
  SELECT os, SUM(cost_jpy) AS cost_jpy
  FROM (
    SELECT * FROM google_cost
    UNION ALL SELECT * FROM tiktok_cost
    UNION ALL SELECT * FROM asa_cost
  )
  GROUP BY os
)
SELECT
  w.os,
  w.registered_users,
  ROUND(SAFE_DIVIDE(w.registered_users, SUM(w.registered_users) OVER()) * 100, 1) AS registered_share_pct,
  w.applications_within_1m,
  ROUND(SAFE_DIVIDE(w.applications_within_1m, SUM(w.applications_within_1m) OVER()) * 100, 1) AS application_share_pct,
  ROUND(SAFE_DIVIDE(w.applications_within_1m, w.registered_users) * 100, 2) AS application_rate_pct,
  w.contracts_within_1m,
  IFNULL(c.cost_jpy, 0) AS app_install_ad_cost_jpy,
  ROUND(SAFE_DIVIDE(IFNULL(c.cost_jpy, 0), NULLIF(w.applications_within_1m, 0)), 0) AS application_cpa_jpy,
  ROUND(SAFE_DIVIDE(IFNULL(c.cost_jpy, 0), NULLIF(w.contracts_within_1m, 0)), 0) AS contract_cpa_jpy
FROM within_1m w
LEFT JOIN cost c USING (os)
ORDER BY CASE w.os WHEN 'Android' THEN 1 WHEN 'iOS' THEN 2 WHEN 'OS不明' THEN 8 ELSE 9 END
"""
df_cohort_os = client.query(q_cohort_os).to_dataframe()

# ============================================================
# Google Sheets API: 有効DL数 (分母) の取得
# ============================================================
print("\nGoogle Sheets: 有効DL数データ取得中...")
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    import os
    
    KEY_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "credentials_sheets.json"
    if os.path.exists(KEY_FILE):
        _sheets_creds = service_account.Credentials.from_service_account_file(
            KEY_FILE, scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        _sheets_service = build('sheets', 'v4', credentials=_sheets_creds)
        _res_sheets = _sheets_service.spreadsheets().values().get(
            spreadsheetId="1Wvoo8dAeYz5uWNT9G4EAjTfsmIDVnPi04sJENAvVWwQ", 
            range='実績!A38:Z150'
        ).execute()
        _s_values = _res_sheets.get('values', [])
        
        valid_dls_map = {}
        new_dls_map = {}
        for row in _s_values:
            if len(row) > 3:
                _ym_raw = row[0].strip()
                # YYYY/MM 形式のチェック
                if len(_ym_raw) == 7 and _ym_raw.count('/') == 1:
                    # 新規DL数 (Index 1)
                    _new_raw = row[1].replace(',', '').strip()
                    if _new_raw.isdigit():
                        new_dls_map[_ym_raw] = int(_new_raw)
                    
                    # 有効DL数 (Index 3)
                    _val_raw = row[3].replace(',', '').strip()
                    if _val_raw.isdigit():
                        valid_dls_map[_ym_raw] = int(_val_raw)
        
        print(f"スプレッドシート取得完了: 新規DL数={len(new_dls_map)}件, 有効DL数={len(valid_dls_map)}件")
        
        # マップの値をDFに適用
        df_cohort['new_dls_sheets'] = df_cohort['reg_ym'].map(new_dls_map)
        df_cohort['active_dls_sheets'] = df_cohort['reg_ym'].map(valid_dls_map)
        
        # データが欠けている場合は元のtotal_usersをフォールバックに使う
        df_cohort['new_dls_used'] = df_cohort.apply(
            lambda r: r['new_dls_sheets'] if pd.notnull(r['new_dls_sheets']) and r['new_dls_sheets'] > 0 else r['total_users'], axis=1
        )
        df_cohort['active_dls_used'] = df_cohort.apply(
            lambda r: r['active_dls_sheets'] if pd.notnull(r['active_dls_sheets']) and r['active_dls_sheets'] > 0 else r['total_users'], axis=1
        )
        
        # 分母を使い分けて再計算
        # 1. 登録30日以内申込率: 分母=UUID新規登録数 (BQの total_users)
        df_cohort['rate_within_1m'] = df_cohort.apply(
            lambda r: round((r['applied_within_1m'] / r['total_users']) * 100, 2) if r['total_users'] > 0 else 0, axis=1
        )
        # 2. 1ヶ月以上経過申込率 (申込月別): 分母=有効DL数, 分子=既存ユーザー申込数
        # アプリ申込月ベースのデータと統合
        df_cohort = df_cohort.merge(df_old_user_apps, left_on='reg_ym', right_on='app_ym', how='left').fillna({'old_user_apps': 0})
        
        df_cohort['rate_after_1m'] = df_cohort.apply(
            lambda r: round((r['old_user_apps'] / r['active_dls_used']) * 100, 2) if r['active_dls_used'] > 0 else 0, axis=1
        )
        
        # ダッシュボード統合用の total_users は「有効DL数」を参考値として採用
        # ※chart_dl 等の不整合を避けるため、既存の登録数ベースは維持
        # df_cohort['total_users'] = df_cohort['active_dls_used'] 
except Exception as e:
    print(f"  ERROR: Sheets fetch failed: {e}")

if 'new_dls_used' not in df_cohort.columns:
    df_cohort['new_dls_used'] = df_cohort['total_users']
if 'active_dls_used' not in df_cohort.columns:
    df_cohort['active_dls_used'] = df_cohort['total_users']

print(df_cohort.to_string())

# 直近月（1ヶ月窓が閉じていない）にフラグ
_today = date.today()
_complete_cutoff = date(_today.year, _today.month, 1) - relativedelta(months=1)
df_cohort['ym_date'] = pd.to_datetime(df_cohort['reg_ym'], format='%Y/%m').dt.date
df_cohort['is_incomplete'] = df_cohort['ym_date'].apply(lambda d: d >= _complete_cutoff)

# メインデータフレームに登録者数を統合
df = df.merge(df_cohort[['reg_ym', 'total_users']], left_on='ym', right_on='reg_ym', how='left').drop(columns=['reg_ym']).fillna({'total_users': 0})
df['total_users'] = df['total_users'].astype(int)

# コホート全体データ（KPI計算用）
cohort_months_all = df_cohort['reg_ym'].tolist()
cohort_rate_all = df_cohort['rate_within_1m'].tolist()

# ============================================================
# KPI計算（今月 vs 前月）
# ============================================================
def fmt_num(v, unit=''):
    if v is None or pd.isna(v): return '-'
    if unit == '万': return f"¥{v:,.1f}万"
    if unit == '円': return f"¥{int(v):,}"
    if unit == '%': return f"{v:.1f}%"
    return str(v)

def diff_arrow(curr, prev, lower_is_better=False):
    if curr is None or prev is None or pd.isna(curr) or pd.isna(prev) or prev == 0:
        return '', 'neutral'
    diff_pct = (curr - prev) / abs(prev) * 100
    if lower_is_better:
        if diff_pct > 3: return f'▲ {abs(diff_pct):.1f}%', 'bad'
        if diff_pct < -3: return f'▼ {abs(diff_pct):.1f}%', 'good'
    else:
        if diff_pct > 3: return f'▲ {abs(diff_pct):.1f}%', 'good'
        if diff_pct < -3: return f'▼ {abs(diff_pct):.1f}%', 'bad'
    return f'± {abs(diff_pct):.1f}%', 'neutral'

last = df.iloc[-1] if len(df) >= 1 else None
prev = df.iloc[-2] if len(df) >= 2 else None

def kpi(row, col, default=None):
    if row is None: return default
    v = row.get(col)
    return None if pd.isna(v) else v

last_cost   = kpi(last, 'cost_jpy')
prev_cost   = kpi(prev, 'cost_jpy')
last_acpa   = kpi(last, 'apply_cpa')
prev_acpa   = kpi(prev, 'apply_cpa')
last_ccpa   = kpi(last, 'contract_cpa')
prev_ccpa   = kpi(prev, 'contract_cpa')
last_cvr    = kpi(last, 'cvr')
avg_cvr     = df[df['applications'] > 0]['cvr'].mean() if not df.empty else None
avg_cpi     = df[df['installs'] > 0]['cpi'].mean() if not df.empty else None
avg_acpa    = df[df['applications'] > 0]['apply_cpa'].mean() if not df.empty else None
avg_ccpa    = df[df['contracts'] > 0]['contract_cpa'].mean() if not df.empty else None
avg_listing_rate = df[df['applications'] > 0]['listing_rate'].mean() if not df.empty else None
avg_contract_listing_rate = df[df['listings'] > 0]['contract_listing_rate'].mean() if not df.empty else None

last_cohort_rate = cohort_rate_all[-1] if cohort_rate_all else 0
prev_cohort_rate = cohort_rate_all[-2] if len(cohort_rate_all) >= 2 else 0
cohort_rate_diff, cohort_rate_cls = diff_arrow(last_cohort_rate, prev_cohort_rate, lower_is_better=False)

cost_diff,  cost_cls  = diff_arrow(last_cost, prev_cost, lower_is_better=False)
acpa_diff,  acpa_cls  = diff_arrow(last_acpa, prev_acpa, lower_is_better=True)
ccpa_diff,  ccpa_cls  = diff_arrow(last_ccpa, prev_ccpa, lower_is_better=True)

# CPIカード追加 (全体・OS別)
last_cpi         = kpi(last, 'cpi')
prev_cpi         = kpi(prev, 'cpi')
last_cpi_android = kpi(last, 'gads_android_cpi')
prev_cpi_android = kpi(prev, 'gads_android_cpi')
last_cpi_ios     = kpi(last, 'gads_ios_cpi')
prev_cpi_ios     = kpi(prev, 'gads_ios_cpi')

cpi_diff, cpi_cls = diff_arrow(last_cpi, prev_cpi, lower_is_better=True)
cpi_and_diff, cpi_and_cls = diff_arrow(last_cpi_android, prev_cpi_android, lower_is_better=True)
cpi_ios_diff, cpi_ios_cls = diff_arrow(last_cpi_ios, prev_cpi_ios, lower_is_better=True)

last_apps = kpi(last, 'applications')
prev_apps = kpi(prev, 'applications')

last_contracts = kpi(last, 'contracts')
prev_contracts = kpi(prev, 'contracts')
contracts_diff, contracts_cls = diff_arrow(last_contracts, prev_contracts, lower_is_better=False)

last_clear_profit = kpi(last, 'clear_profit_man_yen')
prev_clear_profit = kpi(prev, 'clear_profit_man_yen')
clear_profit_diff, clear_profit_cls = diff_arrow(last_clear_profit, prev_clear_profit, lower_is_better=False)


# 今月の着地見込み計算
import calendar
now = datetime.now()
last_ym_str = last['ym'] if last is not None else None
is_current_month = (last_ym_str == now.strftime('%Y/%m')) if last_ym_str else False

last_cost_est_html = ""
last_installs_est_html = ""
if is_current_month:
    current_day = now.day
    _, days_in_month = calendar.monthrange(now.year, now.month)
    
    # 広告費
    if last_cost:
        last_cost_est = last_cost * (days_in_month / current_day)
        last_cost_est_html = f'<div style="font-size:11px; color:#9ca3af; margin-top:-6px;">(着地見込: ¥{last_cost_est/10000:,.0f}万)</div>'
    
    # インストール
    last_installs = kpi(last, 'installs')
    prev_installs = kpi(prev, 'installs')
    installs_diff, installs_cls = diff_arrow(last_installs, prev_installs, lower_is_better=False)
    if last_installs:
        last_installs_est = last_installs * (days_in_month / current_day)
        last_installs_est_html = f'<div style="font-size:11px; color:#9ca3af; margin-top:-6px;">(着地見込: {int(last_installs_est):,} DL)</div>'
else:
    last_cost_est_html = ""
    last_installs_est_html = ""
    last_installs = kpi(last, 'installs')
    prev_installs = kpi(prev, 'installs')
    installs_diff, installs_cls = diff_arrow(last_installs, prev_installs, lower_is_better=False)
cvr_diff,   cvr_cls   = diff_arrow(last_cvr, avg_cvr, lower_is_better=False)

last_ym = last['ym'] if last is not None else '-'
prev_ym = prev['ym'] if prev is not None else '-'

# ============================================================
# Chart データ
# ============================================================
months        = df['ym'].tolist()
apps          = df['applications'].tolist()
contracts     = df['contracts'].tolist()
cvr_list      = df['cvr'].tolist()
installs_list = df['installs'].tolist()
cpi_list           = [int(x) if x is not None and not pd.isna(x) else None for x in df['cpi'].tolist()]
gads_android_cpi_list = [int(x) if x is not None and not pd.isna(x) else None for x in df['gads_android_cpi'].tolist()]
gads_ios_cpi_list     = [int(x) if x is not None and not pd.isna(x) else None for x in df['gads_ios_cpi'].tolist()]
asa_cpi_list          = [int(x) if x is not None and not pd.isna(x) else None for x in df['asa_cpi'].tolist()]
# 収益チャート用データ
# 売上は「取締役会基準の売上高（消費税調整込み）」、利益は「手数料収入（広告費引く前）」を使用
revenue_man   = df['revenue_man_yen'].tolist()
profit_list    = df['profit_man_yen'].tolist()
costs_man     = (df['cost_jpy'] / 10000).round(1).tolist()
clear_profit_list = df['clear_profit_man_yen'].tolist()
apply_cpa_l   = df['apply_cpa'].fillna(0).tolist()
contract_cpa_l= df['contract_cpa'].fillna(0).tolist()
listing_rates = df['listing_rate'].tolist()
contract_listing_rates = df['contract_listing_rate'].tolist()
registered_users = df['total_users'].tolist()

# コホートグラフ用データ（表示用に過去12ヶ月にスライス）
df_cohort_sliced = df_cohort.tail(12)
cohort_months = df_cohort_sliced['reg_ym'].tolist()
cohort_total = df_cohort_sliced['total_users'].tolist()
cohort_rate = df_cohort_sliced['rate_within_1m'].tolist()

# 修正: CURRENT_DATE() に基づいて判定
today_ym = datetime.now().strftime('%Y/%m')
cohort_incomplete = [m == today_ym for m in cohort_months]
avg_cohort_rate = round(df_cohort_sliced['rate_within_1m'].mean(), 2) if not df_cohort_sliced.empty else 0

# 既存ユーザー申込率グラフ用データ
old_apps_rate = df_cohort_sliced['rate_after_1m'].tolist()
avg_old_apps_rate = round(df_cohort_sliced['rate_after_1m'].mean(), 2) if not df_cohort_sliced.empty else 0

def fmt_int(v):
    try:
        if v is None or pd.isna(v): return '-'
        return f"{int(v):,}"
    except:
        return '-'

def fmt_pct(v, digits=1):
    try:
        if v is None or pd.isna(v): return '-'
        return f"{float(v):.{digits}f}%"
    except:
        return '-'

def fmt_yen(v):
    try:
        if v is None or pd.isna(v): return '-'
        return f"¥{int(v):,}"
    except:
        return '-'

cohort_os_rows_html = ''
if df_cohort_os.empty:
    cohort_os_rows_html = '<tr><td colspan="6" class="empty-cell">データなし</td></tr>'
else:
    for _, r in df_cohort_os.iterrows():
        cohort_os_rows_html += (
            f"<tr>"
            f"<td>{r['os']}</td>"
            f"<td>{fmt_int(r['registered_users'])}</td>"
            f"<td>{fmt_int(r['applications_within_1m'])}</td>"
            f"<td>{fmt_pct(r['application_rate_pct'], 2)}</td>"
            f"<td>{fmt_yen(r['application_cpa_jpy'])}</td>"
            f"<td>{fmt_yen(r['contract_cpa_jpy'])}</td>"
            f"</tr>"
        )

# ============================================================
# 有効DL数（現在インストール推定）: Google Sheets 実績タブ
# ============================================================
store_valid_df = df_cohort[['reg_ym', 'active_dls_used']].dropna().copy()
store_valid_df = store_valid_df[store_valid_df['active_dls_used'] > 0].tail(14)
store_valid_months = store_valid_df['reg_ym'].tolist()
active_download_users = [int(v) for v in store_valid_df['active_dls_used'].tolist()]
store_total_latest = active_download_users[-1] if active_download_users else 0


# ============================================================
# テーブル行生成（NaN安全）
# ============================================================
def safe_cpa(v):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)): return '-'
        return f"¥{int(v):,}"
    except: return '-'

rows_html = ''
for _, r in df.iterrows():
    rows_html += (
        f"<tr><td>{r['ym']}</td>"
        f"<td>{int(r['applications'])}</td>"
        f"<td>{int(r['contracts'])}</td>"
        f"<td>{r['cvr']}%</td>"
        f"<td>{int(r['installs']) if not pd.isna(r['installs']) else 0}</td>"
        f"<td>{safe_cpa(r['cpi'])}</td>"
        f"<td>¥{r['cost_jpy']/10000:,.1f}万</td>"
        f"<td>{safe_cpa(r['apply_cpa'])}</td>"
        f"<td>{safe_cpa(r['contract_cpa'])}</td>"
        f"<td>¥{r['revenue_man_yen']:,.1f}万</td>"
        f"<td>¥{r['profit_man_yen']:,.1f}万</td>"
        f"<td>¥{r['clear_profit_man_yen']:,.1f}万</td>"
        f"<td>{safe_cpa(r['profit_per_car'])}</td></tr>"
    )

funnel_rows_html = ''
for _, r in df.iterrows():
    funnel_rows_html += (
        f"<tr><td>{r['ym']}</td>"
        f"<td>{int(r['applications'])}</td>"
        f"<td>{int(r['listings'])}</td>"
        f"<td>{int(r['contracts'])}</td>"
        f"<td>{r['listing_rate']}%</td>"
        f"<td>{r['contract_listing_rate']}%</td>"
        f"<td>{r['cvr']}%</td></tr>"
    )

# ============================================================
# HTML生成
# ============================================================
generated_at = datetime.now().strftime('%Y年%m月%d日 %H:%M')

html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LP11 アプリ経由 CPA月次推移</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Noto Sans JP', sans-serif;
    background: #0c0e15;
    color: #e0e0e0;
    padding: 28px 32px;
  }}
  .header {{ margin-bottom: 28px; }}
  .header h1 {{ font-size: 22px; font-weight: 700; color: #fff; margin-bottom: 5px; }}
  .header .meta {{ font-size: 12px; color: #666; }}
  .header .meta span {{ margin-right: 20px; }}

  /* KPIカード */
  .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 28px; }}
  .kpi-card {{
    background: #161922;
    border: 1px solid #252836;
    border-radius: 14px;
    padding: 20px 22px;
    position: relative;
    overflow: hidden;
  }}
  .kpi-card::before {{
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 3px;
  }}
  .kpi-card.blue::before   {{ background: linear-gradient(90deg, #3b82f6, #60a5fa); }}
  .kpi-card.amber::before  {{ background: linear-gradient(90deg, #f59e0b, #fbbf24); }}
  .kpi-card.red::before    {{ background: linear-gradient(90deg, #ef4444, #f87171); }}
  .kpi-card.purple::before {{ background: linear-gradient(90deg, #a855f7, #c084fc); }}
  .kpi-card.gold::before   {{ background: linear-gradient(90deg, #fbbf24, #fcd34d); }}
  .kpi-card.green::before  {{ background: linear-gradient(90deg, #10b981, #34d399); }}
  .kpi-label {{ font-size: 15px; color: #6b7280; font-weight: 700; margin-bottom: 8px; letter-spacing: .05em; text-transform: uppercase; }}
  .kpi-value {{ font-size: 38px; font-weight: 700; color: #fff; line-height: 1; margin-bottom: 10px; }}
  .kpi-value .unit {{ font-size: 18px; font-weight: 400; margin-left: 2px; color: #9ca3af; }}
  .kpi-badge {{
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 11px; font-weight: 600; padding: 3px 8px;
    border-radius: 20px;
  }}
  .kpi-badge.good   {{ background: rgba(52,211,153,.15); color: #34d399; }}
  .kpi-badge.bad    {{ background: rgba(248,113,113,.15); color: #f87171; }}
  .kpi-badge.neutral{{ background: rgba(156,163,175,.12); color: #9ca3af; }}
  .kpi-sub {{ font-size: 11px; color: #4b5563; margin-top: 6px; }}

  /* スーパーリロードボタン */
  .header-box {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 28px; }}
  .reload-btn {{
    background: #252836;
    color: #3b82f6;
    border: 1px solid #3b82f6;
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .reload-btn:hover {{ background: #3b82f6; color: #fff; }}
  .reload-btn:active {{ transform: scale(0.98); }}

  /* 2列チャートレイアウト */
  .charts-2col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
  .charts-3col {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
  @media (max-width: 1024px) {{
    .charts-2col {{ grid-template-columns: 1fr; }}
    .charts-3col {{ grid-template-columns: 1fr; }}
  }}

  /* チャートカード */
  .chart-card {{
    background: #161922; border: 1px solid #252836;
    border-radius: 14px; padding: 22px; margin-bottom: 20px;
  }}
  .chart-title {{ font-size: 14px; font-weight: 600; color: #d1d5db; margin-bottom: 18px; }}
  .chart-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
  canvas {{ max-height: 300px; }}

  /* 注記 */
  .notice {{
    background: rgba(251,191,36,.07);
    border: 1px solid rgba(251,191,36,.3);
    border-radius: 8px; padding: 11px 16px;
    font-size: 12px; color: #fbbf24;
    margin-bottom: 22px; line-height: 1.7;
  }}

  /* テーブル */
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{
    background: #1e2130; color: #6b7280; padding: 11px 14px;
    text-align: right; font-weight: 600; border-bottom: 1px solid #2d3148;
    white-space: nowrap;
  }}
  th:first-child {{ text-align: left; }}
  td {{
    padding: 11px 14px; text-align: right;
    border-bottom: 1px solid #1e2130; color: #cbd5e1;
  }}
  td:first-child {{ text-align: left; font-weight: 600; color: #fff; }}
  tr:hover td {{ background: #1c1f2e; }}
  .cohort-os-panel {{
    border: 1px solid #252836;
    border-radius: 8px;
    overflow: hidden;
    background: #12151e;
  }}
  .mini-table-title {{
    padding: 10px 12px;
    font-size: 12px;
    font-weight: 700;
    color: #e5e7eb;
    border-bottom: 1px solid #252836;
  }}
  .compact-table {{ font-size: 12px; }}
  .compact-table th, .compact-table td {{ padding: 9px 10px; }}
  .empty-cell {{ text-align: center !important; color: #6b7280 !important; }}

  /* カスタムレジェンド（チェックボックス） */
  .custom-legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    margin-bottom: 20px;
    padding: 10px 14px;
    background: #1e2130;
    border-radius: 8px;
  }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    font-size: 13px;
    color: #9ca3af;
    user-select: none;
    transition: color 0.2s;
  }}
  .legend-item:hover {{ color: #fff; }}
  .legend-item input {{
    cursor: pointer;
    accent-color: #3b82f6;
    width: 15px;
    height: 15px;
  }}
  .legend-color {{
    width: 12px;
    height: 4px;
    border-radius: 2px;
  }}
</style>
</head>
<body>

<div class="header-box">
  <div class="header">
    <h1>📱 LP11 アプリ経由 CPA月次レポート</h1>
    <div class="meta">
      <span>集計基準: 申込日ベース</span>
      <span>対象期間: {START_DATE} 〜 {END_DATE}</span>
      <span>データ取得: {generated_at}</span>
    </div>
  </div>
  <button class="reload-btn" onclick="superReload()">
    <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M4 4v5h5M20 20v-5h-5"/><path d="M20 9A9 9 0 0 0 4.1 12M4 15a9 9 0 0 0 15.9-3"/></svg>
    スーパーリロード (キャッシュをクリアして更新)
  </button>
</div>

<div class="notice">
  ⚠️ 広告費: Google Ads アプリDL系キャンペーン（GAC001〜005, GS011）の合計 ｜
  成約: <code>c2b_deal_passed</code>（送客成立）｜
  利益: <code>deal_c2b.手数料</code>（UCP手数料合計）｜
  直近月は成約タイムラグにより過小の場合あり
</div>

<!-- KPIカード -->
<div class="kpi-grid">
  <div class="kpi-card purple">
    <div class="kpi-label">今月({last_ym}) 新規DL数</div>
    <div class="kpi-value">
      {f"{int(last_installs):,}" if last_installs else '-'}
      <span class="unit">DL</span>
    </div>
    {last_installs_est_html}
    <div><span class="kpi-badge {installs_cls}">{installs_diff if installs_diff else '比較なし'}</span></div>
    <div class="kpi-sub">前月({prev_ym}) 比</div>
  </div>
  <div class="kpi-card blue">
    <div class="kpi-label">今月({last_ym}) 広告費</div>
    <div class="kpi-value">
      {f"¥{last_cost/10000:,.1f}" if last_cost else '-'}
      <span class="unit">万</span>
    </div>
    {last_cost_est_html}
    <div><span class="kpi-badge {cost_cls}">{cost_diff if cost_diff else '比較なし'}</span></div>
    <div class="kpi-sub">前月({prev_ym}) 比</div>
  </div>
  <div class="kpi-card purple">
    <div class="kpi-label">今月({last_ym}) CPI (And / iOS)</div>
    <div class="kpi-value" style="font-size: 20px;">
      <span style="font-size: 14px; color: #a78bfa;">And:</span> {f"¥{int(last_cpi_android):,}" if last_cpi_android else '-'} <br>
      <span style="font-size: 14px; color: #a78bfa;">iOS:</span> {f"¥{int(last_cpi_ios):,}" if last_cpi_ios else '-'}
    </div>
    <div class="kpi-sub" style="margin-top: 10px;">
      前月({prev_ym}) And: {f"¥{int(prev_cpi_android):,}" if prev_cpi_android else '-'}
      <br>
      前月({prev_ym}) iOS: {f"¥{int(prev_cpi_ios):,}" if prev_cpi_ios else '-'}
    </div>
  </div>
  <div class="kpi-card amber">
    <div class="kpi-label">今月({last_ym}) 申込CPA</div>
    <div class="kpi-value">
      {f"¥{int(last_acpa):,}" if last_acpa else '-'}
    </div>
    <div style="font-size: 13px; color: #cbd5e1; margin-top: -4px; margin-bottom: 6px;">
      申込数: <span style="font-weight: 600; color: #f59e0b;">{f"{int(last_apps)}件" if last_apps else "-"}</span>
    </div>
    <div><span class="kpi-badge {acpa_cls}">{acpa_diff if acpa_diff else '比較なし'}</span></div>
    <div class="kpi-sub">前月({prev_ym}) 比 / CPA低いほど良い</div>
  </div>
  <div class="kpi-card gold">
    <div class="kpi-label">今月({last_ym}) 1ヶ月内申込率</div>
    <div class="kpi-value">
      {f"{last_cohort_rate:.2f}" if last_cohort_rate else '-'}
      <span class="unit">%</span>
    </div>
    <div><span class="kpi-badge {cohort_rate_cls}">{cohort_rate_diff if cohort_rate_diff else '比較なし'}</span></div>
    <div class="kpi-sub">前月({prev_ym}) 比 / コホート分析数値</div>
  </div>
  <div class="kpi-card red">
    <div class="kpi-label">今月({last_ym}) 成約数</div>
    <div class="kpi-value">
      {f"{int(last_contracts):,}" if last_contracts else '-'}
      <span class="unit">件</span>
    </div>
    <div><span class="kpi-badge {contracts_cls}">{contracts_diff if contracts_diff else '比較なし'}</span></div>
    <div class="kpi-sub">前月({prev_ym}): {f"{int(prev_contracts):,}件" if prev_contracts is not None else '-'}</div>
  </div>
  <div class="kpi-card green">
    <div class="kpi-label">今月({last_ym}) 純利益(売上-広告)</div>
    <div class="kpi-value">
      {f"¥{last_clear_profit:,.1f}" if last_clear_profit else '-'}
      <span class="unit">万</span>
    </div>
    <div><span class="kpi-badge {clear_profit_cls}">{clear_profit_diff if clear_profit_diff else '比較なし'}</span></div>
    <div class="kpi-sub">前月({prev_ym}): {f"¥{prev_clear_profit:,.1f}万" if prev_clear_profit is not None else '-'}</div>
  </div>
</div>

<!-- KPIカード直結: 広告費・売上・利益 -->
<div class="chart-card" style="margin-top:0;">
  <div class="chart-title">広告費・売上・利益（月次）</div>
  <div id="legend-chart1b" class="custom-legend"></div>
  <canvas id="chart1b"></canvas>
</div>

<!-- 3列レイアウト: コホート関連 -->
<div class="charts-3col">
  <!-- 新規DL数 推移 -->
  <div class="chart-card" style="margin-bottom:0;">
    <div class="chart-title">新規DL数 推移</div>
    <div id="legend-chart_dl" class="custom-legend"></div>
    <canvas id="chart_dl" style="max-height:180px;"></canvas>
  </div>

  <!-- Chart Cohort: 登録1ヶ月以内申込率 -->
  <div class="chart-card" style="margin-bottom:0;">
    <div class="chart-title">アプリ登録コホート: 登録から1ヶ月以内の申込率（登録月別）</div>
    <div class="notice" style="margin-bottom:14px; margin-top:0;">
      ⚠️ 分母: UUID新規登録数 ｜ 分子: 登録から30日以内に査定申込みを開始した人数
    </div>
    <div id="legend-chart_cohort" class="custom-legend"></div>
    <canvas id="chart_cohort"></canvas>
  </div>

  <!-- 今月コホート OS別 -->
  <div class="chart-card" style="margin-bottom:0;">
    <div class="chart-title">今月コホート OS別（オーガニック含む全体）</div>
    <div class="cohort-os-panel">
      <table class="compact-table">
        <thead>
          <tr>
            <th>OS</th>
            <th>登録</th>
            <th>1ヶ月内申込</th>
            <th>申込率</th>
            <th>申込CPA</th>
            <th>成約CPA</th>
          </tr>
        </thead>
        <tbody>
          {cohort_os_rows_html}
        </tbody>
      </table>
    </div>
  </div>
</div>

<!-- 2列レイアウト: 有効DL数と既存ユーザー施策 -->
<div class="charts-2col">
  <!-- Chart Store Valid Downloads: GooglePlay / AppStore 有効DL -->
  <div class="chart-card" style="margin-bottom:0;">
    <div class="chart-title">有効ダウンロード数（現在インストール推定）</div>
    <div class="notice" style="margin-bottom:14px; margin-top:0;">
      ⚠️ Google Sheets「実績」集計 ｜ 有効DL数 = 新規DL累計から削除を反映した現在インストール推定
    </div>
    <div class="notice" style="margin-bottom:14px; margin-top:-6px; color:#cbd5e1; border-color:#2d3148; background:#12151e;">
      {last_ym}時点の有効DL数: <strong style="color:#fff;">{store_total_latest:,} DL</strong>（削除反映後）
    </div>
    <div id="legend-chart_store_valid_dl" class="custom-legend"></div>
    <canvas id="chart_store_valid_dl" style="max-height:360px;"></canvas>
  </div>

  <!-- Chart Old Apps: 登録1ヶ月後申込率 -->
  <div class="chart-card" style="margin-bottom:0;">
    <div class="chart-title">既存ユーザー施策: 登録から1ヶ月以上経過している方の申込率（申込月別）</div>
    <div class="notice" style="margin-bottom:14px; margin-top:0;">
      ⚠️ 分母: 有効DL数 (除アンインストール) ｜ 分子: その月に申し込んだ人のうち、登録から30日以上経過していた人数
    </div>
    <div id="legend-chart_old_apps" class="custom-legend"></div>
    <canvas id="chart_old_apps"></canvas>
  </div>
</div>

<!-- Chart CPI: 平均CPI単価 -->
<div class="chart-card">
  <div class="chart-title">平均CPI単価 推移</div>
  <div id="legend-chart_cpi" class="custom-legend"></div>
  <canvas id="chart_cpi"></canvas>
</div>

<!-- 2列レイアウト: CPA -->
<div class="charts-2col">
  <!-- Chart 2: 申込CPA推移 -->
  <div class="chart-card">
    <div class="chart-title">申込CPA 推移（円）</div>
    <div id="legend-chart2" class="custom-legend"></div>
    <canvas id="chart2"></canvas>
  </div>

  <!-- Chart 3: 成約CPA推移 -->
  <div class="chart-card">
    <div class="chart-title">成約CPA 推移（円）</div>
    <div id="legend-chart3" class="custom-legend"></div>
    <canvas id="chart3"></canvas>
  </div>
</div>

<!-- Chart 1A: 申込数・成約数 -->
<div class="chart-card">
  <div class="chart-title">申込数・成約数（月次）</div>
  <div id="legend-chart1a" class="custom-legend"></div>
  <canvas id="chart1a"></canvas>
</div>

<!-- Chart Funnel: 詳細ファネル転換率 -->
<div class="chart-card">
  <div class="chart-title">詳細ファネル転換率 推移（当月除外）</div>
  <div id="legend-chart_funnel" class="custom-legend"></div>
  <canvas id="chart_funnel"></canvas>
</div>



<!-- データテーブル -->
<div class="chart-card">
  <div class="chart-title">月次データ一覧</div>
  <table>
    <thead>
      <tr>
        <th>月</th>
        <th>申込数</th>
        <th>成約数</th>
        <th>CVR</th>
        <th>新規DL数</th>
        <th>平均CPI</th>
        <th>広告費</th>
        <th>申込CPA</th>
        <th>成約CPA</th>
        <th>売上</th>
        <th>落札手数料(参考)</th>
        <th>純利益(売上-広告)</th>
        <th>1台平均手数料</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>

<script>
const months      = {months};
const apps        = {apps};
const contracts   = {contracts};
const cvrData     = {cvr_list};
const installsData= {installs_list};
const cpiData            = {json.dumps(cpi_list)};
const gadsAndroidCpiData = {json.dumps(gads_android_cpi_list)};
const gadsIosCpiData     = {json.dumps(gads_ios_cpi_list)};
const asaCpiData         = {json.dumps(asa_cpi_list)};
const costsMan    = {costs_man};
const revenueMan  = {revenue_man};
const profitMan   = {profit_list};
const clearProfitMan = {clear_profit_list};
const applyCPA    = {apply_cpa_l};
const contractCPA = {contract_cpa_l};
const listingRates = {listing_rates};
const conListingRates = {contract_listing_rates};
const regUsersData = {registered_users};
const avgCVR      = {round(avg_cvr, 1) if avg_cvr else 0};
const avgCPI      = {round(avg_cpi, 0) if avg_cpi else 0};
const avgACPA     = {round(avg_acpa, 0) if avg_acpa else 0};
const avgCCPA     = {round(avg_ccpa, 0) if avg_ccpa else 0};

// コホートデータ
const cohortMonths     = {cohort_months};
const cohortTotal      = {cohort_total};
const cohortRate       = {cohort_rate};
const cohortIncomplete = {["true" if x else "false" for x in cohort_incomplete]};
const avgCohortRate    = {avg_cohort_rate};

// 既存ユーザーデータ
const oldAppsRate       = {old_apps_rate};
const avgOldAppsRate    = {avg_old_apps_rate};

// 有効DL数（現在インストール推定）
const storeValidMonths = {json.dumps(store_valid_months, ensure_ascii=False)};
const activeDownloadUsers = {json.dumps(active_download_users, ensure_ascii=False)};

// KPI目標値
const kpiListingRate    = 28.0;
const kpiConListingRate = 40.0;
const kpiTotalCVR       = 11.2;

const GRID = '#252836';
const TICK = '#6b7280';

function initCustomLegend(chart, containerId) {{
  const container = document.getElementById(containerId);
  if (!container) return;
  
  chart.data.datasets.forEach((dataset, i) => {{
    const label = document.createElement('label');
    label.className = 'legend-item';
    
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = chart.isDatasetVisible(i);
    
    checkbox.addEventListener('change', () => {{
      chart.setDatasetVisibility(i, checkbox.checked);
      chart.update();
    }});
    
    const colorBox = document.createElement('div');
    colorBox.className = 'legend-color';
    colorBox.style.background = dataset.borderColor || dataset.backgroundColor;
    
    const text = document.createTextNode(dataset.label);
    
    label.appendChild(checkbox);
    label.appendChild(colorBox);
    label.appendChild(text);
    container.appendChild(label);
  }});
}}

// Chart 1A: 申込数・成約数
const c1a = new Chart(document.getElementById('chart1a'), {{
  data: {{
    labels: months,
    datasets: [
      {{
        type: 'bar', label: '申込数', data: apps,
        backgroundColor: 'rgba(56,189,248,0.75)', yAxisID: 'y', order: 2
      }},
      {{
        type: 'bar', label: '成約数', data: contracts,
        backgroundColor: 'rgba(52,211,153,0.85)', yAxisID: 'y', order: 1
      }},
      {{
        type: 'line', label: '申込成約率 (%)', data: cvrData,
        borderColor: '#a78bfa', backgroundColor: 'rgba(167,139,250,0.1)',
        yAxisID: 'y1', order: 0, tension: 0.4, pointRadius: 4
      }}
    ]
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x:  {{ ticks: {{ color: TICK }}, grid: {{ color: GRID }} }},
      y:  {{ ticks: {{ color: TICK }}, grid: {{ color: GRID }},
             title: {{ display: true, text: '件数', color: '#4b5563' }} }},
      y1: {{ position: 'right', ticks: {{ color: TICK, callback: v => v + '%' }}, 
             grid: {{ display: false }},
             title: {{ display: true, text: '成約率 (%)', color: '#4b5563' }},
             min: 0 }}
    }}
  }}
}});
initCustomLegend(c1a, 'legend-chart1a');

// Chart 1B: 広告費・売上・利益
const c1b = new Chart(document.getElementById('chart1b'), {{
  data: {{
    labels: months,
    datasets: [
      {{
        type: 'line', label: '広告費（万円）', data: costsMan,
        borderColor: '#818cf8', backgroundColor: 'rgba(129,140,248,0.1)',
        fill: false, tension: 0.4, pointRadius: 4, order: 0
      }},
      {{
        type: 'line', label: '売上（万円）', data: revenueMan,
        borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.1)',
        fill: false, tension: 0.4, pointRadius: 4, order: 0
      }},
      {{
        type: 'bar', label: '利益（万円）', data: clearProfitMan,
        backgroundColor: clearProfitMan.map(v => v >= 0 ? 'rgba(59,130,246,0.6)' : 'rgba(239,68,68,0.6)'),
        borderColor: clearProfitMan.map(v => v >= 0 ? '#3b82f6' : '#ef4444'),
        borderWidth: 1, order: 1
      }}
    ]
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x:  {{ 
        ticks: {{ color: TICK }}, 
        grid: {{ color: GRID }}
      }},
      y:  {{ 
        ticks: {{ color: TICK, callback: v => v+'万' }},
        grid: {{ color: GRID }},
        title: {{ display: true, text: '万円', color: '#4b5563' }}
      }}
    }}
  }}
}});
initCustomLegend(c1b, 'legend-chart1b');

// Chart DL: 新規DL数 推移
const cDL = new Chart(document.getElementById('chart_dl'), {{
  data: {{
    labels: months,
    datasets: [
      {{
        type: 'bar', label: '新規DL数', data: installsData,
        borderColor: 'rgba(167,139,250,0.95)',
        backgroundColor: 'rgba(167,139,250,0.72)',
        borderWidth: 1,
        yAxisID: 'y'
      }}
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x:  {{ ticks: {{ color: TICK }}, grid: {{ color: GRID }} }},
      y:  {{ ticks: {{ color: TICK }}, grid: {{ color: GRID }},
             title: {{ display: true, text: 'DL数', color: '#4b5563' }} }}
    }}
  }}
}});
initCustomLegend(cDL, 'legend-chart_dl');

// Chart CPI: 平均CPI単価
const cCPI = new Chart(document.getElementById('chart_cpi'), {{
  type: 'line',
  data: {{
    labels: months,
    datasets: [
      {{
        label: '全体CPI（円）', data: cpiData,
        borderColor: '#f472b6', backgroundColor: 'rgba(244,114,182,0.08)',
        fill: true, tension: 0.4, pointRadius: 5, spanGaps: true
      }},
      {{
        label: 'Google Ads Android CPI（円）',
        data: gadsAndroidCpiData,
        borderColor: '#4ade80', backgroundColor: 'rgba(74,222,128,0.08)',
        fill: false, tension: 0.4, pointRadius: 5, spanGaps: true
      }},
      {{
        label: 'Google Ads iOS CPI（円）',
        data: gadsIosCpiData,
        borderColor: '#fb923c', backgroundColor: 'rgba(251,146,60,0.08)',
        fill: false, tension: 0.4, pointRadius: 5, spanGaps: true
      }}
    ]
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x:  {{ ticks: {{ color: TICK }}, grid: {{ color: GRID }} }},
      y:  {{ ticks: {{ color: TICK, callback: v => '¥'+v.toLocaleString() }}, grid: {{ color: GRID }},
             title: {{ display: true, text: '円', color: '#4b5563' }} }}
    }}
  }}
}});
initCustomLegend(cCPI, 'legend-chart_cpi');

// Chart 2: 申込CPA
const c2 = new Chart(document.getElementById('chart2'), {{
  type: 'line',
  data: {{
    labels: months,
    datasets: [
      {{
        label: '申込CPA（円）', data: applyCPA,
        borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.1)',
        fill: true, tension: 0.4, pointRadius: 5, pointBackgroundColor: '#f59e0b'
      }},
      {{
        label: '全期間平均申込CPA（円）',
        data: months.map(() => avgACPA),
        borderColor: '#6b7280', borderDash: [6,4],
        pointRadius: 0, fill: false
      }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: TICK }}, grid: {{ color: GRID }} }},
      y: {{ ticks: {{ color: TICK, callback: v => '¥' + v.toLocaleString() }}, grid: {{ color: GRID }} }}
    }}
  }}
}});
initCustomLegend(c2, 'legend-chart2');

// Chart 3: 成約CPA
const c3 = new Chart(document.getElementById('chart3'), {{
  type: 'line',
  data: {{
    labels: months,
    datasets: [
      {{
        label: '成約CPA（円）', data: contractCPA,
        borderColor: '#f87171', backgroundColor: 'rgba(248,113,113,0.1)',
        fill: true, tension: 0.4, pointRadius: 5, pointBackgroundColor: '#f87171'
      }},
      {{
        label: '全期間平均成約CPA（円）',
        data: months.map(() => avgCCPA),
        borderColor: '#6b7280', borderDash: [6,4],
        pointRadius: 0, fill: false
      }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: TICK }}, grid: {{ color: GRID }} }},
      y: {{ ticks: {{ color: TICK, callback: v => '¥' + v.toLocaleString() }}, grid: {{ color: GRID }} }}
    }}
  }}
}});
initCustomLegend(c3, 'legend-chart3');

// Chart Funnel: 詳細ファネル転換率 (当月除外)
const funnelMonthsCut = months.slice(0, -1);
const listingRatesCut = listingRates.slice(0, -1);
const conListingRatesCut = conListingRates.slice(0, -1);
const cvrDataCut = cvrData.slice(0, -1);

const cFunnel = new Chart(document.getElementById('chart_funnel'), {{
  type: 'line',
  data: {{
    labels: funnelMonthsCut,
    datasets: [
      {{
        label: '出品率 (出品/申込)', data: listingRatesCut,
        borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)',
        fill: false, tension: 0.4, pointRadius: 5
      }},
      {{
        label: '出品成約率 (成約/出品)', data: conListingRatesCut,
        borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.1)',
        fill: false, tension: 0.4, pointRadius: 5
      }},
      {{
        label: '申込成約率 (成約/申込)', data: cvrDataCut,
        borderColor: '#a78bfa', backgroundColor: 'rgba(167,139,250,0.1)',
        fill: false, tension: 0.4, pointRadius: 5
      }},
      {{
        label: 'KPI出品率 (28%)', data: funnelMonthsCut.map(() => kpiListingRate),
        borderColor: 'rgba(59,130,246,0.4)', borderDash: [6,4], borderWidth: 1.5, pointRadius: 0, fill: false
      }},
      {{
        label: 'KPI出品成約率 (40%)', data: funnelMonthsCut.map(() => kpiConListingRate),
        borderColor: 'rgba(16,185,129,0.4)', borderDash: [6,4], borderWidth: 1.5, pointRadius: 0, fill: false
      }},
      {{
        label: 'KPI成約率 (11.2%)', data: funnelMonthsCut.map(() => kpiTotalCVR),
        borderColor: 'rgba(167,139,250,0.4)', borderDash: [6,4], borderWidth: 1.5, pointRadius: 0, fill: false
      }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: TICK }}, grid: {{ color: GRID }} }},
      y: {{ ticks: {{ color: TICK, callback: v => v + '%' }}, grid: {{ color: GRID }},
             title: {{ display: true, text: '転換率 (%)', color: '#4b5563' }} }}
    }}
  }}
}});
initCustomLegend(cFunnel, 'legend-chart_funnel');

// Chart Cohort: 登録1ヶ月以内申込率
const cohortPointColors = cohortIncomplete.map(inc => inc ? 'rgba(251,191,36,0.35)' : '#fbbf24');
const cohortPointRadius = cohortIncomplete.map(inc => inc ? 4 : 5);

const cCohort = new Chart(document.getElementById('chart_cohort'), {{
  data: {{
    labels: cohortMonths,
    datasets: [
      {{
        type: 'line',
        label: '登録1ヶ月以内申込率 (%)',
        data: cohortRate,
        borderColor: '#fbbf24',
        backgroundColor: 'rgba(251,191,36,0.1)',
        fill: true,
        tension: 0.4,
        pointRadius: cohortPointRadius,
        pointBackgroundColor: cohortPointColors,
        pointBorderColor: cohortPointColors,
        yAxisID: 'y',
        order: 1
      }},
      {{
        type: 'line',
        label: '全期間平均申込率 (%)',
        data: cohortMonths.map(() => avgCohortRate),
        borderColor: '#6b7280',
        borderDash: [6, 4],
        borderWidth: 1.5,
        pointRadius: 0,
        fill: false,
        yAxisID: 'y',
        order: 1
      }}
    ]
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x:  {{ ticks: {{ color: TICK }}, grid: {{ color: GRID }} }},
      y:  {{
        position: 'left',
        ticks: {{ color: TICK, callback: v => v + '%' }},
        grid: {{ color: GRID }},
        title: {{ display: true, text: '申込率 (%)', color: '#4b5563' }},
        min: 0
      }}
    }}
  }}
}});
initCustomLegend(cCohort, 'legend-chart_cohort');

// Chart Old Apps: 既存ユーザー申込割合
const oldAppsPointColors = cohortIncomplete.map(inc => inc === "true" ? 'rgba(168,85,247,0.35)' : '#a855f7');
const oldAppsPointRadius = cohortIncomplete.map(inc => inc === "true" ? 4 : 5);

const cOldApps = new Chart(document.getElementById('chart_old_apps'), {{
  data: {{
    labels: cohortMonths,
    datasets: [
      {{
        type: 'line', 
        label: '1ヶ月超経過の申込割合（%）', 
        data: oldAppsRate,
        borderColor: '#a855f7', 
        backgroundColor: 'rgba(168,85,247,0.15)',
        fill: true, 
        tension: 0.4, 
        pointRadius: oldAppsPointRadius, 
        pointBorderColor: oldAppsPointColors,
        yAxisID: 'y',
        order: 1
      }},
      {{
        type: 'line',
        label: '全期間平均申込率 (%)',
        data: cohortMonths.map(() => avgOldAppsRate),
        borderColor: '#6b7280',
        borderDash: [6, 4],
        borderWidth: 1.5,
        pointRadius: 0,
        fill: false,
        yAxisID: 'y',
        order: 1
      }}
    ]
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: TICK }}, grid: {{ color: GRID }} }},
      y: {{ position: 'left', beginAtZero: true, 
               ticks: {{ color: TICK, callback: v => v + '%' }}, 
               grid: {{ color: GRID }},
               title: {{ display: true, text: '申込率 (%)', color: '#4b5563' }} }}
    }}
  }}
}});
initCustomLegend(cOldApps, 'legend-chart_old_apps');

// Chart Store Valid Downloads: active installs estimate
const cStoreValidDL = new Chart(document.getElementById('chart_store_valid_dl'), {{
  type: 'bar',
  data: {{
    labels: storeValidMonths,
    datasets: [
      {{
        label: '有効DL数（現在インストール推定）',
        data: activeDownloadUsers,
        backgroundColor: 'rgba(74,222,128,0.82)',
        borderColor: 'rgba(74,222,128,0.95)',
        borderWidth: 1
      }}
    ]
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: TICK }}, grid: {{ color: GRID }} }},
      y: {{
        beginAtZero: true,
        ticks: {{ color: TICK, precision: 0 }},
        grid: {{ color: GRID }},
        title: {{ display: true, text: '有効DL数', color: '#4b5563' }}
      }}
    }}
  }}
}});
initCustomLegend(cStoreValidDL, 'legend-chart_store_valid_dl');

function superReload() {{
    // クエリパラメータにタイムスタンプを付与してキャッシュを回避
    const url = new URL(window.location.href);
    url.searchParams.set('reload', new Date().getTime());
    window.location.href = url.toString();
}}
</script>
</body>
</html>"""

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lp11_cpa_report.html')
with open(OUT, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"\nHTMLレポート生成: {OUT}")
try:
    webbrowser.open(f'file:///{OUT}')
except Exception:
    pass
