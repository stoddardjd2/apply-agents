"""Unit tests for Landed artifact upload helpers."""

from __future__ import annotations

import pytest

from computer_use.landed.client import MAX_ARTIFACT_BYTES, LandedApiError, LandedClient


def test_artifact_rejects_empty() -> None:
    client = LandedClient(
        api_base="http://localhost:8180",
        worker_token="test-token",
    )
    with pytest.raises(LandedApiError, match="empty"):
        client.artifact("00000000-0000-0000-0000-000000000001", data=b"")


def test_artifact_rejects_oversize() -> None:
    client = LandedClient(
        api_base="http://localhost:8180",
        worker_token="test-token",
    )
    with pytest.raises(LandedApiError, match="exceeds"):
        client.artifact(
            "00000000-0000-0000-0000-000000000001",
            data=b"x" * (MAX_ARTIFACT_BYTES + 1),
        )


def test_max_artifact_matches_landed() -> None:
    assert MAX_ARTIFACT_BYTES == 15 * 1024 * 1024
