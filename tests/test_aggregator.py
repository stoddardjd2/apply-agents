"""Tests for aggregator escape detection and one-shot reporting."""

from __future__ import annotations

from computer_use.browser.local import LocalCamoufoxComputer
from computer_use.landed.aggregator import adapter_for_url, is_aggregator_host


def test_is_aggregator_host() -> None:
    assert is_aggregator_host("https://www.glassdoor.com/job-listing/j?jl=1")
    assert is_aggregator_host("https://www.indeed.com/viewjob?jk=abc")
    assert is_aggregator_host("https://smartapply.indeed.com/beta/indeedapply/form")
    assert not is_aggregator_host("https://boards.greenhouse.io/acme/jobs/1")
    assert not is_aggregator_host("https://vivsofttechnologiesfa.applytojob.com/apply/x")
    assert not is_aggregator_host("")
    assert not is_aggregator_host(None)


def test_adapter_for_url() -> None:
    assert adapter_for_url("https://job-boards.greenhouse.io/acme/jobs/1") == "greenhouse"
    assert adapter_for_url("https://jobs.lever.co/acme/abc") == "lever"
    assert adapter_for_url("https://jobs.ashbyhq.com/acme/abc") == "ashby"
    assert adapter_for_url(
        "https://vivsofttechnologiesfa.applytojob.com/apply/G1EVapDRUh/Full-Stack-Developer"
    ) == "jazzhr"
    assert adapter_for_url("https://www.glassdoor.com/job-listing/j?jl=1") == "glassdoor"
    assert adapter_for_url("https://careers.acme.com/jobs/1") == "generic"


def test_maybe_report_escape_fires_once() -> None:
    calls: list[tuple[str, str, str]] = []

    def on_escape(url: str, adapter: str, via: str) -> bool:
        calls.append((url, adapter, via))
        return False

    comp = object.__new__(LocalCamoufoxComputer)
    comp._started_on_aggregator = True
    comp._escape_reported = False
    comp._escape_duplicate = False
    comp._on_escape_aggregator = on_escape

    gd = "https://www.glassdoor.com/job-listing/j?jl=1"
    ats = "https://boards.greenhouse.io/acme/jobs/99"

    # Still on aggregator — no report
    comp._maybe_report_escape(gd, via="employer_site")
    assert calls == []
    assert comp._escape_reported is False

    # Left aggregator
    comp._maybe_report_escape(ats, via="openForm_redirect")
    assert len(calls) == 1
    assert calls[0] == (ats, "greenhouse", "openForm_redirect")
    assert comp._escape_reported is True

    # Second navigation must not re-post
    comp._maybe_report_escape(
        "https://vivsofttechnologiesfa.applytojob.com/apply/x",
        via="employer_site",
    )
    assert len(calls) == 1


def test_maybe_report_escape_skips_when_not_started_on_aggregator() -> None:
    calls: list[tuple[str, str, str]] = []

    def on_escape(url: str, adapter: str, via: str) -> bool:
        calls.append((url, adapter, via))
        return False

    comp = object.__new__(LocalCamoufoxComputer)
    comp._started_on_aggregator = False
    comp._escape_reported = False
    comp._escape_duplicate = False
    comp._on_escape_aggregator = on_escape

    comp._maybe_report_escape("https://boards.greenhouse.io/acme/jobs/1", via="employer_site")
    assert calls == []
