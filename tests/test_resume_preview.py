"""Tests for OPEN_RESUME_PREVIEW helper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import computer_use.browser.local as local


def test_resume_preview_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("OPEN_RESUME_PREVIEW", raising=False)
    assert local.resume_preview_enabled() is False
    assert local.open_resume_preview(Path("missing.pdf")) is False


def test_resume_preview_enabled_truthy(monkeypatch) -> None:
    monkeypatch.setenv("OPEN_RESUME_PREVIEW", "1")
    assert local.resume_preview_enabled() is True
    monkeypatch.setenv("OPEN_RESUME_PREVIEW", "false")
    assert local.resume_preview_enabled() is False


def test_open_resume_preview_launches_viewer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPEN_RESUME_PREVIEW", "yes")
    pdf = tmp_path / "Jared Resume.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    with patch.object(local.os, "startfile", create=True) as startfile:
        with patch.object(local.sys, "platform", "win32"):
            assert local.open_resume_preview(pdf) is True
        startfile.assert_called_once_with(str(pdf.resolve()))


def test_open_resume_preview_missing_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPEN_RESUME_PREVIEW", "1")
    assert local.open_resume_preview(tmp_path / "nope.pdf") is False
