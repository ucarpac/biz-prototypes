import json
import mimetypes
import os
import posixpath
import time
from html import escape
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import unquote

from flask import Flask, Response, abort, request
from google.api_core.exceptions import NotFound
from google.cloud import storage


app = Flask(__name__)


@dataclass
class PageObject:
    body: bytes
    content_type: str
    updated: Optional[str] = None


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def strip_known_prefix(path: str) -> str:
    prefixes = os.environ.get("BIZ_PROTO_STRIP_PREFIXES", "/biz-prototypes/")
    for prefix in [p.strip() for p in prefixes.split(",") if p.strip()]:
        prefix = "/" + prefix.strip("/") + "/"
        if path == prefix.rstrip("/"):
            return "/"
        if path.startswith(prefix):
            return "/" + path[len(prefix):]
    return path


def normalize_key(raw_path: str) -> str:
    path = unquote(raw_path.split("?", 1)[0])
    path = strip_known_prefix(path)
    path = posixpath.normpath("/" + path.lstrip("/")).lstrip("/")
    if path in {"", "."}:
        return "index.html"
    if raw_path.endswith("/"):
        return path.rstrip("/") + "/index.html"
    return path


def cache_seconds_for(key: str) -> int:
    if key.endswith(".html") or key == "auth.js":
        return 60
    return 3600


class PageStore:
    def __init__(self) -> None:
        self.local_root = os.environ.get("BIZ_PROTO_LOCAL_ROOT")
        self.bucket_name = os.environ.get("BIZ_PROTO_BUCKET")
        self._client = None

    def _bucket(self):
        if not self.bucket_name:
            raise RuntimeError("BIZ_PROTO_BUCKET is required")
        if self._client is None:
            self._client = storage.Client()
        return self._client.bucket(self.bucket_name)

    def get(self, key: str) -> PageObject:
        if self.local_root:
            path = (Path(self.local_root) / key).resolve()
            root = Path(self.local_root).resolve()
            if root not in path.parents and path != root:
                raise NotFound("invalid path")
            if not path.is_file():
                raise NotFound(key)
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            return PageObject(path.read_bytes(), content_type, str(path.stat().st_mtime))

        blob = self._bucket().blob(key)
        if not blob.exists():
            raise NotFound(key)
        body = blob.download_as_bytes()
        content_type = blob.content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
        updated = blob.updated.isoformat() if blob.updated else None
        return PageObject(body, content_type, updated)


STORE = PageStore()
POLICY_CACHE = {"loaded_at": 0.0, "policy": None}


def default_policy() -> dict:
    return {
        "version": 1,
        "internal": {"domains": ["ucarpac.co.jp"]},
        "partners": {
            "ayudante": {
                "name": "アユダンテ株式会社",
                "domains": ["ayudante.jp"],
                "slack": {
                    "channel_id": "C049FPP511Q",
                    "channel_name": "zm05_ayudante"
                }
            }
        },
        "rules": [
            {"prefix": "agency/", "access": "partner", "partner": "ayudante", "enabled": True},
            {"prefix": "ops/auto-kpi/", "access": "partner", "partner": "ayudante", "enabled": True},
            {
                "prefix": "reports/ai-inflow-20260331-n6x3p8r4k2/",
                "access": "partner",
                "partner": "ayudante",
                "enabled": True
            },
            {"prefix": "shares/ayudante/", "access": "partner", "partner": "ayudante", "enabled": True},
            {"prefix": "shares/internal/", "access": "internal", "enabled": True},
            {"prefix": "", "access": "internal", "enabled": True}
        ]
    }


def load_policy() -> dict:
    ttl = int(os.environ.get("BIZ_PROTO_POLICY_CACHE_SECONDS", "60"))
    now = time.time()
    if POLICY_CACHE["policy"] is not None and now - POLICY_CACHE["loaded_at"] < ttl:
        return POLICY_CACHE["policy"]

    key = os.environ.get("BIZ_PROTO_SHARE_INDEX", "_config/share-index.json")
    try:
        policy = json.loads(STORE.get(key).body.decode("utf-8"))
    except Exception:
        if env_bool("BIZ_PROTO_ALLOW_DEFAULT_POLICY", True):
            policy = default_policy()
        else:
            raise

    POLICY_CACHE["loaded_at"] = now
    POLICY_CACHE["policy"] = policy
    return policy


def email_from_iap() -> str:
    raw = request.headers.get("X-Goog-Authenticated-User-Email", "")
    if raw.startswith("accounts.google.com:"):
        return raw.split(":", 1)[1].lower()
    if "@" in raw:
        return raw.lower()

    local_email = os.environ.get("BIZ_PROTO_LOCAL_AUTH_EMAIL", "")
    if local_email and request.remote_addr in {"127.0.0.1", "::1"}:
        return local_email.lower()
    return ""


def domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def domains_match(email: str, domains: list[str]) -> bool:
    domain = domain_of(email)
    return any(domain == allowed.lower().lstrip("@") for allowed in domains)


