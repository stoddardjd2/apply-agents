"""Unit tests for form knowledge base."""

from __future__ import annotations

import json
from pathlib import Path

from computer_use.features.form_knowledge import (
    ai_may_answer_entries,
    answer_from_profile,
    answered_entries,
    is_ai_generatable_question,
    lookup_answer,
    normalize_question,
    pending_count,
    record_question,
    resolve_form_question,
)


def test_normalize_question_strips_punct_and_case() -> None:
    assert normalize_question("  Do you have an Active Secret clearance? ") == (
        "do you have an active secret clearance"
    )


def test_record_preserves_existing_answer(tmp_path: Path) -> None:
    path = tmp_path / "form_knowledge.json"
    first = record_question(
        question="Do you have Secret clearance?",
        required=True,
        options=["Yes", "No"],
        path=path,
    )
    assert first["status"] == "pending"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"][0]["answer"] = "Yes"
    path.write_text(json.dumps(data), encoding="utf-8")

    second = record_question(
        question="Do you have Secret clearance?",
        required=True,
        company="VivSoft",
        job_url="https://example.com/job",
        path=path,
    )
    assert second["status"] == "answered"
    assert second["answer"] == "Yes"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["entries"][0]["answer"] == "Yes"
    assert saved["entries"][0]["company"] == "VivSoft"


def test_lookup_answer_only_when_filled(tmp_path: Path) -> None:
    path = tmp_path / "kb.json"
    record_question(question="Willing to relocate?", path=path)
    assert lookup_answer("Willing to relocate?", path=path) is None
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"][0]["answer"] = "No"
    path.write_text(json.dumps(data), encoding="utf-8")
    hit = lookup_answer("willing to relocate?", path=path)
    assert hit is not None
    assert hit["answer"] == "No"


def test_resolve_prefers_kb_then_profile_before_pending(tmp_path: Path) -> None:
    path = tmp_path / "kb.json"
    profile = {
        "email": "jared@example.com",
        "custom_answers": {"are_you_over_18": True},
        "require_sponsorship": False,
    }

    # Profile hit — must not create a pending entry
    msg = resolve_form_question(
        question="What is your email address?",
        profile=profile,
        path=path,
    )
    assert msg.startswith("ANSWER: jared@example.com")
    assert pending_count(path) == 0
    assert answered_entries(path) == []

    msg2 = resolve_form_question(
        question="Are you over 18?",
        profile=profile,
        path=path,
    )
    assert "ANSWER: Yes" in msg2
    assert pending_count(path) == 0

    # Unknown → pending
    msg3 = resolve_form_question(
        question="Do you have an Active Secret clearance or higher?",
        required=True,
        options=["Yes", "No"],
        company="VivSoft",
        profile=profile,
        path=path,
    )
    assert msg3.startswith("RECORDED_PENDING:")
    assert pending_count(path) == 1

    # Fill answer; next resolve returns it
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"][0]["answer"] = "No"
    path.write_text(json.dumps(data), encoding="utf-8")
    msg4 = resolve_form_question(
        question="Do you have an Active Secret clearance or higher?",
        profile=profile,
        path=path,
    )
    assert msg4 == "ANSWER: No"


def test_answer_from_profile_sponsorship_hint() -> None:
    profile = {"require_sponsorship": False}
    assert answer_from_profile(
        "Will you now or in the future require visa sponsorship?",
        profile,
    ) == "No"


def test_optional_unknown_skips_without_pending(tmp_path: Path) -> None:
    path = tmp_path / "kb.json"
    msg = resolve_form_question(
        question="What is your favorite color?",
        required=False,
        path=path,
    )
    assert msg.startswith("SKIP_OPTIONAL:")
    assert pending_count(path) == 0


def test_soft_essay_auto_generate_ok(tmp_path: Path) -> None:
    path = tmp_path / "kb.json"
    q = (
        "How would you describe CDI's mission in your own words? "
        "How does this mission align with your personal and professional values?"
    )
    assert is_ai_generatable_question(q) is True
    msg = resolve_form_question(question=q, required=True, path=path)
    assert msg.startswith("GENERATE_OK:")
    assert pending_count(path) == 0
    assert len(ai_may_answer_entries(path)) == 1
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["entries"][0]["ai_may_answer"] is True


def test_why_interested_auto_generate_ok(tmp_path: Path) -> None:
    path = tmp_path / "kb.json"
    msg = resolve_form_question(
        question="Why are you interested in Tin Can?",
        required=True,
        path=path,
    )
    assert msg.startswith("GENERATE_OK:")
    assert pending_count(path) == 0


def test_manual_ai_may_answer_flag(tmp_path: Path) -> None:
    path = tmp_path / "kb.json"
    record_question(
        question="Describe your ideal sprint cadence for this team.",
        required=True,
        path=path,
    )
    assert pending_count(path) == 1
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"][0]["ai_may_answer"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    assert pending_count(path) == 0
    assert len(ai_may_answer_entries(path)) == 1
    msg = resolve_form_question(
        question="Describe your ideal sprint cadence for this team.",
        path=path,
    )
    assert msg.startswith("GENERATE_OK:")


def test_factual_yes_no_not_auto_generate() -> None:
    assert (
        is_ai_generatable_question(
            "Do you have Secret clearance?",
            options=["Yes", "No"],
        )
        is False
    )
    assert is_ai_generatable_question("What is your expected salary?") is False
