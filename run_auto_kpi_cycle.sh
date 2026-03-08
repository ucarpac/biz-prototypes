#!/usr/bin/env bash
# run_auto_kpi_cycle.sh - Auto KPI テーマ選定+レポート生成ラッパー（Mac用）
#
# PowerShell版 run_auto_kpi_cycle.ps1 の bash変換
#
# 使い方:
#   ./run_auto_kpi_cycle.sh --mode daily
#   ./run_auto_kpi_cycle.sh --mode weekly --service ucarpac-web
#   ./run_auto_kpi_cycle.sh --complete --status done
#   ./run_auto_kpi_cycle.sh --mode daily --allow-weekend
#
set -euo pipefail

# === デフォルト値 ===
MODE="daily"
SERVICE="ucarpac-app"
COMPLETE=false
STATUS="done"
WEEKDAYS_ONLY=true
ALLOW_WEEKEND=false
SELECT_ONLY=false
DATE_ARG=""
ROOT="/Users/ucarpacadmin/clawd"

# === 引数パース ===
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="$2"
      if [[ "$MODE" != "daily" && "$MODE" != "weekly" ]]; then
        echo "エラー: --mode は daily または weekly のみ" >&2
        exit 1
      fi
      shift 2
      ;;
    --service)
      SERVICE="$2"
      shift 2
      ;;
    --complete)
      COMPLETE=true
      shift
      ;;
    --status)
      STATUS="$2"
      shift 2
      ;;
    --weekday-only)
      WEEKDAYS_ONLY=true
      shift
      ;;
    --allow-weekend)
      ALLOW_WEEKEND=true
      shift
      ;;
    --select-only)
      SELECT_ONLY=true
      shift
      ;;
    --date)
      DATE_ARG="$2"
      shift 2
      ;;
    --root)
      ROOT="$2"
      shift 2
      ;;
    -h|--help)
      echo "使い方: $0 [オプション]"
      echo ""
      echo "オプション:"
      echo "  --mode daily|weekly     選定モード（デフォルト: daily）"
      echo "  --service SERVICE       対象サービス（デフォルト: ucarpac-app）"
      echo "  --complete              履歴反映モード"
      echo "  --status STATUS         ステータス（デフォルト: done）"
      echo "  --weekday-only          平日のみ実行（デフォルト: 有効）"
      echo "  --allow-weekend         土日も実行を許可"
      echo "  --select-only           テーマ選定+レポート生成のみ（プロトタイプ/push/通知はスキップ）"
      echo "  --date YYYY-MM-DD       日付を指定"
      echo "  --root PATH             ルートディレクトリ"
      exit 0
      ;;
    *)
      echo "不明なオプション: $1" >&2
      exit 1
      ;;
  esac
done

# === パス定義 ===
PYTHON="/usr/bin/python3"
SELECTOR="${ROOT}/skills/public/overnight-work/scripts/auto_kpi_selector.py"
REPORT_BUILDER="${ROOT}/skills/public/overnight-work/scripts/build_auto_kpi_report.py"
KPI_FETCHER="${ROOT}/skills/public/overnight-work/scripts/fetch_kpi_data.py"
THEMES="${ROOT}/prototypes/ops/auto-kpi/kpi-theme-pool.json"
HISTORY="${ROOT}/prototypes/ops/auto-kpi/kpi-history.jsonl"
SELECTION="${ROOT}/prototypes/ops/auto-kpi/last-selection.json"
PROMPT="${ROOT}/prototypes/ops/auto-kpi/last-selection-prompt.md"
OPS_DIR="${ROOT}/prototypes/ops/auto-kpi"
SCRIPTS_DIR="${ROOT}/skills/public/overnight-work/scripts"
FEEDBACK_SUMMARY="${OPS_DIR}/feedback-summary.json"
REPORT_URL="https://ucarpac.github.io/biz-prototypes/ops/auto-kpi/"
LOG_DIR="${ROOT}/prototypes/logs"
LOG_FILE="${LOG_DIR}/auto-kpi-$(date +%Y-%m-%d).log"

# === ログディレクトリ作成 ===
mkdir -p "${LOG_DIR}"