def users_match(email: str, users: list[str]) -> bool:
    return email in {user.lower() for user in users}


def matching_rule(policy: dict, key: str) -> dict:
    rules = policy.get("rules", [])
    enabled_rules = [rule for rule in rules if key.startswith(str(rule.get("prefix", "")).lstrip("/"))]
    if not enabled_rules:
        return {"prefix": "", "access": "internal", "enabled": True}
    return max(enabled_rules, key=lambda rule: len(str(rule.get("prefix", ""))))


def access_level(policy: dict, email: str) -> str:
    internal = policy.get("internal", {})
    if users_match(email, internal.get("users", [])) or domains_match(email, internal.get("domains", [])):
        return "full"

    for partner_id, partner in policy.get("partners", {}).items():
        if users_match(email, partner.get("users", [])) or domains_match(email, partner.get("domains", [])):
            return partner_id
    return ""


def allowed(policy: dict, rule: dict, email: str) -> tuple[bool, str]:
    if not rule.get("enabled", True):
        return False, "disabled"
    if not email:
        return False, "unauthenticated"

    level = access_level(policy, email)
    if level == "full":
        return True, "full"

    access = rule.get("access", "internal")
    if access == "partner" and level and level == rule.get("partner"):
        return True, "agency"
    if access == "partner" and domains_match(email, rule.get("allowed_domains", [])):
        return True, "agency"
    if access == "authenticated" and level:
        return True, "full" if level == "full" else "agency"
    if access == "public":
        return True, "public"
    return False, "forbidden"


def auth_state_script(level: str) -> bytes:
    state = {
        "value": "ok",
        "level": "full" if level == "full" else "agency",
        "expiresAt": int((time.time() + 24 * 60 * 60) * 1000)
    }
    payload = json.dumps(state, ensure_ascii=False)
    script = f"""
// Cloud Run + IAP 配信ではサーバー側認証を正とし、既存auth.jsのパスワード入力を省略します。
(function () {{
  try {{
    var state = {payload};
    localStorage.setItem("biz_proto_auth_v2", JSON.stringify(state));
    document.cookie = "biz_proto_auth_v2=" + encodeURIComponent(JSON.stringify(state)) + "; path=/; SameSite=Lax; Secure";
  }} catch (e) {{}}
}})();
"""
    return script.encode("utf-8")


def with_headers(response: Response, key: str) -> Response:
    response.headers["Cache-Control"] = f"private, max-age={cache_seconds_for(key)}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


def is_lp11_report(key: str) -> bool:
    return key == "reports/lp11-cpa-report-20260410/index.html"


def lp11_status() -> dict:
    try:
        return json.loads(STORE.get("_status/lp11-cpa-report.json").body.decode("utf-8"))
    except Exception:
        return {
            "status": "unknown",
            "message": "自動更新ステータスはまだ記録されていません。",
        }


