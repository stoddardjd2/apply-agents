"""Tests for hidden ATS application-iframe detection helpers."""

from __future__ import annotations

import computer_use.browser.local as local


def test_frame_looks_like_ats_greenhouse_embed() -> None:
    assert local._frame_looks_like_ats(
        "https://job-boards.greenhouse.io/embed/job_app?for=houserx&token=abc",
        "grnhse_iframe",
    )
    assert local._frame_looks_like_ats(
        "https://boards.greenhouse.io/embed/job_app?for=acme",
        "",
    )
    assert local._frame_looks_like_ats("", "grnhse_iframe")


def test_frame_looks_like_ats_other_boards() -> None:
    assert local._frame_looks_like_ats("https://jobs.lever.co/acme/abc", "")
    assert local._frame_looks_like_ats("https://jobs.ashbyhq.com/acme/abc", "")
    assert local._frame_looks_like_ats(
        "https://acme.myworkdayjobs.com/en-US/careers/job/1", ""
    )


def test_frame_looks_like_ats_rejects_captcha_and_noise() -> None:
    assert not local._frame_looks_like_ats(
        "https://www.recaptcha.net/recaptcha/enterprise/anchor?k=abc",
        "a-xyz",
    )
    assert not local._frame_looks_like_ats(
        "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/…",
        "",
    )
    assert not local._frame_looks_like_ats("https://www.houserx.com/careers", "")
    assert not local._frame_looks_like_ats("about:blank", "")


def test_reveal_js_targets_hidden_ancestors_and_size() -> None:
    js = local.LocalCamoufoxComputer._REVEAL_HIDDEN_ATS_IFRAME_JS
    assert "is-hidden" in js
    assert "min-height" in js
    assert "setProperty" in js