# === ログ関数 ===
log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
  echo "$msg"
  echo "$msg" >> "${LOG_FILE}"
}

# === 前提チェック ===
if [[ ! -f "$SELECTOR" ]]; then
  log "エラー: Selector script not found: ${SELECTOR}"
  exit 1
fi
if [[ ! -f "$REPORT_BUILDER" ]]; then
  log "エラー: Report builder not found: ${REPORT_BUILDER}"
  exit 1
fi
if [[ ! -f "$THEMES" ]]; then
  log "エラー: Theme pool not found: ${THEMES}"
  exit 1
fi

# === 平日判定 ===
if [[ -n "$DATE_ARG" ]]; then
  RUN_DATE="$DATE_ARG"
  # macOS date で曜日を取得（0=日, 6=土）
  DOW=$(date -j -f "%Y-%m-%d" "$DATE_ARG" "+%w" 2>/dev/null || date -d "$DATE_ARG" "+%w" 2>/dev/null || echo "")
else
  RUN_DATE=$(date +%Y-%m-%d)
  DOW=$(date +%w)
fi

if [[ "$WEEKDAYS_ONLY" == "true" && "$ALLOW_WEEKEND" == "false" ]]; then
  if [[ "$DOW" == "0" || "$DOW" == "6" ]]; then
    log "スキップ: ${RUN_DATE} は週末です（--allow-weekend で解除可能）"
    exit 0
  fi
fi

log "=== Auto KPI Cycle 開始 ==="
log "Mode: ${MODE} | Service: ${SERVICE} | Date: ${RUN_DATE}"

# === タイムバジェット管理 ===
SCRIPT_START=$(date +%s)
TOTAL_BUDGET=1800   # 30分（OpenClaw cronの2400秒から600秒のマージン）
NOTIFY_RESERVE=60   # git push + Slack通知用に60秒確保

remaining_seconds() {
  local elapsed=$(( $(date +%s) - SCRIPT_START ))
  echo $(( TOTAL_BUDGET - elapsed ))
}

# === Phase 1: KPIデータ取得（必須） ===
DATA_OK=false
if [[ -f "${KPI_FETCHER}" ]]; then
  log "KPIデータ取得中..."
  if "${PYTHON}" "${KPI_FETCHER}" \
    --ops-dir "${OPS_DIR}" \
    2>&1 | tee -a "${LOG_FILE}"; then
    DATA_OK=true
    log "KPIデータ取得完了"
  else
    log "KPIデータ取得失敗"
  fi
else
  log "警告: fetch_kpi_data.py が見つかりません（データ取得スキップ）"
fi

# === 日付引数の組み立て ===
DATE_ARGS=()
if [[ -n "$DATE_ARG" ]]; then
  DATE_ARGS+=("--date" "$DATE_ARG")
fi

WEEKDAY_ARGS=()
if [[ "$WEEKDAYS_ONLY" == "true" && "$ALLOW_WEEKEND" == "false" ]]; then
  WEEKDAY_ARGS+=("--weekday-only")
fi

# === 履歴反映モード ===
if [[ "$COMPLETE" == "true" ]]; then
  log "履歴反映モード: status=${STATUS}"
  "${PYTHON}" "${SELECTOR}" \
    --themes "${THEMES}" \
    --history "${HISTORY}" \
    "${DATE_ARGS[@]+"${DATE_ARGS[@]}"}" \
    "${WEEKDAY_ARGS[@]+"${WEEKDAY_ARGS[@]}"}" \
    --selection-json "${SELECTION}" \
    --append-history \
    --status "${STATUS}" \
    2>&1 | tee -a "${LOG_FILE}"

  "${PYTHON}" "${REPORT_BUILDER}" \
    --ops-dir "${OPS_DIR}" \
    --base-url "${REPORT_URL}" \
    2>&1 | tee -a "${LOG_FILE}"

  log "履歴反映完了: ${HISTORY}"
  exit 0
fi

# === テーマ選定モード ===
COOLDOWN=7
if [[ "$MODE" == "weekly" ]]; then
  COOLDOWN=21
fi

