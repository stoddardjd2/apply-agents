"""Unit tests for Landed Gmail verification-code client + agent helper."""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import urllib.error

from computer_use.landed.client import LandedApiError, LandedClient
from computer_use.features.verification_code import (
    check_verification_code_message,
    check_verification_link_message,
    format_code_hit,
    format_link_hit,
    wait_for_verification_code,
    wait_for_verification_link,
)
from computer_use.features.verification_code.service import soft_company_token
from computer_use.features.verification_code.tool import build_tools
from computer_use.features import ApplyRunContext, compose
from computer_use.prompts import build_prompt


def _client() -> LandedClient:
    return LandedClient(api_base="http://localhost:8180", worker_token="test-token")


def _http_response(*, status: int, body: bytes | None) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body or b""
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = None
    return resp


def test_verification_code_returns_hit() -> None:
    payload = {
        "code": "482913",
        "subject": "Your security code",
        "from": "noreply@greenhouse.io",
        "receivedAt": "2026-10-16T00:00:00Z",
        "messageId": "msg-1",
    }
    with patch(
        "urllib.request.urlopen",
        return_value=_http_response(status=200, body=json.dumps(payload).encode()),
    ):
        hit = _client().verification_code(
            "00000000-0000-0000-0000-000000000001",
            since="2026-10-16T00:00:00Z",
            company="Acme",
        )
    assert hit is not None
    assert hit["code"] == "482913"


def test_verification_code_204_returns_none() -> None:
    with patch(
        "urllib.request.urlopen",
        return_value=_http_response(status=204, body=b""),
    ):
        hit = _client().verification_code("00000000-0000-0000-0000-000000000001")
    assert hit is None