def lp11_status_banner() -> str:
    status = lp11_status()
    state = str(status.get("status", "unknown"))
    is_ok = state == "success"
    title = "自動更新は正常です" if is_ok else "自動更新の確認が必要です"
    message = escape(str(status.get("message") or ""))
    run_url = escape(str(status.get("run_url") or ""), quote=True)
    updated_at = escape(str(status.get("updated_at") or status.get("started_at") or ""))
    badge = "正常" if is_ok else ("失敗" if state == "failure" else "確認中")
    button_label = "手動更新を実行"
    details_link = f'<a class="lp11-status-link" href="{run_url}" target="_blank" rel="noopener">実行ログを見る</a>' if run_url else ""

    return f"""
<style>
  .lp11-status-panel {{
    position: sticky;
    top: 42px;
    z-index: 19;
    margin: 0;
    padding: 12px 16px;
    border-bottom: 1px solid {"#14532d" if is_ok else "#7f1d1d"};
    background: {"rgba(20,83,45,.96)" if is_ok else "rgba(127,29,29,.96)"};
    color: #fff;
    font-family: 'Noto Sans JP', system-ui, sans-serif;
    box-shadow: 0 10px 24px rgba(0,0,0,.22);
  }}
  .lp11-status-inner {{
    display: flex;
    gap: 14px;
    align-items: center;
    justify-content: space-between;
    max-width: 1180px;
    margin: 0 auto;
  }}
  .lp11-status-copy {{ min-width: 0; }}
  .lp11-status-title {{ font-weight: 800; font-size: 14px; }}
  .lp11-status-meta {{ color: rgba(255,255,255,.84); font-size: 12px; margin-top: 3px; }}
  .lp11-status-actions {{ display: flex; gap: 8px; align-items: center; flex-shrink: 0; }}
  .lp11-status-badge {{
    display: inline-flex;
    align-items: center;
    min-height: 26px;
    padding: 0 10px;
    border: 1px solid rgba(255,255,255,.36);
    border-radius: 999px;
    font-size: 12px;
    font-weight: 800;
  }}
  .lp11-status-button, .lp11-status-link {{
    min-height: 32px;
    border-radius: 7px;
    border: 1px solid rgba(255,255,255,.42);
    background: rgba(255,255,255,.14);
    color: #fff;
    padding: 0 11px;
    font-size: 12px;
    font-weight: 800;
    text-decoration: none;
    cursor: pointer;
  }}
  .lp11-status-button[disabled] {{ opacity: .66; cursor: wait; }}
  @media (max-width: 760px) {{
    .lp11-status-inner {{ align-items: flex-start; flex-direction: column; }}
    .lp11-status-actions {{ flex-wrap: wrap; }}
  }}
</style>
<div class="lp11-status-panel" id="lp11StatusPanel">
  <div class="lp11-status-inner">
    <div class="lp11-status-copy">
      <div class="lp11-status-title">{title}</div>
      <div class="lp11-status-meta">{message} {updated_at}</div>
    </div>
    <div class="lp11-status-actions">
      <span class="lp11-status-badge">{badge}</span>
      {details_link}
      <button class="lp11-status-button" id="lp11ManualRefresh" type="button">{button_label}</button>
    </div>
  </div>
</div>
<script>
(function () {{
  var button = document.getElementById('lp11ManualRefresh');
  if (!button) return;
  button.addEventListener('click', function () {{
    button.disabled = true;
    button.textContent = '起動中...';
    fetch('/_admin/lp11-refresh', {{ method: 'POST', credentials: 'same-origin' }})
      .then(function (res) {{ return res.json().then(function (body) {{ return {{ ok: res.ok, body: body }}; }}); }})
      .then(function (result) {{
        button.textContent = result.ok ? '起動しました' : '起動できません';
        alert(result.body.message || (result.ok ? '手動更新を起動しました。数分後に画面を更新してください。' : '手動更新を起動できませんでした。'));
      }})
      .catch(function () {{
        button.textContent = '起動できません';
        alert('手動更新を起動できませんでした。');
      }})
      .finally(function () {{
        setTimeout(function () {{
          button.disabled = false;
          button.textContent = '{button_label}';
        }}, 5000);
      }});
  }});
}})();
</script>
"""


def inject_lp11_status(body: bytes, content_type: str, key: str) -> bytes:
    if not is_lp11_report(key) or "html" not in content_type:
        return body
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body
    banner = lp11_status_banner()
    if "</body>" in text:
        text = text.replace("</body>", banner + "\n</body>", 1)
    else:
        text += banner
    return text.encode("utf-8")


def github_workflow_token() -> str:
    return os.environ.get("BIZ_PROTO_GITHUB_TOKEN", "").strip()


def trigger_lp11_workflow() -> tuple[bool, str]:
    token = github_workflow_token()
    if not token:
        return False, "手動更新用のトークンが未設定です。自動更新は動きますが、画面ボタンからの手動起動はまだ使えません。"

    payload = json.dumps({"ref": "main"}).encode("utf-8")
    req = urlrequest.Request(
        "https://api.github.com/repos/ucarpac/biz-prototypes/actions/workflows/update-lp11-cpa-report.yml/dispatches",
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "biz-prototypes-viewer",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=12) as res:
            if res.status in {200, 201, 202, 204}:
                return True, "手動更新を起動しました。数分後に画面を更新してください。"
            return False, f"GitHubから想定外の応答がありました: HTTP {res.status}"
    except urlerror.HTTPError as exc:
        return False, f"GitHub API エラー: HTTP {exc.code}"
    except Exception as exc:
        return False, f"手動更新の起動に失敗しました: {exc}"


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/_admin/lp11-refresh")
def lp11_refresh():
    policy = load_policy()
    email = email_from_iap()
    if access_level(policy, email) != "full":
        abort(403)
    ok, message = trigger_lp11_workflow()
    return {"ok": ok, "message": message}, 202 if ok else 503


@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def serve(path: str):
    key = normalize_key("/" + path)
    if key.startswith("_config/"):
        abort(404)

    policy = load_policy()
    rule = matching_rule(policy, key)
    if key == "auth.js":
        rule = {"prefix": "auth.js", "access": "authenticated", "enabled": True}
    email = email_from_iap()
    ok, level = allowed(policy, rule, email)
    if not ok:
        abort(401 if level == "unauthenticated" else 403)

    try:
        obj = STORE.get(key)
    except NotFound:
        if "." not in posixpath.basename(key):
            key = key.rstrip("/") + "/index.html"
            obj = STORE.get(key)
        else:
            raise

    body = obj.body
    if key == "auth.js":
        body = auth_state_script(level) + body
    else:
        body = inject_lp11_status(body, obj.content_type, key)

    response = Response(body, mimetype=obj.content_type)
    if obj.updated:
        response.headers["Last-Modified"] = obj.updated
    return with_headers(response, key)
