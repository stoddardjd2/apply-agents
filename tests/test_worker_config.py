"""Tests for worker blocklist / allowlist and config merge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use.config import WorkerConfig, load_apply_config_for_job, load_worker_config


def test_blocklist_matches_adapter_and_host() -> None:
    cfg = WorkerConfig(
        landed_api_base="http://localhost:8080",
        blocklist=["linkedin", "workday"],
    )
    assert cfg.is_blocked(adapter="linkedin", apply_url="https://example.com") == "linkedin"
    assert cfg.is_blocked(
        adapter="greenhouse", apply_url="https://www.linkedin.com/jobs/view/1"
    ) == "linkedin"
    assert cfg.is_blocked(
        adapter="workday", apply_url="https://company.myworkdayjobs.com/en-US/job"
    ) == "workday"
    assert (
        cfg.is_blocked(
            adapter="greenhouse",
            apply_url="https://boards.greenhouse.io/acme/jobs/1",
        )
        is None
    )


def test_allowlist_requires_match() -> None:
    cfg = WorkerConfig(
        landed_api_base="http://localhost:8080",
        blocklist=[],
        allowlist=["greenhouse"],
    )
    assert cfg.is_blocked(adapter="lever", apply_url="https://jobs.lever.co/x") is not None
    assert (
        cfg.is_blocked(
            adapter="greenhouse",
            apply_url="https://boards.greenhouse.io/acme/jobs/1",
        )
        is None
    )


def test_claim_adapters_from_allowlist() -> None:
    cfg = WorkerConfig(
        landed_api_base="http://localhost:8080",
        allowlist=["greenhouse", "lever"],
    )
    assert cfg.claim_adapters() == ["greenhouse", "lever"]
    empty = WorkerConfig(landed_api_base="http://localhost:8080", allowlist=[])
    assert empty.claim_adapters() == []


def test_load_worker_config_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WORKER_BLOCKLIST", raising=False)
    path = tmp_path / "worker.config.json"
    path.write_text(
        json.dumps({"landed_api_base": "http://127.0.0.1:9", "blocklist": ["workday"]}),
        encoding="utf-8",
    )
    cfg = load_worker_config(path)
    assert cfg.landed_api_base == "http://127.0.0.1:9"
    assert cfg.blocklist == ["workday"]


def test_load_worker_config_empty_blocklist_means_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[] must not invent a default blocklist."""
    monkeypatch.delenv("WORKER_BLOCKLIST", raising=False)
    path = tmp_path / "worker.config.json"
    path.write_text(
        json.dumps({"landed_api_base": "http://127.0.0.1:9", "blocklist": []}),
        encoding="utf-8",
    )
    cfg = load_worker_config(path)
    assert cfg.blocklist == []
    assert (
        cfg.is_blocked(
            adapter="workday",
            apply_url="https://tmobile.wd1.myworkdayjobs.com/External/job/x",
        )
        is None
    )


def test_load_worker_config_omitted_blocklist_blocks_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WORKER_BLOCKLIST", raising=False)
    path = tmp_path / "worker.config.json"
    path.write_text(
        json.dumps({"landed_api_base": "http://127.0.0.1:9"}),
        encoding="utf-8",
    )
    cfg = load_worker_config(path)
    assert cfg.blocklist == []


def test_load_worker_config_blocklist_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKER_BLOCKLIST", "linkedin, workday")
    path = tmp_path / "worker.config.json"
    path.write_text(
        json.dumps({"landed_api_base": "http://127.0.0.1:9", "blocklist": []}),
        encoding="utf-8",
    )
    cfg = load_worker_config(path)
    assert cfg.blocklist == ["linkedin", "workday"]


def test_load_apply_config_for_job_overrides_cover(tmp_path: Path) -> None:
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
                    "cover_letter": "generic letter",
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_apply_config_for_job(
        job_url="https://jobs.lever.co/acme/abc",
        resume_path=resume,
        cover_letter="tailored for this role",
        submit=False,
        path=cfg_path,
    )
    assert cfg.job_url.endswith("/abc")
    assert cfg.resume_path == resume.resolve()
    assert cfg.profile["cover_letter"] == "tailored for this role"
    assert cfg.profile["first_name"] == "Jared"
    assert cfg.submit is False
