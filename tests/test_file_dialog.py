"""Tests for native OS file-dialog detection / close helpers."""

from __future__ import annotations

from unittest.mock import patch

import computer_use.browser.local as local


def test_is_file_dialog_title_matches_common_pickers() -> None:
    assert local.is_file_dialog_title("Open") is True
    assert local.is_file_dialog_title("File Upload") is True
    assert local.is_file_dialog_title("Choose File to Upload") is True
    assert local.is_file_dialog_title("Save As") is True
    assert local.is_file_dialog_title("Select File") is True
    assert local.is_file_dialog_title("  open  ") is True


def test_is_file_dialog_title_rejects_unrelated() -> None:
    assert local.is_file_dialog_title("") is False
    assert local.is_file_dialog_title("Camoufox") is False
    assert local.is_file_dialog_title("Job Application — Acme") is False
    assert local.is_file_dialog_title("Settings") is False
    assert local.is_file_dialog_title("Opening soon") is False


def test_close_native_file_dialogs_noop_off_windows() -> None:
    with patch.object(local.sys, "platform", "darwin"):
        assert local.close_native_file_dialogs() == 0
