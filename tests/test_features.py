"""Tests for apply feature registry compose / inject."""

from __future__ import annotations

from computer_use.features import ApplyRunContext, compose, disabled_feature_names
from computer_use.features.form_knowledge import TOOL_NAME as FORM_TOOL
from computer_use.features.hcaptcha import TOOL_NAME as HCAPTCHA_TOOL
from computer_use.features.learnings import TOOL_NAME as LEARN_TOOL
from computer_use.features.pre_submit_screenshot import TOOL_NAME as SCREENSHOT_TOOL
from computer_use.features.verification_code import TOOL_NAME as VERIFY_TOOL
from computer_use.prompts import build_prompt, build_system_instructions


def _tool_names(composed) -> set[str]:
    names: set[str] = set()
    for tool in composed.tools:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
        if name:
            names.add(str(name))
    return names


def test_default_compose_includes_core_features(monkeypatch) -> None:
    monkeypatch.delenv("APPLY_DISABLE_FEATURES", raising=False)
    ctx = ApplyRunContext(
        job_url="https://jobs.example.org/1",
        profile={"email": "a@b.com"},
        account_signup={"enabled": False},
    )
    composed = compose(ctx)
    assert "form_knowledge" in composed.names
    assert "learnings" in composed.names
    assert "account_signup" in composed.names
    assert "verification_code" not in composed.names
    assert "pre_submit_screenshot" not in composed.names
    assert "hcaptcha" not in composed.names
    names = _tool_names(composed)
    assert FORM_TOOL in names
    assert LEARN_TOOL in names
    assert VERIFY_TOOL not in names
    assert SCREENSHOT_TOOL not in names
    assert HCAPTCHA_TOOL not in names
    blob = "\n".join(composed.user_blocks) + "\n" + composed.system_instructions
    assert "resolve_form_question" in blob
    assert "record_apply_learning" in blob
    assert "ACCOUNT SIGNUP" in blob
    assert "record_employer_account" in blob
    assert "check_verification_code" not in blob
    assert "capture_pre_submit_screenshot" not in blob
    assert "solve_hcaptcha" not in blob


def test_pre_submit_screenshot_enabled_with_browser(monkeypatch) -> None:
    monkeypatch.delenv("APPLY_DISABLE_FEATURES", raising=False)

    class _Computer:
        async def capture_pre_submit_evidence(self) -> str:
            return "CAPTURED: test"

        async def solve_hcaptcha_now(self) -> str:
            return "SOLVED: test"

    ctx = ApplyRunContext(
        job_url="https://jobs.example.org/1",
        browser_computer=_Computer(),
    )
    composed = compose(ctx)
    assert "pre_submit_screenshot" in composed.names
    assert "hcaptcha" in composed.names
    names = _tool_names(composed)
    assert SCREENSHOT_TOOL in names
    assert HCAPTCHA_TOOL in names
    blob = "\n".join(composed.user_blocks) + "\n" + composed.system_instructions
    assert "capture_pre_submit_screenshot" in blob
    assert "scroll" in blob.lower() and "Submit" in blob
    assert "solve_hcaptcha" in blob


def test_verification_enabled_with_landed_client(monkeypatch) -> None:
    monkeypatch.delenv("APPLY_DISABLE_FEATURES", raising=False)

    class _Client:
        pass

    ctx = ApplyRunContext(
        job_url="https://jobs.example.org/1",
        landed_client=_Client(),  # type: ignore[arg-type]
        application_id="app-123",
        verification_since="2026-01-01T00:00:00Z",
    )
    composed = compose(ctx)
    assert "verification_code" in composed.names
    assert VERIFY_TOOL in _tool_names(composed)
    assert "check_verification_code is available" in "\n".join(composed.user_blocks)


def test_disable_features_via_env(monkeypatch) -> None:
    monkeypatch.setenv("APPLY_DISABLE_FEATURES", "learnings,form_knowledge")
    assert disabled_feature_names() == {"learnings", "form_knowledge"}
    ctx = ApplyRunContext(job_url="https://jobs.example.org/1")
    composed = compose(ctx)
    assert "learnings" not in composed.names
    assert "form_knowledge" not in composed.names
    assert "account_signup" in composed.names
    names = _tool_names(composed)
    assert FORM_TOOL not in names
    assert LEARN_TOOL not in names
    blob = composed.system_instructions + "\n".join(composed.user_blocks)
    assert "resolve_form_question" not in blob
    assert "record_apply_learning" not in blob


def test_build_prompt_injects_feature_blocks() -> None:
    prompt = build_prompt(
        job_url="https://jobs.example.org/1",
        resume_path="resumes/me.pdf",
        submit_application=False,
        feature_user_blocks=["FORM KNOWLEDGE: empty.", "ACCOUNT SIGNUP: disabled."],
    )
    assert "FORM KNOWLEDGE: empty." in prompt
    assert "ACCOUNT SIGNUP: disabled." in prompt
    assert "https://jobs.example.org/1" in prompt


def test_build_system_instructions_injects_feature_system() -> None:
    text = build_system_instructions(
        feature_system="- FORM KNOWLEDGE: call resolve_form_question only when needed."
    )
    assert "resolve_form_question" in text
    assert "Camoufox" in text
    assert "Never click captcha widgets" in text or "captcha" in text.lower()