log "テーマ選定実行: cooldown=${COOLDOWN}日"

# === フィードバック収集（GAS Web App → feedback-summary.json） ===
log "フィードバック収集開始..."
"${PYTHON}" "${SCRIPTS_DIR}/collect_feedback.py" "${FEEDBACK_SUMMARY}" 2>&1 | while read -r line; do log "  $line"; done

FEEDBACK_ARGS=()
if [[ -f "${FEEDBACK_SUMMARY}" ]]; then
  FEEDBACK_ARGS+=("--feedback-json" "${FEEDBACK_SUMMARY}")
  log "フィードバックデータ検出: ${FEEDBACK_SUMMARY}"
fi
"${PYTHON}" "${SELECTOR}" \
  --themes "${THEMES}" \
  --history "${HISTORY}" \
  --service "${SERVICE}" \
  --mode "${MODE}" \
  --cooldown-days "${COOLDOWN}" \
  --output-json "${SELECTION}" \
  --output-prompt "${PROMPT}" \
  "${DATE_ARGS[@]+"${DATE_ARGS[@]}"}" \
  "${WEEKDAY_ARGS[@]+"${WEEKDAY_ARGS[@]}"}" \
  "${FEEDBACK_ARGS[@]+"${FEEDBACK_ARGS[@]}"}" \
  2>&1 | tee -a "${LOG_FILE}"

# === レポート再生成 ===
log "レポート再生成中..."
"${PYTHON}" "${REPORT_BUILDER}" \
  --ops-dir "${OPS_DIR}" \
  --base-url "${REPORT_URL}" \
  2>&1 | tee -a "${LOG_FILE}"

log "=== レポート再生成完了 ==="

# === --select-only の場合はここで終了 ===
if [[ "$SELECT_ONLY" == "true" ]]; then
  log "=== select-only モード: テーマ選定+レポート生成完了 ==="
  log "Selection JSON: ${SELECTION}"
  log "Prompt file:    ${PROMPT}"
  log "Report URL:     ${REPORT_URL}"
  log "Log file:       ${LOG_FILE}"

  # 選定結果のサマリーをJSON形式で出力（エージェントが読みやすい形式）
  SELECTED_SERVICE=$(/usr/bin/python3 -c "import json; d=json.load(open('${SELECTION}')); print(d.get('selected',{}).get('service','ucarpac-app'))" 2>/dev/null || echo "ucarpac-app")
  SELECTED_ID=$(/usr/bin/python3 -c "import json; d=json.load(open('${SELECTION}')); print(d.get('selected',{}).get('id','unknown'))" 2>/dev/null || echo "unknown")
  SELECTED_TITLE=$(/usr/bin/python3 -c "import json; d=json.load(open('${SELECTION}')); print(d.get('selected',{}).get('title',''))" 2>/dev/null || echo "")

  echo ""
  echo "=== エージェント向け指示 ==="
  echo "SELECTED_SERVICE=${SELECTED_SERVICE}"
  echo "SELECTED_ID=${SELECTED_ID}"
  echo "SELECTED_TITLE=${SELECTED_TITLE}"
  echo "OUTPUT_DIR=${ROOT}/prototypes/${SELECTED_SERVICE}"
  echo "PROMPT_FILE=${PROMPT}"
  echo ""
  echo "--- 選定プロンプト ---"
  cat "${PROMPT}"
  exit 0
fi

# === Phase 2: Git push (KPIレポート) + Slack通知 ===
# データ取得成功時のみ実行。プロトタイプ生成前に完了させる。
PROTO_DIR="${ROOT}/prototypes"
REAL_PROTO=$("${PYTHON}" -c "import os; print(os.path.realpath('${PROTO_DIR}'))" 2>/dev/null || echo "${PROTO_DIR}")

setup_git_credential() {
  if command -v gh &>/dev/null; then
    git config credential.helper '!gh auth git-credential'
  else
    local token=$(grep -A1 'oauth_token' "${HOME}/.config/gh/hosts.yml" 2>/dev/null | grep -oE 'gho_[A-Za-z0-9]+' | head -1 || echo "")
    if [[ -n "$token" ]]; then
      git config credential.helper 'store'
      echo "https://ucarpac-developer:${token}@github.com" > "${HOME}/.git-credentials"
    fi
  fi
}

