"""Unit tests for auto salary expectation + apply.config override."""

from __future__ import annotations

import json
from pathlib import Path

from computer_use.config.salary import (
    enrich_profile_salary,
    expectation_from_range,
    extract_job_salary_range,
    format_salary_usd,
    parse_salary_number,
    resolve_salary_expectation,
)
from computer_use.config import load_apply_config_for_job
from computer_use.features.form_knowledge import answer_from_profile


def test_parse_salary_number_variants() -> None:
    assert parse_salary_number(120_000) == 120_000
    assert parse_salary_number("$135,000") == 135_000
    assert parse_salary_number("120k") == 120_000
    assert parse_salary_number(None) is None
    assert parse_salary_number("negotiable") is None


def test_expectation_biases_by_experience() -> None:
    junior = expectation_from_range(100_000, 160_000, years_experience=1)
    mid = expectation_from_range(100_000, 160_000, years_experience=5)
    senior = expectation_from_range(100_000, 160_000, years_experience=10)
    assert junior < mid < senior
    assert 100_000 <= junior <= 160_000
    assert junior % 5_000 == 0


def test_config_number_overrides_job_range() -> None:
    profile = {
        "years_experience": 2,
        "salary_expectation_usd": 95_000,
    }
    out = resolve_salary_expectation(
        profile,
        job={"salaryMin": 120_000, "salaryMax": 180_000, "salaryCurrency": "USD"},
    )
    assert out["salary_expectation_usd"] == 95_000
    assert "override" in out["salary_expectation_source"]


def test_auto_from_job_range_when_config_null() -> None:
    profile = {
        "years_experience": 2,
        "salary_expectation_usd": None,
    }
    out = resolve_salary_expectation(
        profile,
        job={"salaryMin": 120_000, "salaryMax": 180_000, "salaryCurrency": "USD"},
    )
    assert out["salary_expectation_usd"] == expectation_from_range(
        120_000, 180_000, years_experience=2
    )
    assert out["salary_expectation_source"].startswith("auto from job range")


def test_fallback_to_package_salary_answer() -> None:
    low, high, _ = extract_job_salary_range(
        {},
        fields={
            "answers": [
                {
                    "key": "salaryExpectation",
                    "label": "Salary expectation",
                    "text": "$135,000",
                }
            ]
        },
    )
    assert low == 135_000
    assert high == 135_000

    out = enrich_profile_salary(
        {"years_experience": 2, "salary_expectation_usd": None},
        fields={
            "answers": [
                {"key": "salaryExpectation", "text": "$135,000"},
            ]
        },
    )
    assert out["salary_expectation_usd"] == 135_000


def test_strips_underscore_help_keys() -> None:
    out = enrich_profile_salary(
        {
            "_salary_expectation_usd_help": "docs only",
            "salary_expectation_usd": None,
            "years_experience": 2,
        },
        job={"salary_min": 100_000, "salary_max": 140_000, "salary_currency": "USD"},
    )
    assert "_salary_expectation_usd_help" not in out
    assert out["salary_expectation_usd"] is not None


def test_format_and_form_kb_answer() -> None:
    assert format_salary_usd(120_000) == "$120,000"
    assert (
        answer_from_profile(
            "What are your compensation expectations?",
            {"salary_expectation_usd": 120_000},
        )
        == "$120,000"
    )


def test_load_apply_config_for_job_enriches_salary(tmp_path: Path) -> None:
    resume = tmp_path / "tailored.pdf"
    resume.write_bytes(b"%PDF-1.4 test")
    cfg_path = tmp_path / "apply.config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "job_url": "https://boards.example.com/jobs/1",
                "resume_path": "unused.pdf",
                "submit": False,
                "profile": {
                    "first_name": "Jared",
                    "years_experience": 2,
                    "salary_expectation_usd": None,
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_apply_config_for_job(
        job_url="https://jobs.lever.co/acme/abc",
        resume_path=resume,
        submit=False,
        path=cfg_path,
        job={"salaryMin": 110_000, "salaryMax": 150_000, "salaryCurrency": "USD"},
    )
    assert cfg.profile["salary_expectation_usd"] == expectation_from_range(
        110_000, 150_000, years_experience=2
    )
