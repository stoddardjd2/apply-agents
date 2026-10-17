"""NoneCap hCaptcha token API (Camoufox cannot load the Chrome extension).

NopeCHA is dropping hCaptcha; NoneCap returns a real P1_ token from
POST https://api.nonecap.com/v1/solves which we inject into the page.

Docs: https://nonecap.com/api-reference/
Playwright guide: https://nonecap.com/solutions/playwright/
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

NONECAP_API_BASE = "https://api.nonecap.com/v1"

# Extract sitekey / rqdata from a rendered hCaptcha widget (host or iframe).
# Challenge iframes put sitekey in the URL *hash* (#sitekey=…), not ?search —
# searchParams alone misses those and NoneCap never gets called.
EXTRACT_HCAPTCHA_JS = r"""() => {
  const out = {
    sitekey: null,
    rqdata: null,
    callback: null,
    enterprise: false,
    userAgent: navigator.userAgent || '',
    source: null,
  };
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const take = (sk, rq, cb, source) => {
    if (!sk || !uuid.test(sk)) return false;
    if (!out.sitekey) {
      out.sitekey = sk;
      out.source = source || null;
    }
    if (rq) {
      out.rqdata = rq;
      out.enterprise = true;
    }
    if (cb && !out.callback) out.callback = cb;
    return true;
  };
  const paramsFromUrl = (raw) => {
    const found = { sitekey: null, rqdata: null };
    try {
      const u = new URL(raw, location.href);
      found.sitekey = u.searchParams.get('sitekey');
      found.rqdata = u.searchParams.get('rqdata');
      const hash = (u.hash || '').replace(/^#/, '');
      if (hash) {
        const hp = new URLSearchParams(hash);
        found.sitekey = found.sitekey || hp.get('sitekey');
        found.rqdata = found.rqdata || hp.get('rqdata');
      }
    } catch (_) {}
    return found;
  };

  const hosts = [
    ...document.querySelectorAll(
      '[data-sitekey], .h-captcha, [class*="h-captcha" i], [class*="hcaptcha" i]'
    ),
  ];
  for (const el of hosts) {
    take(
      el.getAttribute('data-sitekey') || '',
      el.getAttribute('data-rqdata') || null,
      el.getAttribute('data-callback') || null,
      'data-sitekey'
    );
  }

  for (const f of document.querySelectorAll('iframe')) {
    const src = f.getAttribute('src') || f.src || '';
    if (!/hcaptcha/i.test(src)) continue;
    const p = paramsFromUrl(src);
    take(p.sitekey, p.rqdata, null, 'iframe');
  }

  // Invisible / explicit render: sitekey often only appears in inline scripts.
  try {
    const html = document.documentElement && document.documentElement.outerHTML || '';
    const patterns = [
      /data-sitekey=["']([0-9a-f-]{36})["']/i,
      /sitekey["']?\s*[:=]\s*["']([0-9a-f-]{36})["']/i,
      /[?&#]sitekey=([0-9a-f-]{36})/i,
    ];
    for (const re of patterns) {
      const m = html.match(re);
      if (m) take(m[1], null, null, 'html');
    }
  } catch (_) {}

  // Resource URLs (challenge assets) sometimes carry sitekey in the fragment.
  try {
    for (const e of performance.getEntriesByType('resource') || []) {
      const name = String(e.name || '');
      if (!/hcaptcha/i.test(name)) continue;
      const p = paramsFromUrl(name);
      take(p.sitekey, p.rqdata, null, 'resource');
    }
  } catch (_) {}

  return out;
}"""

# Debug helper when extraction fails — iframe srcs / sitekey-looking strings.
DIAGNOSE_HCAPTCHA_JS = """() => {
  const iframes = [...document.querySelectorAll('iframe')].slice(0, 12).map((f) => ({
    src: (f.getAttribute('src') || f.src || '').slice(0, 240),
    w: Math.round(f.offsetWidth || 0),
    h: Math.round(f.offsetHeight || 0),
  }));
  const hosts = [...document.querySelectorAll('[data-sitekey]')].slice(0, 8).map((el) => ({
    sitekey: el.getAttribute('data-sitekey'),
    className: String(el.className || '').slice(0, 80),
  }));
  return {
    href: String(location.href || '').slice(0, 200),
    hasHcaptchaApi: typeof window.hcaptcha !== 'undefined',
    iframes,
    hosts,
  };
}"""

_INJECT_TOKEN_TEMPLATE = r"""
(() => {
  const token = __TOKEN__;
  const respKey = __RESP_KEY__;

  const setVal = (el, value) => {
    if (!el) return;
    const proto = el.tagName === 'TEXTAREA'
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
    el.innerHTML = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  };

  const ensureField = (name) => {
    let el = document.querySelector('textarea[name="' + name + '"], input[name="' + name + '"]');
    if (el) return el;
    const form = document.querySelector('form') || document.body;
    el = document.createElement('textarea');
    el.name = name;
    el.id = name;
    el.style.display = 'none';
    form.appendChild(el);
    return el;
  };

  for (const name of ['h-captcha-response', 'g-recaptcha-response']) {
    setVal(ensureField(name), token);
    for (const el of document.querySelectorAll(
      'textarea[name="' + name + '"], textarea#' + name + ', input[name="' + name + '"]'
    )) {
      setVal(el, token);
    }
  }

  if (respKey) {
    for (const name of ['h-captcha-response-key', 'g-recaptcha-response-key']) {
      setVal(ensureField(name), respKey);
    }
  }

  if (window.hcaptcha) {
    try {
      window.hcaptcha.getResponse = function() { return token; };
      if (respKey) window.hcaptcha.getRespKey = function() { return respKey; };
    } catch (_) {}
  }

  const host = document.querySelector('[data-callback], [data-sitekey], .h-captcha');
  const cbName = host && host.getAttribute('data-callback');
  if (cbName && typeof window[cbName] === 'function') {
    try { window[cbName](token); } catch (_) {}
  }

  for (const f of document.querySelectorAll('iframe[src*="hcaptcha"]')) {
    try {
      const wrap = f.closest('div');
      if (wrap && f.offsetWidth > 200) wrap.style.display = 'none';
    } catch (_) {}
  }

  const filled = [...document.querySelectorAll(
    'textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]'
  )].some((el) => (el.value || '').length > 20);

  return { filled: filled, callback: cbName || null, tokenLen: token.length };
})()
""".strip()


def build_inject_token_script(token: str, resp_key: str | None = None) -> str:
    """Camoufox main-world IIFE — args must be inlined; ``mw:(fn)`` does not receive Playwright args."""
    return (
        _INJECT_TOKEN_TEMPLATE
        .replace("__TOKEN__", json.dumps(token))
        .replace("__RESP_KEY__", json.dumps(resp_key))
    )


# Kept for tests / isolated-world fallback callers.
INJECT_TOKEN_JS = build_inject_token_script("P1_PLACEHOLDER", None)

def _env_str(*names: str, default: str = "") -> str:
    for name in names:
        val = os.getenv(name)
        if val is not None and str(val).strip():
            return str(val).strip()
    return default

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

def nonecap_api_key() -> str:
    return _env_str("NONECAP_KEY", "NONECAP_API_KEY", default="")

def nonecap_enabled() -> bool:
    """On when a key is present, unless NONECAP_ENABLED=0."""
    if not _env_bool("NONECAP_ENABLED", True):
        return False
    return bool(nonecap_api_key())

def nonecap_wait_seconds() -> int:
    raw = _env_str("NONECAP_WAIT_SECONDS", default="90")
    try:
        return max(5, min(90, int(raw)))
    except ValueError:
        return 90

def solve_hcaptcha(
    *,
    sitekey: str,
    url: str,
    rqdata: str | None = None,
    user_agent: str | None = None,
    api_key: str | None = None,
    wait_seconds: int | None = None,
) -> dict[str, Any]:
    """POST /v1/solves?wait=N — returns the solve object with token on success.

    Pass the browser's real ``user_agent`` so the token matches Camoufox/Firefox;
    NoneCap defaults to a Chrome UA that many sites reject when submitted from Firefox.
    """
    key = api_key if api_key is not None else nonecap_api_key()
    if not key:
        raise RuntimeError(
            "NONECAP_KEY is not set. Mint one at https://dashboard.nonecap.com"
        )
    wait = wait_seconds if wait_seconds is not None else nonecap_wait_seconds()
    captcha_type = "hcaptcha_enterprise" if rqdata else "hcaptcha"
    body: dict[str, Any] = {
        "type": captcha_type,
        "sitekey": sitekey,
        "url": url,
    }
    if rqdata:
        body["rqdata"] = rqdata
    if user_agent:
        body["user_agent"] = user_agent

    query = urllib.parse.urlencode({"wait": wait})
    endpoint = f"{NONECAP_API_BASE}/solves?{query}"
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=wait + 30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            detail_obj = json.loads(detail)
        except json.JSONDecodeError:
            detail_obj = {"raw": detail}
        raise RuntimeError(f"NoneCap HTTP {exc.code}: {detail_obj}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"NoneCap request failed: {exc}") from exc

    status = payload.get("status")
    token = payload.get("token")
    if status != "solved" or not token:
        raise RuntimeError(
            f"NoneCap solve not ready: status={status!r} error={payload.get('error')!r}"
        )
    return payload

