import argparse
import json
from datetime import datetime
from pathlib import Path

from google.cloud import bigquery


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_one(client: bigquery.Client, query: str) -> dict:
    rows = list(client.query(query).result())
    if not rows:
        return {}
    return dict(rows[0].items())


def fetch_many(client: bigquery.Client, query: str) -> list[dict]:
    return [dict(row.items()) for row in client.query(query).result()]


def js_dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def build_queries(config: dict) -> dict:
    project_id = config["project_id"]
    dataset = config["dataset"]
    subscription = f"`{project_id}.{dataset}.{config['subscription_table']}`"
    notification = f"`{project_id}.{dataset}.{config['notification_table']}`"
    tz = config.get("timezone", "Asia/Tokyo")
    months = int(config.get("top_series_months", 6))
    notifications = int(config.get("bottom_series_notifications", 6))
    fallback_dl = int(config.get("fallback_cumulative_effective_dl", 33855))

    current = f"""
WITH latest_snapshot AS (
  SELECT MAX(snapshot_date) AS snapshot_date
  FROM {subscription}
),
snapshot_kpi AS (
  SELECT
    s.snapshot_date,
    COUNT(1) AS os_registered,
    COUNTIF(notification_types > 0) AS subscribed_count,
    COUNTIF(unsubscribed_at IS NOT NULL OR invalid_identifier) AS unreachable_count,
    COUNTIF(notification_types > 0 AND NOT invalid_identifier AND unsubscribed_at IS NULL) AS effective_target_count
  FROM {subscription} s
  JOIN latest_snapshot l
    ON s.snapshot_date = l.snapshot_date
  GROUP BY s.snapshot_date
),
latest_notification AS (
  SELECT
    DATE(completed_at, '{tz}') AS notification_date,
    COUNT(1) AS notification_count,
    SUM(successful) AS successful_count,
    SUM(failed) AS failed_count,
    SUM(converted) AS converted_count,
    CAST(NULL AS INT64) AS click_count,
    ARRAY_AGG(name ORDER BY completed_at DESC LIMIT 1)[OFFSET(0)] AS name
  FROM {notification}
  WHERE completed_at IS NOT NULL
  GROUP BY notification_date
  QUALIFY ROW_NUMBER() OVER (ORDER BY notification_date DESC) = 1
)
SELECT
  FORMAT_DATE('%Y-%m', sk.snapshot_date) AS report_month,
  FORMAT_DATE('%Y/%m/%d', sk.snapshot_date) AS latest_snapshot_date,
  FORMAT_DATE('%Y/%m/%d', ln.notification_date) AS latest_notification_date,
  {fallback_dl} AS cumulative_effective_dl,
  sk.os_registered,
  sk.subscribed_count,
  sk.unreachable_count,
  sk.effective_target_count,
  ln.notification_count,
  ln.successful_count,
  ln.failed_count,
  ln.converted_count,
  ln.click_count,
  ln.name AS notification_name
FROM snapshot_kpi sk
LEFT JOIN latest_notification ln
  ON TRUE
"""

    top_series = f"""
WITH daily AS (
  SELECT
    snapshot_date,
    COUNT(1) AS os_registered,
    COUNTIF(notification_types > 0) AS subscribed_count
  FROM {subscription}
  GROUP BY snapshot_date
),
monthly AS (
  SELECT
    snapshot_date,
    FORMAT_DATE('%Y-%m', snapshot_date) AS period,
    os_registered,
    subscribed_count,
    effective_target_count,
    ROW_NUMBER() OVER (
      PARTITION BY FORMAT_DATE('%Y-%m', snapshot_date)
      ORDER BY snapshot_date DESC
    ) AS rn
  FROM (
    SELECT
      snapshot_date,
      COUNT(1) AS os_registered,
      COUNTIF(notification_types > 0) AS subscribed_count,
      COUNTIF(notification_types > 0 AND NOT invalid_identifier AND unsubscribed_at IS NULL) AS effective_target_count
    FROM {subscription}
    GROUP BY snapshot_date
  )
)
SELECT
  period,
  os_registered,
  subscribed_count,
  effective_target_count
FROM monthly
WHERE rn = 1
ORDER BY period DESC
LIMIT {months}
"""

    bottom_series = f"""
WITH notif AS (
  SELECT
    DATE(completed_at, '{tz}') AS notification_date,
    COUNT(1) AS notification_count,
    SUM(successful) AS successful_count,
    SUM(failed) AS failed_count,
    SUM(converted) AS converted_count,
    CAST(NULL AS INT64) AS click_count
  FROM {notification}
  WHERE completed_at IS NOT NULL
  GROUP BY notification_date
)
SELECT
  FORMAT_DATE('%Y-%m-%d', n.notification_date) AS period,
  n.notification_count,
  n.successful_count,
  n.failed_count,
  n.converted_count,
  n.click_count
FROM notif n
ORDER BY n.notification_date DESC
LIMIT {notifications}
"""

    return {
        "current": current,
        "top_series": top_series,
        "bottom_series": bottom_series,
    }


