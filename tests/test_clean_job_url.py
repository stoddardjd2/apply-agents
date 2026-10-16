"""Tests for Landed evidence URL cleaning."""

from __future__ import annotations

from computer_use.landed.urls import (
    clean_job_url,
    evidence_job_url,
    is_post_apply_noise_url,
    job_identity_key,
)


def test_indeed_keeps_only_jk() -> None:
    messy = (
        "https://www.indeed.com/viewjob?jk=d62ca21919f334c1"
        "&advn=7372232528689910&adid=469414369"
        "&from=rjp_mob.indeedApplyAltJobs"
        "&dest=https%3A%2F%2Fclick.appcast.io%2Ft%2Fabc"
        "&utm_source=%2Fm%2F&utm_medium=redir&utm_campaign=dt"
    )
    assert clean_job_url(messy) == (
        "https://www.indeed.com/viewjob?jk=d62ca21919f334c1"
    )


def test_glassdoor_keeps_jl() -> None:
    messy = (
        "https://www.glassdoor.com/job-listing/j?jl=1010294425538"
        "&utm_source=google&ref=share"
    )
    assert clean_job_url(messy) == (
        "https://www.glassdoor.com/job-listing/j?jl=1010294425538"
    )


def test_greenhouse_strips_tracking_keeps_path() -> None:
    messy = (
        "https://job-boards.greenhouse.io/addepar1/jobs/8879308002"
        "?gh_src=abc&utm_campaign=x"
    )
    assert clean_job_url(messy) == (
        "https://job-boards.greenhouse.io/addepar1/jobs/8879308002"
    )


def test_blank_and_none() -> None:
    assert clean_job_url(None) is None
    assert clean_job_url("   ") is None


def test_indeed_alt_jobs_is_noise() -> None:
    alt = (
        "https://www.indeed.com/viewjob?jk=d62ca21919f334c1"
        "&from=rjp_mob.indeedApplyAltJobs"
    )
    assert is_post_apply_noise_url(alt) is True
    assert is_post_apply_noise_url(
        "https://www.indeed.com/viewjob?jk=d62ca21919f334c1"
    ) is False


def test_evidence_url_keeps_applied_job_not_alt() -> None:
    start = "https://www.glassdoor.com/job-listing/j?jl=1010295893629"
    alt = (
        "https://www.indeed.com/viewjob?jk=d62ca21919f334c1"
        "&from=rjp_mob.indeedApplyAltJobs&advn=1"
    )
    assert job_identity_key(start) == "glassdoor:1010295893629"
    assert job_identity_key(alt) == "indeed:d62ca21919f334c1"
    assert evidence_job_url(
        current_url=alt,
        start_url=start,
        url_before_submit="https://smartapply.indeed.com/beta/indeedapply/form",
    ) == clean_job_url(start)
