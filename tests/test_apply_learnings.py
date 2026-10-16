"""Tests for apply_learnings tip + hard_run persistence."""

from __future__ import annotations

from pathlib import Path

from computer_use.features.learnings import (
    hard_run_turn_threshold,
    learnings_prompt_block,
    load_learnings,
    record_hard_run,
    record_tip,
)


def test_record_tip_and_prompt_block(tmp_path: Path) -> None:
    path = tmp_path / "learnings.json"
    result = record_tip(
        summary="Indeed resume picker: never re-click Upload after resume is selected",
        detail="Click Continue instead or a native dialog blocks the window.",
        board="indeed",
        job_url="https://www.indeed.com/viewjob?jk=abc",
        path=path,
    )
    assert result["ok"] is True
    data = load_learnings(path)
    assert len(data["entries"]) == 1
    assert data["entries"][0]["kind"] == "tip"
    block = learnings_prompt_block(path=path)
    assert "Indeed resume picker" in block
    assert "record_apply_learning" in block


def test_hard_run_respects_threshold(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "learnings.json"
    monkeypatch.setenv("LEARNING_TURN_THRESHOLD", "10")
    assert hard_run_turn_threshold() == 10
    assert (
        record_hard_run(
            turns=9,
            job_url="https://example.com/job",
            thinking_excerpts=["still looking for submit"],
            path=path,
        )
        is None
    )
    entry = record_hard_run(
        turns=12,
        job_url="https://example.com/job",
        company="Acme",
        thinking_excerpts=["Found the apply tab after many waits."],
        actions_summary="wait×20, click×8",
        path=path,
    )
    assert entry is not None
    assert entry["kind"] == "hard_run"
    assert entry["turns"] == 12
    assert "Found the apply tab" in entry["thinking_excerpts"][0]
    data = load_learnings(path)
    assert len(data["entries"]) == 1
