// Shared password gate for biz-prototypes
// Note: This is client-side protection only. Suitable for lightweight internal sharing.
(function () {
  const CONFIG = window.PROTO_AUTH_CONFIG || {};
  const STORAGE_KEY = "biz_proto_auth_v2";
  const COOKIE_KEY = "biz_proto_auth_v2";
  const PASS_HASH_FULL   = "8c66d6dd26cb71b9fb433e803b147abdcc2a9bbea0ccf14b87dadc2ced6393a7"; // ucarpac2026
  const PASS_HASH_AGENCY = "02a6db4e0dd34fc166a4035447c57305e23f8d43a724a0c93b477eabfa71ba58"; // agency2026
  const TTL_MS = (CONFIG.ttlMs || 24 * 60 * 60 * 1000);
  const TITLE = CONFIG.title || "UcarPAC Prototype Hub";
  const SUBTITLE = CONFIG.subtitle || "社内共有用パスワードを入力してください";
  const ACCENT = CONFIG.accent || "linear-gradient(135deg, #1ddcff, #4db4ff)";
  const AGENCY_PATH_PREFIXES = [
    "/agency/",
    "/ops/auto-kpi/",
    "/reports/ai-inflow-20260331-n6x3p8r4k2/"
  ];
  // "full" = UCP内部（全ページ閲覧可）、"agency" = 代理店共有ページのみ閲覧可
  const REQUIRED = CONFIG.required || detectRequiredLevel();

  function detectRequiredLevel() {
    if (typeof location === "undefined") return "full";
    const path = location.pathname.replace(/^\/biz-prototypes/, "");
    return AGENCY_PATH_PREFIXES.some((prefix) => path.startsWith(prefix)) ? "agency" : "full";
  }

  function getBasePath() {
    if (typeof location === "undefined") return "/";
    const parts = location.pathname.split("/").filter(Boolean);
    if (location.hostname.endsWith("github.io") && parts.length > 0) {
      return `/${parts[0]}/`;
    }
    return "/";
  }

  // ---------------------------------------------------------------------------
  // 自動パンくず（Hub 戻りリンク）
  // 各ページに手書きする必要はありません。auth.js が現在の URL とベースパスから
  // 「Hub / セクション / 現在ページ」のリンクを絶対パスで自動生成します。
  // ベースパス基準の絶対リンクなので、ファイルがどの階層にあってもリンクは壊れません。
  //
  // PROTO_AUTH_CONFIG での制御:
  //   title       … 末尾（現在ページ）のラベル。省略時は <title> を使用
  //   breadcrumb  … false でパンくずを無効化
  //   navTheme    … "dark" | "light" で配色を上書き（既定はセクションで自動判定）
  //   nav         … [{label, href}, ...] でパンくずを完全に手動指定（href はベース相対）
  // ---------------------------------------------------------------------------
  const SECTION_LABELS = {
    "ucarpac-app": "App プロトタイプ",
    "reports": "Reports",
    "ops": "運用監視レポート",
    "agency": "代理店ハブ",
  };
  const SUBSECTION_LABELS = {
    "ops/auto-kpi": "Auto KPI",
    "ops/competitor-watch": "競合ウォッチ",
    "ops/appsflyer": "AppsFlyer",
    "ucarpac-app/app-enhancement": "App Enhancement",
  };
  // 既定でダーク配色にするセクション（ページ自体がダークテーマのもの）
  const DARK_NAV_SECTIONS = { "ucarpac-app": true };

  function prettify(seg) {
    return String(seg)
      .replace(/\.html?$/i, "")
      .replace(/[-_]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function buildCrumbs() {
    const base = getBasePath();
    let path = location.pathname;
    if (path.indexOf(base) === 0) path = path.slice(base.length);
    let segs = path.split("/").filter(Boolean);

    // 末尾のファイル名を切り出す。index 系はディレクトリ表示として扱う
    let file = null;
    if (segs.length && /\.html?$/i.test(segs[segs.length - 1])) {
      file = segs.pop();
      if (/^index(-all)?\.html?$/i.test(file)) file = null;
    }

    const crumbs = [{ label: "Hub", href: base }];
    if (segs.length === 0 && !file) return null; // ルート Hub では出さない

    const top = segs[0];
    if (top) {
      crumbs.push({ label: SECTION_LABELS[top] || prettify(top), href: base + top + "/" });
    }
    let subKey = null;
    if (segs.length >= 2) {
      subKey = top + "/" + segs[1];
      if (SUBSECTION_LABELS[subKey]) {
        crumbs.push({ label: SUBSECTION_LABELS[subKey], href: base + top + "/" + segs[1] + "/" });
      }
    }

    const leafLabel = CONFIG.title || document.title || "";
    if (file) {
      crumbs.push({ label: leafLabel || prettify(file), href: null });
    } else {
      const sectionIsCurrent = segs.length === 1;
      const subsectionIsCurrent = segs.length === 2 && subKey && SUBSECTION_LABELS[subKey];
      if (!sectionIsCurrent && !subsectionIsCurrent) {
        // section/subsection に当てはまらない深いインデックス（reports/<slug>/ 等）
        crumbs.push({ label: leafLabel || prettify(segs[segs.length - 1]), href: null });
      }
    }
    crumbs[crumbs.length - 1].href = null; // 末尾は現在ページなのでリンクなし
    return { crumbs: crumbs, dark: !!DARK_NAV_SECTIONS[top] };
  }

  // 現在の閲覧者の認証レベル（"full" = 社内 / "agency" = 代理店共有）
  function currentLevel() {
    const s = readState();
    return (s && s.level) || "full";
  }

  // 代理店ユーザー向けパンくず。社内専用ハブ/セクションへは誘導せず、
  // 必ず「代理店ハブ」を起点にする（押せないリンクを見せない）。
  function buildAgencyCrumbs() {
    const base = getBasePath();
    let path = location.pathname;
    if (path.indexOf(base) === 0) path = path.slice(base.length);
    let segs = path.split("/").filter(Boolean);
    let file = null;
    if (segs.length && /\.html?$/i.test(segs[segs.length - 1])) {
      file = segs.pop();
      if (/^index(-all)?\.html?$/i.test(file)) file = null;
    }
    // 代理店ハブ自身では出さない（代理店ユーザーにとってのホーム）
    if (segs[0] === "agency" && !file) return null;
    const leaf = CONFIG.title || document.title || "";
    return {
      crumbs: [
        { label: "代理店ハブ", href: base + "agency/" },
        { label: leaf, href: null },
      ],
      dark: false,
    };
  }

  function resolveNavConfig() {
    if (Array.isArray(CONFIG.nav) && CONFIG.nav.length) {
      const base = getBasePath();
      const crumbs = CONFIG.nav.map(function (c, i) {
        const isLast = i === CONFIG.nav.length - 1;
        let href = null;
        if (!isLast && c.href != null) {
          href = /^(https?:)?\//.test(c.href) ? c.href : base + String(c.href).replace(/^\//, "");
        }
        return { label: c.label, href: href };
      });
      return { crumbs: crumbs, dark: CONFIG.navTheme === "dark" };
    }
    // 代理店ユーザーは社内導線を見せず、代理店ハブ起点のパンくずにする
    if (currentLevel() === "agency") return buildAgencyCrumbs();
    return buildCrumbs();
  }

  function renderBreadcrumb() {
    if (CONFIG.breadcrumb === false) return;
    if (!document.body || document.getElementById("proto-breadcrumb")) return;
    const data = resolveNavConfig();
    if (!data || !data.crumbs || data.crumbs.length < 2) return;

    const dark = CONFIG.navTheme ? CONFIG.navTheme === "dark" : data.dark;
    const c = dark
      ? { bg: "rgba(17,24,39,0.96)", border: "rgba(255,255,255,0.10)", link: "#cbd5e1", sep: "#475569", cur: "#e2e8f0" }
      : { bg: "#ffffff", border: "#e2e8f0", link: "#1a5cd8", sep: "#b0bccc", cur: "#5f7182" };

    const nav = document.createElement("nav");
    nav.id = "proto-breadcrumb";
    nav.style.cssText =
      "margin:0;padding:10px 20px;font:600 13px/1.4 -apple-system,BlinkMacSystemFont,'Hiragino Sans','Noto Sans JP',sans-serif;" +
      "background:" + c.bg + ";border-bottom:1px solid " + c.border + ";" +
      (dark ? "backdrop-filter:blur(8px);" : "") +
      "display:flex;flex-wrap:wrap;align-items:center;gap:0;";

    data.crumbs.forEach(function (crumb, i) {
      if (i > 0) {
        const sep = document.createElement("span");
        sep.textContent = "/";
        sep.style.cssText = "margin:0 8px;color:" + c.sep + ";";
        nav.appendChild(sep);
      }
      const label = i === 0 ? "← " + crumb.label : crumb.label;
      if (crumb.href) {
        const a = document.createElement("a");
        a.href = crumb.href;
        a.textContent = label;
        a.style.cssText = "color:" + c.link + ";text-decoration:none;";
        nav.appendChild(a);
      } else {
        const span = document.createElement("span");
        span.textContent = label;
        span.style.cssText = "color:" + c.cur + ";";
        nav.appendChild(span);
      }
    });

    document.body.insertBefore(nav, document.body.firstChild);
  }

  function getCookie(name) {
    const encoded = `${name}=`;
    const found = document.cookie.split(";").map((item) => item.trim()).find((item) => item.indexOf(encoded) === 0);
    return found ? decodeURIComponent(found.slice(encoded.length)) : "";
  }

  function setCookie(name, value, ttlMs) {
    const expires = new Date(Date.now() + ttlMs).toUTCString();
    const secure = location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=${getBasePath()}; SameSite=Lax${secure}`;
  }

  function readState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || !parsed.expiresAt) return null;
      if (Date.now() >= parsed.expiresAt) {
        localStorage.removeItem(STORAGE_KEY);
        return null;
      }
      return parsed;
    } catch (_) {
      return null;
    }
  }

  function hasValidAuth() {
    const stored = readState();
    if (!stored || stored.value !== "ok") return false;
    // 旧セッション（levelなし）は full として扱う（後方互換）
    const level = stored.level || "full";
    const allowed = level === "full" || (level === "agency" && REQUIRED === "agency");
    if (!allowed) return false;
    // cookie がなければ再セット
    const cookie = getCookie(COOKIE_KEY);
    if (!cookie) {
      setCookie(COOKIE_KEY, "ok", Math.max(0, stored.expiresAt - Date.now()));
    }
    return true;
  }

  function persistAuth(level) {
    const expiresAt = Date.now() + TTL_MS;
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ value: "ok", level: level, expiresAt }));
    setCookie(COOKIE_KEY, "ok", TTL_MS);
  }

  async function sha256(text) {
    const buffer = new TextEncoder().encode(text);
    const digest = await crypto.subtle.digest("SHA-256", buffer);
    return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  function createOverlay() {
    const overlay = document.createElement("div");
    overlay.id = "proto-auth-overlay";
    overlay.innerHTML = `
      <style>
        #proto-auth-overlay {
          position: fixed;
          inset: 0;
          background: radial-gradient(circle at top right, rgba(29,220,255,0.16), transparent 22%), linear-gradient(135deg, #111827 0%, #1c2663 100%);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 99999;
          padding: 20px;
        }
        #proto-auth-box {
          width: min(420px, 100%);
          background: rgba(255,255,255,0.98);
          border: 1px solid rgba(219,227,239,0.9);
          border-radius: 18px;
          padding: 30px 28px 24px;
          box-shadow: 0 20px 50px rgba(15,23,42,0.28);
          text-align: center;
          font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Noto Sans JP", sans-serif;
        }
        #proto-auth-badge {
          display: inline-block;
          padding: 6px 12px;
          border-radius: 999px;
          background: #eaf4ff;
          color: #2455a6;
          font-size: 12px;
          font-weight: 700;
          margin-bottom: 14px;
        }
        #proto-auth-box h2 {
          color: #16233f;
          margin: 0 0 8px;
          font-size: 22px;
          line-height: 1.35;
        }
        #proto-auth-box p {
          color: #5c6b84;
          font-size: 14px;
          margin: 0 0 18px;
          line-height: 1.7;
        }
        #proto-auth-input {
          width: 100%;
          padding: 14px 16px;
          border: 2px solid #dbe3ef;
          border-radius: 12px;
          font-size: 16px;
          text-align: center;
          margin-bottom: 12px;
        }
        #proto-auth-input:focus {
          outline: none;
          border-color: #4db4ff;
          box-shadow: 0 0 0 4px rgba(77,180,255,0.14);
        }
        #proto-auth-btn {
          width: 100%;
          padding: 13px;
          background: ${ACCENT};
          border: none;
          border-radius: 999px;
          color: white;
          font-size: 15px;
          font-weight: 800;
          cursor: pointer;
        }
        #proto-auth-btn[disabled] {
          opacity: 0.7;
          cursor: progress;
        }
        #proto-auth-error {
          display: none;
          color: #d61f69;
          font-size: 13px;
          margin-top: 10px;
          font-weight: 700;
        }
        #proto-auth-help {
          color: #7a8699;
          font-size: 12px;
          margin-top: 12px;
        }
      </style>
      <div id="proto-auth-box">
        <div id="proto-auth-badge">Internal View</div>
        <h2>${TITLE}</h2>
        <p>${SUBTITLE}</p>
        <input type="password" id="proto-auth-input" placeholder="パスワード" autocomplete="current-password" autofocus />
        <button id="proto-auth-btn">表示する</button>
        <div id="proto-auth-error">パスワードが違います</div>
        <div id="proto-auth-help">認証は 24 時間保持されます</div>
      </div>
    `;

    document.body.appendChild(overlay);
    document.body.style.overflow = "hidden";
    return overlay;
  }

  async function main() {
    if (hasValidAuth()) {
      renderBreadcrumb();
      return;
    }

    const overlay = createOverlay();
    const input = document.getElementById("proto-auth-input");
    const button = document.getElementById("proto-auth-btn");
    const error = document.getElementById("proto-auth-error");

    async function submit() {
      button.disabled = true;
      error.style.display = "none";
      try {
        const hash = await sha256(input.value);
        if (hash === PASS_HASH_FULL) {
          persistAuth("full");
          overlay.remove();
          document.body.style.overflow = "";
          renderBreadcrumb();
          return;
        }
        if (hash === PASS_HASH_AGENCY && REQUIRED === "agency") {
          persistAuth("agency");
          overlay.remove();
          document.body.style.overflow = "";
          renderBreadcrumb();
          return;
        }
      } catch (_) {
        // fall through to error state
      }
      input.value = "";
      input.focus();
      error.style.display = "block";
      button.disabled = false;
    }

    button.addEventListener("click", submit);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") submit();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", main, { once: true });
  } else {
    main();
  }
})();
