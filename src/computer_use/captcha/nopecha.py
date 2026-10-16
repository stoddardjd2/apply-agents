"""NopeCHA Firefox automation addon for Camoufox (same approach as landed).

Downloads live under .cache/nopecha (gitignored). The automation build reads
settings from manifest.json → nopecha; we copy that tree into a runtime dir and
inject NOPECHA_API_KEY before launch (key optional — free tier works by IP).

Docs: https://developers.nopecha.com/guides/extension_advanced/
Builds: https://github.com/NopeCHALLC/nopecha-extension/releases
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

DEFAULT_NOPECHA_VERSION = "0.6.1"
NOPECHA_CACHE_DIR = Path(
    os.getenv("NOPECHA_CACHE_DIR")
    or os.getenv("LANDED_NOPECHA_CACHE_DIR")
    or ".cache/nopecha"
)
NOPECHA_STATUS_URL = "https://api.nopecha.com/v1/status"
NOPECHA_OUT_OF_CREDIT_CODE = 16

# Do NOT auto_open reCAPTCHA/etc. while the agent fills the form — JazzHR and
# similar keep the widget on-page and early tokens expire before Submit.
# auto_solve stays on; the harness clicks/opens the checkbox only after Submit
# (or a mid-flow Continue gate) arms the solver. hCaptcha = NoneCap only.
SOLVE_SETTINGS = {
    "perimeterx_auto_solve": True,
    "awscaptcha_auto_open": False,
    "awscaptcha_auto_solve": True,
    "funcaptcha_auto_open": False,
    "funcaptcha_auto_solve": True,
    "turnstile_auto_solve": True,
    "recaptcha_auto_open": False,
    "recaptcha_auto_solve": True,
    "hcaptcha_auto_open": False,
    "hcaptcha_auto_solve": False,
}

def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        # Accept landed's env names so one key works across projects.
        alt = name.replace("NOPECHA_", "LANDED_NOPECHA_", 1) if name.startswith("NOPECHA_") else None
        if alt:
            raw = os.getenv(alt)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

def _env_str(*names: str, default: str = "") -> str:
    for name in names:
        val = os.getenv(name)
        if val is not None and str(val).strip():
            return str(val).strip()
    return default

def nopecha_enabled() -> bool:
    return _env_bool("NOPECHA_ENABLED", True)

def nopecha_api_key() -> str:
    return _env_str("NOPECHA_API_KEY", "LANDED_NOPECHA_API_KEY", default="")

def nopecha_solve_timeout_ms() -> int:
    raw = _env_str(
        "NOPECHA_SOLVE_TIMEOUT_MS",
        "LANDED_NOPECHA_SOLVE_TIMEOUT_MS",
        default="90000",
    )
    try:
        return max(5_000, int(raw))
    except ValueError:
        return 90_000

def nopecha_release_url(version: str = DEFAULT_NOPECHA_VERSION) -> str:
    return (
        "https://github.com/NopeCHALLC/nopecha-extension/releases/download/"
        f"{version}/firefox_automation.zip"
    )

def pristine_addon_dir(cache_dir: Path | None = None) -> Path:
    return (cache_dir or NOPECHA_CACHE_DIR) / "firefox_automation"

def runtime_addon_dir(cache_dir: Path | None = None) -> Path:
    return (cache_dir or NOPECHA_CACHE_DIR) / "runtime"

def looks_like_addon_dir(dir_path: Path | str | None) -> bool:
    if not dir_path:
        return False
    root = Path(dir_path)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(manifest.get("nopecha"), dict)

def apply_nopecha_settings(
    manifest: dict[str, Any],
    *,
    api_key: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    next_manifest = json.loads(json.dumps(manifest))  # deep copy
    block = next_manifest.get("nopecha")
    if not isinstance(block, dict):
        raise ValueError("NopeCHA manifest.json is missing the nopecha settings block")
    next_manifest["nopecha"] = {
        **block,
        **SOLVE_SETTINGS,
        "enabled": bool(enabled),
        "key": api_key or block.get("key") or "",
    }
    return next_manifest

def is_nopecha_out_of_credits(status: dict[str, Any] | None) -> bool:
    if not status or not isinstance(status, dict):
        return False
    code = status.get("code")
    err = status.get("error")
    if isinstance(err, dict):
        code = code if code is not None else err.get("code")
    if code == NOPECHA_OUT_OF_CREDIT_CODE:
        return True
    message = str(status.get("message") or (err.get("message") if isinstance(err, dict) else "") or "")
    if "out of credit" in message.lower():
        return True
    credit = status.get("credit")
    if isinstance(credit, (int, float)) and credit <= 0:
        return True
    if status.get("status") == "Expired" and (credit is None or credit <= 0):
        return True
    return False

def nopecha_credits_warning(status: dict[str, Any] | None = None) -> str:
    status = status or {}
    ttl = status.get("ttl")
    ttl_note = (
        f" Credits refill in about {max(1, int((ttl + 3599) // 3600))}h."
        if isinstance(ttl, (int, float)) and ttl > 0
        else " Credits usually refill every ~23 hours."
    )
    plan = f" ({status['plan']})" if status.get("plan") else ""
    return (
        f"CAPTCHA solver (NopeCHA){plan} is out of daily credits.{ttl_note}"
        " Finish the CAPTCHA yourself, wait for the refill, or set NOPECHA_API_KEY"
        " on a paid plan."
    )

def ensure_nopecha_cached(
    *,
    version: str | None = None,
    cache_dir: Path | None = None,
    force: bool = False,
) -> Path:
    """Download + extract the Firefox automation build if missing."""
    cache = Path(cache_dir or NOPECHA_CACHE_DIR)
    ver = version or _env_str(
        "NOPECHA_VERSION", "LANDED_NOPECHA_VERSION", default=DEFAULT_NOPECHA_VERSION
    )
    dest = pristine_addon_dir(cache)
    if not force and looks_like_addon_dir(dest):
        print(f"NopeCHA already cached: {dest.resolve()}", flush=True)
        return dest

    cache.mkdir(parents=True, exist_ok=True)
    zip_path = cache / f"firefox_automation-{ver}.zip"
    url = nopecha_release_url(ver)
    print(f"Downloading NopeCHA {ver} (cache only — not launching browser)…", flush=True)
    try:
        urllib.request.urlretrieve(url, zip_path)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"NopeCHA download failed: {exc} ({url})") from exc

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)

    if not looks_like_addon_dir(dest):
        kids = [p for p in dest.iterdir() if p.is_dir()]
        nested = next((p for p in kids if looks_like_addon_dir(p)), None)
        if nested:
            tmp = dest.with_suffix(".flat")
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            nested.rename(tmp)
            shutil.rmtree(dest, ignore_errors=True)
            tmp.rename(dest)

    if not looks_like_addon_dir(dest):
        raise RuntimeError(f"Extracted NopeCHA zip did not contain a manifest at {dest}")
    print(f"NopeCHA ready: {dest.resolve()}", flush=True)
    return dest

def prepare_nopecha_addon(
    *,
    enabled: bool | None = None,
    api_key: str | None = None,
    addon_dir: str | Path | None = None,
    version: str | None = None,
    cache_dir: Path | None = None,
) -> Path | None:
    """Build a Camoufox-ready addon directory. Returns the path, or None when disabled."""
    if enabled is None:
        enabled = nopecha_enabled()
    if not enabled:
        return None

    cache = Path(cache_dir or NOPECHA_CACHE_DIR)
    key = api_key if api_key is not None else nopecha_api_key()
    configured = addon_dir or _env_str("NOPECHA_ADDON_DIR", "LANDED_NOPECHA_ADDON_DIR", default="")
    source = Path(configured) if configured and looks_like_addon_dir(configured) else pristine_addon_dir(cache)

    if not looks_like_addon_dir(source):
        source = ensure_nopecha_cached(version=version, cache_dir=cache)

    runtime = runtime_addon_dir(cache)
    if runtime.exists():
        shutil.rmtree(runtime, ignore_errors=True)
    shutil.copytree(source, runtime)

    manifest_path = runtime / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    patched = apply_nopecha_settings(manifest, api_key=key, enabled=True)
    manifest_path.write_text(json.dumps(patched, indent=2) + "\n", encoding="utf-8")
    return runtime.resolve()