def test_verification_code_409_raises() -> None:
    err = urllib.error.HTTPError(
        url="http://x",
        code=409,
        msg="Conflict",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error":"tracking.gmail_not_configured"}'),
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(LandedApiError) as exc_info:
            _client().verification_code("00000000-0000-0000-0000-000000000001")
    assert exc_info.value.status == 409


def test_format_code_hit() -> None:
    assert (
        format_code_hit(
            {
                "code": "123456",
                "from": "a@b.com",
                "subject": "Your code",
            }
        )
        == "CODE: 123456 (from: a@b.com; subject: Your code)"
    )


def test_verification_link_returns_hit() -> None:
    payload = {
        "url": "https://bcbst.wd1.myworkdayjobs.com/login/verify?token=abc",
        "subject": "Verify your account",
        "from": "noreply@myworkday.com",
        "receivedAt": "2026-10-16T00:00:00Z",
        "messageId": "msg-2",
    }
    with patch(
        "urllib.request.urlopen",
        return_value=_http_response(status=200, body=json.dumps(payload).encode()),
    ):
        hit = _client().verification_link(
            "00000000-0000-0000-0000-000000000001",
            since="2026-10-16T00:00:00Z",
            company="BCBST",
        )
    assert hit is not None
    assert "myworkdayjobs.com" in hit["url"]


def test_verification_link_204_returns_none() -> None:
    with patch(
        "urllib.request.urlopen",
        return_value=_http_response(status=204, body=b""),
    ):
        hit = _client().verification_link("00000000-0000-0000-0000-000000000001")
    assert hit is None


def test_verification_link_409_raises() -> None:
    err = urllib.error.HTTPError(
        url="http://x",
        code=409,
        msg="Conflict",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error":"tracking.gmail_not_configured"}'),
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(LandedApiError) as exc_info:
            _client().verification_link("00000000-0000-0000-0000-000000000001")
    assert exc_info.value.status == 409


def test_format_link_hit() -> None:
    assert (
        format_link_hit(
            {
                "url": "https://example.com/verify?t=1",
                "from": "a@b.com",
                "subject": "Verify",
            }
        )
        == "LINK: https://example.com/verify?t=1 (from: a@b.com; subject: Verify)"
    )


class _FakeClock:
    """Advances on sleep so poll loops finish instantly in tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += float(seconds)


def test_wait_polls_until_hit() -> None:
    client = MagicMock()
    client.verification_code.side_effect = [
        None,
        None,
        {"code": "999111", "from": "x@y.com", "subject": "OTP"},
    ]
    clock = _FakeClock()
    hit = wait_for_verification_code(
        client,
        "app-1",
        since="2026-10-16T00:00:00Z",
        company="Acme",
        timeout_s=30,
        poll_s=1,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert hit is not None
    assert hit["code"] == "999111"
    assert client.verification_code.call_count == 3


def test_wait_raises_on_409() -> None:
    client = MagicMock()
    client.verification_code.side_effect = LandedApiError("no gmail", status=409)
    clock = _FakeClock()

    with pytest.raises(LandedApiError) as exc_info:
        wait_for_verification_code(
            client,
            "app-1",
            timeout_s=10,
            poll_s=1,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
    assert exc_info.value.status == 409


def test_check_message_unavailable_without_client() -> None:
    msg = check_verification_code_message(None, None)
    assert msg.startswith("UNAVAILABLE:")


def test_check_message_code_and_step() -> None:
    client = MagicMock()
    client.verification_code.return_value = {
        "code": "555666",
        "from": "hr@co.com",
        "subject": "Code",
        "messageId": "m1",
    }
    steps: list[tuple[str, dict[str, Any]]] = []
    clock = _FakeClock()
    msg = check_verification_code_message(
        client,
        "app-1",
        default_company="Co",
        timeout_s=5,
        poll_s=1,
        on_step=lambda status, detail: steps.append((status, detail)),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert msg.startswith("CODE: 555666")
    assert steps and steps[0][0] == "ok"


def test_check_message_not_found() -> None:
    client = MagicMock()
    client.verification_code.return_value = None
    clock = _FakeClock()
    msg = check_verification_code_message(
        client,
        "app-1",
        timeout_s=5,
        poll_s=1,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert msg.startswith("NOT_FOUND:")


def test_check_message_gmail_unavailable() -> None:
    client = MagicMock()
    client.verification_code.side_effect = LandedApiError("off", status=409)
    clock = _FakeClock()
    msg = check_verification_code_message(
        client,
        "app-1",
        timeout_s=5,
        poll_s=1,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert msg.startswith("UNAVAILABLE:")
    assert "Gmail" in msg


def test_wait_link_polls_until_hit() -> None:
    client = MagicMock()
    client.verification_link.side_effect = [
        None,
        {"url": "https://example.com/verify", "from": "x@y.com", "subject": "Verify"},
    ]
    clock = _FakeClock()
    hit = wait_for_verification_link(
        client,
        "app-1",
        since="2026-10-16T00:00:00Z",
        company="Acme",
        timeout_s=30,
        poll_s=1,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert hit is not None
    assert hit["url"] == "https://example.com/verify"
    assert client.verification_link.call_count == 2


def test_check_link_message_and_step() -> None:
    client = MagicMock()
    client.verification_link.return_value = {
        "url": "https://example.com/verify?t=9",
        "from": "hr@co.com",
        "subject": "Verify",
        "messageId": "m2",
    }
    steps: list[tuple[str, dict[str, Any]]] = []
    clock = _FakeClock()
    msg = check_verification_link_message(
        client,
        "app-1",
        default_company="Co",
        timeout_s=5,
        poll_s=1,
        on_step=lambda status, detail: steps.append((status, detail)),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert msg.startswith("LINK: https://example.com/verify")
    assert steps and steps[0][0] == "ok"
    assert steps[0][1].get("kind") == "link"


def test_check_link_message_gmail_unavailable() -> None:
    client = MagicMock()
    client.verification_link.side_effect = LandedApiError("off", status=409)
    clock = _FakeClock()
    msg = check_verification_link_message(
        client,
        "app-1",
        timeout_s=5,
        poll_s=1,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert msg.startswith("UNAVAILABLE:")
    assert "Gmail" in msg


def test_build_tools_includes_link_when_browser_present() -> None:
    class _Client:
        pass

    class _Browser:
        async def open_url(self, url: str) -> str:
            return f"OPENED: {url}"

    ctx = ApplyRunContext(
        job_url="https://jobs.example.org/posting/1",
        landed_client=_Client(),  # type: ignore[arg-type]
        application_id="app-1",
        browser_computer=_Browser(),
    )
    tools = build_tools(ctx)
    tool_names = {
        getattr(t, "name", None) or getattr(t, "__name__", str(t)) for t in tools
    }
    assert "check_verification_code" in tool_names
    assert "open_verification_link" in tool_names

    no_browser = ApplyRunContext(
        job_url="https://jobs.example.org/posting/1",
        landed_client=_Client(),  # type: ignore[arg-type]
        application_id="app-1",
    )
    tools_no = build_tools(no_browser)
    names_no = {
        getattr(t, "name", None) or getattr(t, "__name__", str(t)) for t in tools_no
    }
    assert "check_verification_code" in names_no
    assert "open_verification_link" not in names_no


def test_build_prompt_mentions_verification_when_enabled(monkeypatch) -> None:
    monkeypatch.delenv("APPLY_DISABLE_FEATURES", raising=False)

    class _Client:
        pass

    class _Browser:
        pass

    on_ctx = ApplyRunContext(
        job_url="https://jobs.example.org/posting/1",
        landed_client=_Client(),  # type: ignore[arg-type]
        application_id="app-1",
        browser_computer=_Browser(),
    )
    on = compose(on_ctx)
    prompt = build_prompt(
        job_url=on_ctx.job_url,
        resume_path="resumes/me.pdf",
        submit_application=False,
        feature_user_blocks=on.user_blocks,
    )
    assert "check_verification_code is available" in prompt
    assert "open_verification_link is available" in prompt

    off_ctx = ApplyRunContext(job_url="https://jobs.example.org/posting/1")
    off = compose(off_ctx)
    prompt_off = build_prompt(
        job_url=off_ctx.job_url,
        resume_path="resumes/me.pdf",
        submit_application=False,
        feature_user_blocks=off.user_blocks,
    )
    assert "check_verification_code" not in prompt_off
    assert "open_verification_link" not in prompt_off


def test_soft_company_token_prefers_acronym() -> None:
    assert (
        soft_company_token("BCBST BlueCross BlueShield of Tennessee, Inc.")
        == "BCBST"
    )
    assert soft_company_token("Twilio") == "Twilio"
    assert soft_company_token("Amazon Web Services (AWS)") == "Amazon"
    assert soft_company_token("  ") is None
    assert soft_company_token(None) is None