if [[ "$DATA_OK" == "true" && -d "${REAL_PROTO}/.git" ]]; then
  log "Phase 2: KPIレポート push + Slack通知"
  cd "${REAL_PROTO}"
  setup_git_credential
  git add ops/ logs/
  if ! git diff --cached --quiet; then
    git commit -m "auto-kpi: ${MODE} ${RUN_DATE} - KPIレポート" >> "${LOG_FILE}" 2>&1
    git push origin main >> "${LOG_FILE}" 2>&1
    log "Git push (KPIレポート) 完了"
  fi

  NOTIFY_SCRIPT="${ROOT}/skills/public/overnight-work/scripts/notify_kpi_result.sh"
  if [[ -f "${NOTIFY_SCRIPT}" ]]; then
    log "Slack通知送信中..."
    CLAWD_ROOT="${ROOT}" bash "${NOTIFY_SCRIPT}" 2>&1 | tee -a "${LOG_FILE}" || log "Slack通知失敗（続行）"
  fi
elif [[ "$DATA_OK" != "true" ]]; then
  log "Phase 2 スキップ: データ取得失敗のためSlack通知しない"
fi

log "Phase 2完了: 残り$(remaining_seconds)秒"

# === Phase 3: プロトタイプHTML生成（ベストエフォート） ===
# CLI検出: PATH内のcodexを優先、なければホスト側パスにフォールバック
CODEX_CMD=""
if command -v codex &>/dev/null; then
  CODEX_CMD="codex"
elif [[ -x "/Users/ucarpacadmin/.npm-global/bin/codex" ]]; then
  CODEX_CMD="/Users/ucarpacadmin/.npm-global/bin/codex"
fi
CLAUDE_CMD=""
if command -v claude &>/dev/null; then
  CLAUDE_CMD="claude"
elif [[ -x "/Users/ucarpacadmin/.npm-global/bin/claude" ]]; then
  CLAUDE_CMD="/Users/ucarpacadmin/.npm-global/bin/claude"
fi

PROTO_SERVICE_DIR="${ROOT}/prototypes"

