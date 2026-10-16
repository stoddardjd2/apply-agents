"""Unit tests for NoneCap helpers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from computer_use.captcha.nonecap import (
    EXTRACT_HCAPTCHA_JS,
    build_inject_token_script,
    nonecap_enabled,
    solve_hcaptcha,
)

def test_extract_and_inject_scripts_are_nonempty() -> None:
    assert "data-sitekey" in EXTRACT_HCAPTCHA_JS
    script = build_inject_token_script("P1_test", "E0_key")
    assert "h-captcha-response" in script
    assert "P1_test" in script
    assert "E0_key" in script
    assert "ensureField" in script

def test_nonecap_enabled_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NONECAP_KEY", raising=False)
    monkeypatch.delenv("NONECAP_API_KEY", raising=False)
    monkeypatch.setenv("NONECAP_ENABLED", "1")
    assert nonecap_enabled() is False
    monkeypatch.setenv("NONECAP_KEY", "nc_live_test")
    assert nonecap_enabled() is True
    monkeypatch.setenv("NONECAP_ENABLED", "0")
    assert nonecap_enabled() is False

def test_solve_hcaptcha_posts_wait_and_returns_token() -> None:
    payload = {
        "id": "solve_test",
        "status": "solved",
        "token": "P1_test_token",
    }
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps(payload).encode("utf-8")
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False

    with patch("computer_use.captcha.nonecap.urllib.request.urlopen", return_value=fake_resp) as mock_open:
        result = solve_hcaptcha(
            sitekey="f5ab1c2d-7e8f-4a9b-b1c2-d3e4f5a6b7c8",
            url="https://example.com/apply",
            api_key="nc_live_test",
            wait_seconds=30,
            user_agent="Mozilla/5.0 (Windows NT 10.0; rv:135.0) Gecko/20100101 Firefox/135.0",
        )

    assert result["token"] == "P1_test_token"
    req = mock_open.call_args[0][0]
    assert "wait=30" in req.full_url
    assert req.get_header("Authorization") == "Bearer nc_live_test"
    body = json.loads(req.data.decode("utf-8"))
    assert body["type"] == "hcaptcha"
    assert body["sitekey"].startswith("f5ab1c2d")
    assert "Firefox" in body["user_agent"]

def test_solve_hcaptcha_enterprise_sends_rqdata() -> None:
    payload = {"id": "solve_ent", "status": "solved", "token": "P1_ent"}
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps(payload).encode("utf-8")
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False

    with patch("computer_use.captcha.nonecap.urllib.request.urlopen", return_value=fake_resp) as mock_open:
        solve_hcaptcha(
            sitekey="f5ab1c2d-7e8f-4a9b-b1c2-d3e4f5a6b7c8",
            url="https://example.com/apply",
            rqdata="rqdata-blob",
            api_key="nc_live_test",
        )

    body = json.loads(mock_open.call_args[0][0].data.decode("utf-8"))
    assert body["type"] == "hcaptcha_enterprise"
    assert body["rqdata"] == "rqdata-blob"
