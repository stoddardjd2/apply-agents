"""Unit tests for apply config and prompts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use.config import load_apply_config
from computer_use.costs import estimate_cost_usd
from computer_use.features import ApplyRunContext, compose
from computer_use.prompts import build_prompt


def test_build_prompt_requires_job_url_and_resume() -> None:
    prompt = build_prompt(
        job_url="https://jobs.example.org/posting/123",
        resume_path="resumes/resume.pdf",
        submit_application=False,
        profile={"first_name": "Jared", "email": "j@example.com"},
    )
    assert "https://jobs.example.org/posting/123" in prompt
    assert "resume.pdf" in prompt
    assert "Jared" in prompt
    assert "STOP without clicking the final Submit" in prompt
    assert "at most ONE time" in prompt


def test_build_prompt_submit_mode() -> None:
    prompt = build_prompt(
        job_url="https://jobs.example.org/posting/123",
        resume_path="C:/docs/me.pdf",
        submit_application=True,
        profile={"full_name": "Jared Stoddard"},
    )
    assert "submit" in prompt.lower()
    assert "me.pdf" in prompt
    assert "Jared Stoddard" in prompt


def test_build_prompt_account_signup_rules(monkeypatch) -> None:
    monkeypatch.delenv("APPLY_DISABLE_FEATURES", raising=False)
    ctx = ApplyRunContext(
        job_url="https://jobs.example.org/posting/123",
        profile={"email": "applicant@example.com"},
        account_signup={
            "enabled": True,
            "create_on_non_major_employers": True,
            "email": "applicant@example.com",
            "password": "secret-pass",
            "prefer_google_sso": True,
            "major_employers": ["Google", "Microsoft"],
        },
    )
    composed = compose(ctx)
    prompt = build_prompt(
        job_url=ctx.job_url,
        resume_path="resumes/resume.pdf",
        submit_application=False,
        profile=ctx.profile,
        feature_user_blocks=composed.user_blocks,
    )
    assert "ACCOUNT SIGNUP" in prompt
    assert "applicant@example.com" in prompt
    assert "secret-pass" in prompt
    assert "Google" in prompt
    assert "major" in prompt.lower()


def test_luna_is_cheaper_than_astra() -> None:
    luna = estimate_cost_usd(
        model="gpt-6-luna", input_tokens=100_000, cached_tokens=0, output_tokens=10_000
    )
    astra = estimate_cost_usd(
        model="gpt-6-astra", input_tokens=100_000, cached_tokens=0, output_tokens=10_000
    )
    assert luna is not None and astra is not None
    assert luna < astra


def test_load_apply_config(tmp_path: Path) -> None:
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test")
    cfg_path = tmp_path / "apply.config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "job_url": "https://boards.example.com/jobs/42",
                "resume_path": str(resume.name),
                "submit": False,
                "profile": {"first_name": "Jared", "github_url": "https://github.com/stoddardjd2"},
            }
        ),
        encoding="utf-8",
    )
    cfg = load_apply_config(cfg_path)
    assert cfg.job_url.endswith("/42")
    assert cfg.resume_path == resume.resolve()
    assert cfg.submit is False
    assert cfg.profile["first_name"] == "Jared"
    assert cfg.account_signup == {}


def test_load_apply_config_rejects_placeholder(tmp_path: Path) -> None:
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test")
    cfg_path = tmp_path / "apply.config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "job_url": "https://example.com/jobs/your-listing",
                "resume_path": "resume.pdf",
                "submit": False,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="placeholder"):
        load_apply_config(cfg_path)
