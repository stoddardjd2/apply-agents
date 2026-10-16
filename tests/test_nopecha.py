"""Unit tests for NopeCHA addon helpers (mirrors landed's nopecha.test.js)."""

from __future__ import annotations

import json
from pathlib import Path

from computer_use.captcha.nopecha import (
    apply_nopecha_settings,
    is_nopecha_out_of_credits,
    looks_like_addon_dir,
    nopecha_credits_warning,
    nopecha_release_url,
    prepare_nopecha_addon,
)

def test_nopecha_release_url_pins_firefox_automation() -> None:
    url = nopecha_release_url("0.6.1")
    assert url.endswith("firefox_automation.zip")
    assert "/0.6.1/" in url

def test_apply_nopecha_settings_solves_without_early_auto_open() -> None:
    patched = apply_nopecha_settings(
        {
            "nopecha": {
                "key": "",
                "enabled": True,
                "turnstile_auto_solve": True,
                "perimeterx_auto_solve": False,
                "awscaptcha_auto_solve": False,
                "recaptcha_auto_open": True,
            }
        },
        api_key="test-key",
    )
    assert patched["nopecha"]["key"] == "test-key"
    assert patched["nopecha"]["perimeterx_auto_solve"] is True
    assert patched["nopecha"]["awscaptcha_auto_solve"] is True
    assert patched["nopecha"]["funcaptcha_auto_solve"] is True
    # Keep auto_open off so tokens are not minted while the form is still filling.
    assert patched["nopecha"]["recaptcha_auto_open"] is False
    assert patched["nopecha"]["awscaptcha_auto_open"] is False
    assert patched["nopecha"]["funcaptcha_auto_open"] is False
    assert patched["nopecha"]["recaptcha_auto_solve"] is True
    assert patched["nopecha"]["hcaptcha_auto_open"] is False
    assert patched["nopecha"]["hcaptcha_auto_solve"] is False  # NoneCap owns hCaptcha

def test_prepare_nopecha_addon_copies_and_patches(tmp_path: Path) -> None:
    pristine = tmp_path / "firefox_automation"
    pristine.mkdir()
    (pristine / "manifest.json").write_text(
        json.dumps(
            {
                "name": "NopeCHA",
                "nopecha": {
                    "key": "",
                    "enabled": True,
                    "turnstile_auto_solve": True,
                    "perimeterx_auto_solve": False,
                },
            }
        ),
        encoding="utf-8",
    )
    assert looks_like_addon_dir(pristine)

    runtime = prepare_nopecha_addon(
        enabled=True,
        api_key="runtime-key",
        cache_dir=tmp_path,
    )
    assert runtime is not None
    manifest = json.loads((runtime / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["nopecha"]["key"] == "runtime-key"
    assert manifest["nopecha"]["perimeterx_auto_solve"] is True
    pristine_manifest = json.loads((pristine / "manifest.json").read_text(encoding="utf-8"))
    assert pristine_manifest["nopecha"]["key"] == ""

def test_prepare_nopecha_addon_returns_none_when_disabled() -> None:
    assert prepare_nopecha_addon(enabled=False) is None

def test_is_nopecha_out_of_credits() -> None:
    assert is_nopecha_out_of_credits({"credit": 0, "status": "Expired"}) is True
    assert is_nopecha_out_of_credits({"credit": 12, "status": "Active"}) is False
    assert is_nopecha_out_of_credits({"code": 16, "message": "Out of credit"}) is True

def test_nopecha_credits_warning_mentions_refill() -> None:
    msg = nopecha_credits_warning({"plan": "Free", "ttl": 7200})
    assert "NopeCHA" in msg
    assert "credit" in msg.lower()
