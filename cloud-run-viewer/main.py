import json
import mimetypes
import os
import posixpath
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
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


@app.get("/healthz")
def healthz():
    return {"ok": True}


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

    response = Response(body, mimetype=obj.content_type)
    if obj.updated:
        response.headers["Last-Modified"] = obj.updated
    return with_headers(response, key)
