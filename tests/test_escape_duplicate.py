"""Escape-aggregator duplicate ack → abort apply (no double submit)."""

from __future__ import annotations

import pytest

from computer_use.browser.local import (
    EXIT_DUPLICATE,
    EscapeDuplicateAbort,
    LocalCamoufoxComputer,
)


def test_maybe_report_escape_aborts_when_callback_returns_true() -> None:
    calls: list[tuple[str, str, str]] = []

    def on_escape(url: str, adapter: str, via: str) -> bool:
        calls.append((url, adapter, via))
        return True

    comp = object.__new__(LocalCamoufoxComputer)
    comp._started_on_aggregator = True
    comp._escape_reported = False
    comp._escape_duplicate = False
    comp._on_escape_aggregator = on_escape

    ats = "https://boards.greenhouse.io/acme/jobs/99"
    with pytest.raises(EscapeDuplicateAbort):
        comp._maybe_report_escape(ats, via="openForm_redirect")
    assert calls == [(ats, "greenhouse", "openForm_redirect")]
    assert comp._escape_duplicate is True
    assert comp._escape_reported is True


def test_maybe_report_escape_continues_when_callback_returns_false() -> None:
    comp = object.__new__(LocalCamoufoxComputer)
    comp._started_on_aggregator = True
    comp._escape_reported = False
    comp._escape_duplicate = False
    comp._on_escape_aggregator = lambda url, adapter, via: False

    comp._maybe_report_escape(
        "https://boards.greenhouse.io/acme/jobs/1", via="employer_site"
    )
    assert comp._escape_duplicate is False
    assert comp._escape_reported is True


def test_report_escape_duplicate_ack_signals_abort() -> None:
    from computer_use.worker import escape_step_should_abort

    assert escape_step_should_abort(
        {"duplicate": True, "cancelled": True, "reasonCode": "eligibility.already_applied"}
    )
    assert escape_step_should_abort({"duplicate": False, "cancelled": True})
    assert not escape_step_should_abort({"duplicate": False, "cancelled": False})
    assert not escape_step_should_abort(None)
    assert EXIT_DUPLICATE == 4
