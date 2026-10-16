"""Tests for agent final-report → exit mapping."""

from __future__ import annotations

from computer_use.browser.local import (
    EXIT_NEEDS_HUMAN,
    EXIT_POSTING_UNAVAILABLE,
    _agent_reported_not_submitted,
    _agent_reported_posting_unavailable,
    looks_posting_unavailable,
)


def test_detects_application_submitted_no() -> None:
    assert _agent_reported_not_submitted("**Application submitted:** No\nDone.")


def test_detects_blocked_section() -> None:
    report = """
- **Job:** Ground Station Software Engineer
- **Blocked:** The required question asks whether you are willing to work onsite.
"""
    assert _agent_reported_not_submitted(report)


def test_detects_pending_language() -> None:
    assert _agent_reported_not_submitted(
        "The question has been recorded as pending for you to answer."
    )


def test_submitted_yes_is_not_blocked() -> None:
    assert not _agent_reported_not_submitted("**Application submitted:** Yes")


def test_needs_human_exit_code() -> None:
    assert EXIT_NEEDS_HUMAN == 3


def test_posting_unavailable_exit_code() -> None:
    assert EXIT_POSTING_UNAVAILABLE == 5


def test_detects_posting_status_unavailable() -> None:
    report = (
        "**Application submitted:** No\n"
        "**Posting status:** unavailable\n"
        "This role is no longer accepting applications."
    )
    assert _agent_reported_posting_unavailable(report)
    assert not _agent_reported_not_submitted(report)


def test_detects_posting_status_closed() -> None:
    assert _agent_reported_posting_unavailable(
        "**Application submitted:** No\n**Posting status:** closed"
    )


def test_looks_posting_unavailable_page_copy() -> None:
    assert looks_posting_unavailable("Sorry, this job is no longer available.")
    assert looks_posting_unavailable("This position has been filled.")
    assert looks_posting_unavailable("Page not found")
    assert not looks_posting_unavailable("Please enter your email address.")