# 選定結果からプロトタイプ情報を取得
if [[ -f "${SELECTION}" && -f "${PROMPT}" ]]; then
  SELECTED_SERVICE=$("${PYTHON}" -c "import json; d=json.load(open('${SELECTION}')); print(d.get('selected',{}).get('service','ucarpac-app'))" 2>/dev/null || echo "ucarpac-app")
  SELECTED_ID=$("${PYTHON}" -c "import json; d=json.load(open('${SELECTION}')); print(d.get('selected',{}).get('id','unknown'))" 2>/dev/null || echo "unknown")
  SELECTED_TITLE=$("${PYTHON}" -c "import json; d=json.load(open('${SELECTION}')); print(d.get('selected',{}).get('title',''))" 2>/dev/null || echo "")

  # コンテキストファイルを決定
  if [[ "$SELECTED_SERVICE" == "ucarpac-web" ]]; then
    CONTEXT_FILE="${ROOT}/skills/public/overnight-work/contexts/ucarpac.md"
  else
    CONTEXT_FILE="${ROOT}/skills/public/overnight-work/contexts/ucarpac-app.md"
  fi
  COMPETITOR_FILE="${ROOT}/skills/public/overnight-work/contexts/competitors.md"

  OUTPUT_DIR="${PROTO_SERVICE_DIR}/${SELECTED_SERVICE}"
  mkdir -p "${OUTPUT_DIR}"

  # 共通プロンプト部品を組み立て
  BASE_CONTEXT="$(cat "${CONTEXT_FILE}" 2>/dev/null)"
  COMPETITOR_CONTEXT="$(cat "${COMPETITOR_FILE}" 2>/dev/null)"
  THEME_PROMPT="$(cat "${PROMPT}" 2>/dev/null)"

  log "=== プロトタイプ生成開始（${SELECTED_TITLE}） ==="

  # タイムアウト: 残り時間からgit push用マージンを引いて3分割
  REMAINING=$(remaining_seconds)
  GIT_PUSH_MARGIN=60
  PROTO_TOTAL=$((REMAINING - GIT_PUSH_MARGIN))
  if [[ $PROTO_TOTAL -lt 120 ]]; then
    log "残り時間不足（${REMAINING}秒）: プロトタイプ生成スキップ"
    CODEX_CMD=""  # スキップさせる
  fi
  PROTO_TIMEOUT=$((PROTO_TOTAL / 3))
  # 上限300秒、下限60秒
  [[ $PROTO_TIMEOUT -gt 300 ]] && PROTO_TIMEOUT=300
  [[ $PROTO_TIMEOUT -lt 60 ]] && PROTO_TIMEOUT=60
  log "プロトタイプタイムアウト: ${PROTO_TIMEOUT}秒/ファイル（残り${REMAINING}秒）"

  # フィードバックから好評アプローチを取得してプロンプトに注入
  FEEDBACK_HINT=""
  if [[ -f "${FEEDBACK_SUMMARY}" ]]; then
    FEEDBACK_HINT=$("${PYTHON}" -c "
import json
fb = json.load(open('${FEEDBACK_SUMMARY}'))
# 好評率でソート、TOP3を抽出
rated = []
for tid, data in fb.items():
    total = data.get('up',0) + data.get('down',0)
    if total >= 2:
        ratio = data.get('up',0) / total
        rated.append((tid, ratio, data.get('top_approaches',[])))
rated.sort(key=lambda x: -x[1])
top3 = rated[:3]
if top3:
    lines = ['過去の好評アプローチ:']
    for tid, ratio, approaches in top3:
        lines.append(f'  - {tid} (好評率{ratio:.0%}): {\" / \".join(approaches[:2]) if approaches else \"詳細なし\"}')
    print('\n'.join(lines))
" 2>/dev/null || echo "")
  fi

  # バリエーション別のアプローチ指定
  APPROACHES=(
    "A案: 感情に訴えるアプローチ。ユーザーの不安や期待に寄り添い、安心感を与えるデザイン。暖色系のアクセント、手書き風要素、親しみやすいイラスト的表現"
    "B案: データドリブンアプローチ。数字・グラフ・比較表で説得力を出す。ダッシュボード風レイアウト、SVGチャート、進捗バー"
    "C案: ゲーミフィケーション・インタラクティブアプローチ。スワイプ、診断フロー、ステップ進行などの操作体験重視。マイクロアニメーション"
  )
  VARIANTS=(a b c)

  # codex exec で1ファイルずつ生成
  if [[ -n "$CODEX_CMD" ]]; then
    for i in 0 1 2; do
      VARIANT="${VARIANTS[$i]}"
      APPROACH="${APPROACHES[$i]}"
      OUT_FILE="${OUTPUT_DIR}/codex-${SELECTED_ID}-${VARIANT}.html"
      TMP_FILE="/tmp/proto-${SELECTED_ID}-${VARIANT}.html"

      log "codex exec: ${VARIANT}案 生成中..."
      (
        cd "${OUTPUT_DIR}"
        timeout "${PROTO_TIMEOUT}" "${CODEX_CMD}" exec \
          -c sandbox_mode="workspace-write" \
          -c approval_policy="never" \
          -o "${TMP_FILE}" \
          "以下の要件でHTMLプロトタイプを1ファイル生成してください。コードのみ出力。マークダウンのコードフェンス(\`\`\`)は不要。

## アプローチ
${APPROACH}

## コンテキスト
${BASE_CONTEXT}

## 競合情報
${COMPETITOR_CONTEXT}

## テーマ
${THEME_PROMPT}

${FEEDBACK_HINT:+## ユーザーフィードバック（参考にすること）
${FEEDBACK_HINT}

}## 生成ルール（厳守）
- 完全なHTMLファイル（<!DOCTYPE html>から</html>まで）
- CSS/JSはすべてインライン（外部ファイル参照なし）
- モバイルファースト（375px幅基準）、レスポンシブ対応
- lang=\"ja\"、日本語のUI、フォントはNoto Sans JP
- リアルなダミーデータ（車名・価格・相場等を具体的に）
- インタラクティブ要素必須（ボタン、アニメーション、状態変化等）
- ファイル冒頭に <!-- ${APPROACH} --> コメント
- <head>の直前に <script src=\"../auth.js\"></script>
- 最低200行以上の充実したコード" \
          2>> "${LOG_FILE}"
      )

      # コードフェンスを除去し、HTMLだけ抽出
      if [[ -f "${TMP_FILE}" ]]; then
        "${PYTHON}" - "${TMP_FILE}" "${OUT_FILE}" <<'STRIPPY'
import sys, re
from pathlib import Path
raw = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")
# マークダウンコードフェンスを除去
cleaned = re.sub(r'^```(?:html)?\s*\n', '', raw)
cleaned = re.sub(r'\n```\s*$', '', cleaned)
# <!DOCTYPE html> 以降を抽出（前後のゴミを除去）
m = re.search(r'(<!DOCTYPE html>.*</html>)', cleaned, re.DOTALL | re.IGNORECASE)
if m:
    cleaned = m.group(1)
Path(sys.argv[2]).write_text(cleaned, encoding="utf-8")
print(f"  → {sys.argv[2]} ({len(cleaned)} bytes)")
STRIPPY
        rm -f "${TMP_FILE}"
      else
        log "  ${VARIANT}案: 出力ファイルなし（失敗）"
      fi
    done
  else
    log "Codex CLI未検出（プロトタイプ生成スキップ）"
  fi

  # Claude CLIがあれば追加バリエーションも生成（オプション）
  if [[ -n "$CLAUDE_CMD" ]]; then
    log "Claude CLI検出: 追加バリエーション生成は省略（codex分で十分）"
  fi

  # 生成ファイル数を確認
  GENERATED=$(find "${OUTPUT_DIR}" -name "*-${SELECTED_ID}-*.html" -newer "${SELECTION}" 2>/dev/null | wc -l | tr -d ' ')
  log "生成ファイル数: ${GENERATED}"

  # index.html を再生成（プロトタイプ一覧 - 独立スクリプトで生成）
  log "index.html 更新中..."
  "${PYTHON}" "${SCRIPTS_DIR}/generate_index.py" "${OUTPUT_DIR}" "${SELECTED_TITLE}" "${RUN_DATE}" \
    --feedback-url "https://script.google.com/macros/s/AKfycbyhxczCVKHbnGgdmnnlY400zTrbTJFtJtM1sxnlxuZtGa-A80PREWJ8zs2XhRnxUC-W/exec"

else
  log "選定結果ファイルが見つかりません（プロトタイプ生成スキップ）"
fi

# === 競合ウォッチは独立スクリプト run_competitor_watch.sh に移行済み ===
# cronジョブ competitor-watch-weekly が毎週月曜 8:30に実行

# === Phase 4: Git push（プロトタイプ生成分） ===
if [[ -d "${REAL_PROTO}/.git" ]]; then
  log "Phase 4: Git push (プロトタイプ)"
  cd "${REAL_PROTO}"
  setup_git_credential
  git add -A
  if git diff --cached --quiet; then
    log "Git (プロトタイプ): 変更なし"
  else
    SELECTED_TITLE=$("${PYTHON}" -c "import json; d=json.load(open('${SELECTION}')); print(d.get('selected',{}).get('title','update'))" 2>/dev/null || echo "update")
    COMMIT_MSG="auto-kpi: ${MODE} ${RUN_DATE} - ${SELECTED_TITLE}"
    git commit -m "${COMMIT_MSG}" >> "${LOG_FILE}" 2>&1
    git push origin main >> "${LOG_FILE}" 2>&1
    log "Git push (プロトタイプ) 完了"
  fi
fi

log "=== Auto KPI Cycle 完了 ==="
log "Selection JSON: ${SELECTION}"
log "Prompt file:    ${PROMPT}"
log "Report URL:     ${REPORT_URL}"
log "Log file:       ${LOG_FILE}"
echo ""
echo "--- 選定プロンプト ---"
cat "${PROMPT}"
