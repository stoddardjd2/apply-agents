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
    format_code_hit,
    wait_for_verification_code,
)
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


def test_build_prompt_mentions_verification_when_enabled(monkeypatch) -> None:
    monkeypatch.delenv("APPLY_DISABLE_FEATURES", raising=False)

    class _Client:
        pass

    on_ctx = ApplyRunContext(
        job_url="https://jobs.example.org/posting/1",
        landed_client=_Client(),  # type: ignore[arg-type]
        application_id="app-1",
    )
    on = compose(on_ctx)
    prompt = build_prompt(
        job_url=on_ctx.job_url,
        resume_path="resumes/me.pdf",
        submit_application=False,
        feature_user_blocks=on.user_blocks,
    )
    assert "check_verification_code is available" in prompt

    off_ctx = ApplyRunContext(job_url="https://jobs.example.org/posting/1")
    off = compose(off_ctx)
    prompt_off = build_prompt(
        job_url=off_ctx.job_url,
        resume_path="resumes/me.pdf",
        submit_application=False,
        feature_user_blocks=off.user_blocks,
    )
    assert "check_verification_code" not in prompt_off

