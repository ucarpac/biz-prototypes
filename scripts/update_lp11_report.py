#!/usr/bin/env python3
"""Generate and publish the LP11 CPA report inside this repository."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
GENERATED_HTML = SCRIPT_DIR / "lp11_cpa_report.html"
REPORT_HTML = REPO_ROOT / "reports" / "lp11-cpa-report-20260410" / "index.html"


AUTH_BLOCK = """  <script>
    window.PROTO_AUTH_CONFIG = {
      title: 'LP11 アプリ経由 CPA月次レポート',
      subtitle: '分析レポート閲覧用の認証です。認証状態は 24 時間保持されます。'
    };
  </script>
  <script src="../../auth.js"></script>
  <div style="position:sticky;top:0;z-index:20;background:rgba(25,28,34,0.96);backdrop-filter:blur(10px);border-bottom:1px solid #252836;padding:10px 16px;font-family:'Noto Sans JP',sans-serif;">
    <a href="../" style="color:#3b82f6;text-decoration:none;font-weight:800;">&larr; Reports に戻る</a>
  </div>
"""


def run(cmd: list[str], cwd: Path) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def extract_between(text: str, start: str, end: str) -> str | None:
    start_pos = text.find(start)
    if start_pos < 0:
        return None
    end_pos = text.find(end, start_pos)
    if end_pos < 0:
        return None
    return text[start_pos:end_pos]


def insert_before(text: str, marker: str, block: str | None) -> str:
    if not block or marker not in text:
        return text
    return text.replace(marker, block.rstrip() + "\n\n" + marker, 1)


def preserve_manual_sections(content: str, existing: str) -> str:
    """Keep manually added LP11 visual sections until the generator owns them."""
    if not existing:
        return content

    if ".spend-month-grid" not in content:
        css_block = extract_between(existing, "  .spend-breakdown {", "</style>")
        content = insert_before(content, "</style>", css_block)

    data_table_marker = "<!-- データテーブル -->"
    if "chart_ad_spend_mix_prev" not in content:
        html_block = extract_between(existing, "<!-- Chart Ad Spend Mix:", data_table_marker)
        content = insert_before(content, data_table_marker, html_block)

    if "const adSpendPrevMix" not in content:
        data_block = extract_between(existing, "const adSpendPrevMix", "const GRID = '#252836';")
        content = insert_before(content, "const GRID = '#252836';", data_block)

    if "createSpendDoughnut('chart_ad_spend_mix_prev'" not in content:
        render_block = extract_between(existing, "// Chart Ad Spend Mix:", "// Chart Cohort:")
        content = insert_before(content, "// Chart Cohort:", render_block)

    return content


def main() -> int:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Generate LP11 report")
    run([sys.executable, str(SCRIPT_DIR / "bq_lp11_report.py")], cwd=SCRIPT_DIR)

    if not GENERATED_HTML.exists():
        raise FileNotFoundError(f"Generated HTML not found: {GENERATED_HTML}")

    content = GENERATED_HTML.read_text(encoding="utf-8")
    content = content.replace("<body>", "<body>" + AUTH_BLOCK, 1)

    existing = REPORT_HTML.read_text(encoding="utf-8") if REPORT_HTML.exists() else ""
    content = preserve_manual_sections(content, existing)

    REPORT_HTML.parent.mkdir(parents=True, exist_ok=True)
    REPORT_HTML.write_text(content, encoding="utf-8")
    print(f"Updated {REPORT_HTML.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
