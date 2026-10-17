"""Tests for employer_accounts.json credential store + signup prompt injection."""

from __future__ import annotations

from pathlib import Path

from computer_use.features.account_signup.prompts import user_prompt_block
from computer_use.features.account_signup.service import (
    find_accounts_for_site,
    format_accounts_for_prompt,
    host_from_url,
    upsert_account,
)
from computer_use.features.account_signup.tool import TOOL_NAME, build_tools
from computer_use.features.base import ApplyRunContext
from computer_use.features.registry import compose


def test_host_from_url() -> None:
    assert host_from_url("https://bcbst.wd1.myworkdayjobs.com/External/job/1") == (
        "bcbst.wd1.myworkdayjobs.com"
    )
    assert host_from_url("https://www.example.com/x") == "example.com"


def test_upsert_and_find(tmp_path: Path) -> None:
    path = tmp_path / "employer_accounts.json"
    created = upsert_account(
        email="me@example.com",
        password="secret123",
        site_url="https://bcbst.wd1.myworkdayjobs.com/External/login",
        company="BCBST BlueCross BlueShield of Tennessee, Inc.",
        verification_status="needs_verification",
        path=path,
    )
    assert created["ok"] is True
    assert created["message"] == "created"
    assert created["account"]["verification_status"] == "needs_verification"

    found = find_accounts_for_site(
        site_url="https://bcbst.wd1.myworkdayjobs.com/External/job/usa/x",
        path=path,
    )
    assert len(found) == 1
    assert found[0]["email"] == "me@example.com"
    assert found[0]["password"] == "secret123"

    updated = upsert_account(
        email="me@example.com",
        password="secret123",
        site_url="https://bcbst.wd1.myworkdayjobs.com/External/login",
        verification_status="verified",
        path=path,
    )
    assert updated["ok"] is True
    assert updated["message"] == "updated"
    assert updated["account"]["verification_status"] == "verified"


def test_prompt_includes_saved_account(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "employer_accounts.json"
    monkeypatch.setenv("EMPLOYER_ACCOUNTS_PATH", str(path))
    upsert_account(
        email="me@example.com",
        password="secret123",
        site_url="https://careers.example.com/apply/1",
        company="ExampleCo",
        verification_status="verified",
        path=path,
    )
    ctx = ApplyRunContext(
        job_url="https://careers.example.com/jobs/99",
        company="ExampleCo",
        account_signup={
            "enabled": True,
            "email": "me@example.com",
            "password": "secret123",
            "create_on_non_major_employers": True,
        },
    )
    block = user_prompt_block(ctx)
    assert "SAVED EMPLOYER ACCOUNTS" in block
    assert "me@example.com" in block
    assert "secret123" in block
    assert "verification=verified" in block
    assert "record_employer_account" in block
    assert "Prefer Sign In" in block
    # Verified accounts must not push open_verification_link at session start.
    saved = block.split("SAVED EMPLOYER ACCOUNTS", 1)[1]
    assert "call open_verification_link at session start" not in saved.lower()


def test_format_accounts_needs_verification_resend_hint() -> None:
    text = format_accounts_for_prompt(
        [
            {
                "host": "jobs.example.com",
                "email": "a@b.com",
                "password": "pw",
                "verification_status": "needs_verification",
                "company": "Acme",
                "site_url": "https://jobs.example.com/",
            }
        ]
    )
    assert "a@b.com" in text
    assert "verification=needs_verification" in text
    assert "Do NOT call open_verification_link at session start" in text
    assert "Resend" in text
    assert "open_verification_link" in text
    assert "Prefer Sign In" in text


def test_compose_includes_record_tool(monkeypatch) -> None:
    monkeypatch.delenv("APPLY_DISABLE_FEATURES", raising=False)
    ctx = ApplyRunContext(
        job_url="https://jobs.example.org/1",
        account_signup={"enabled": True, "email": "a@b.com", "password": "x"},
    )
    composed = compose(ctx)
    names = {
        getattr(t, "name", None) or getattr(t, "__name__", str(t))
        for t in composed.tools
    }
    assert TOOL_NAME in names
    tools = build_tools(ctx)
    assert len(tools) == 1