def build_payload(config: dict, current: dict, top_series: list[dict], bottom_series: list[dict]) -> dict:
    now = datetime.now().strftime("%Y-%m-%d")

    entry = {
        "month": current.get("report_month") or now[:7],
        "date": current.get("latest_snapshot_date") or now.replace("-", "/"),
        "notificationDate": current.get("latest_notification_date"),
        "cumulativeEffectiveDl": int(current.get("cumulative_effective_dl") or config.get("fallback_cumulative_effective_dl", 33855)),
        "osRegistered": int(current.get("os_registered") or 0),
        "subscribed": int(current.get("subscribed_count") or 0),
        "effectiveTarget": int(current.get("effective_target_count") or 0),
        "unreachable": int(current.get("unreachable_count") or 0),
        "notifications": int(current.get("notification_count") or 0),
        "successful": int(current.get("successful_count") or 0),
        "failed": int(current.get("failed_count") or 0),
        "converted": int(current.get("converted_count") or 0),
        "clicks": None,
        "signups": None,
    }

    top = [
        {
            "month": row["period"],
            "osRegistered": int(row.get("os_registered") or 0),
            "subscribed": int(row.get("subscribed_count") or 0),
            "effectiveTarget": int(row.get("effective_target_count") or 0),
        }
        for row in reversed(top_series)
    ]

    bottom = [
        {
            "month": row["period"],
            "notifications": int(row.get("notification_count") or 0),
            "successful": int(row.get("successful_count") or 0),
            "failed": int(row.get("failed_count") or 0),
            "converted": int(row.get("converted_count") or 0),
            "clicks": None,
            "signups": None,
        }
        for row in reversed(bottom_series)
    ]

    return {
        "reportMonth": entry["month"],
        "generatedDate": now,
        "updatedDate": current.get("latest_snapshot_date", now).replace("/", "-"),
        "latestNotificationDate": (current.get("latest_notification_date") or "").replace("/", "-"),
        "summaryNote": config.get("summary_note", ""),
        "entry": entry,
        "topSeries": top,
        "bottomSeries": bottom,
        "copyReview": config.get("copy_review", {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="dashboard_config.json")
    parser.add_argument("--output", default="push_notification_dashboard_data.js")
    args = parser.parse_args()

    config_path = Path(args.config)
    output_path = Path(args.output)
    config = load_config(config_path)
    client = bigquery.Client(project=config["project_id"])

    queries = build_queries(config)
    current = fetch_one(client, queries["current"])
    top_series = fetch_many(client, queries["top_series"])
    bottom_series = fetch_many(client, queries["bottom_series"])
    payload = build_payload(config, current, top_series, bottom_series)

    output = "window.__PUSH_DASHBOARD_DATA__ = " + js_dumps(payload) + ";\n"
    output_path.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
