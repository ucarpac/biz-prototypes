import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def extract_value(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def load_dashboard_meta(data_path: Path) -> dict[str, str]:
    text = read_text(data_path)
    return {
        "reportMonth": extract_value(r'["\']?reportMonth["\']?\s*:\s*"([^"]+)"', text) or "unknown",
        "updatedDate": extract_value(r'["\']?updatedDate["\']?\s*:\s*"([^"]+)"', text) or "",
    }


def load_history_manifest(history_js_path: Path) -> list[dict]:
    if not history_js_path.exists():
        return []

    text = read_text(history_js_path)
    match = re.search(r"=\s*(\[[\s\S]*\])\s*;\s*$", text)
    if not match:
        return []

    return json.loads(match.group(1))


def save_history_manifest(history_js_path: Path, items: list[dict]) -> None:
    payload = "window.__PUSH_DASHBOARD_HISTORY__ = " + json.dumps(items, ensure_ascii=False, indent=2) + ";\n"
    write_text(history_js_path, payload)


def patch_snapshot_index(index_path: Path) -> None:
    text = read_text(index_path)
    text = text.replace('src="../../auth.js"', 'src="../../../../auth.js"')
    text = text.replace('href="../"', 'href="../../../"')
    write_text(index_path, text)


def archive_snapshot(report_dir: Path) -> dict[str, str]:
    data_path = report_dir / "push_notification_dashboard_data.js"
    meta = load_dashboard_meta(data_path)
    month = meta["reportMonth"]

    history_root = report_dir / "history"
    snapshot_dir = history_root / month
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    files_to_copy = [
        "index.html",
        "push_notification_dashboard_data.js",
        "dashboard_config.json",
        "dashboard_history.js",
    ]
    for name in files_to_copy:
        src = report_dir / name
        if src.exists():
            shutil.copy2(src, snapshot_dir / name)

    patch_snapshot_index(snapshot_dir / "index.html")

    history_js_path = report_dir / "dashboard_history.js"
    items = load_history_manifest(history_js_path)
    saved_at = datetime.now().strftime("%Y-%m-%d")
    entry = {
        "folder": month,
        "label": month,
        "savedAt": saved_at,
        "updatedDate": meta["updatedDate"],
    }

    items = [item for item in items if item.get("folder") != month]
    items.insert(0, entry)
    save_history_manifest(history_js_path, items)

    shutil.copy2(history_js_path, snapshot_dir / "dashboard_history.js")
    return entry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report-dir",
        default="reports/push-notification-20260528-p7k4m2q8",
        help="Path to the dashboard directory.",
    )
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    entry = archive_snapshot(report_dir)
    print(json.dumps(entry, ensure_ascii=False))


if __name__ == "__main__":
    main()
