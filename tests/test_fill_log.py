"""Unit tests for form fill ledger → Landed Q&A outcomes."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from computer_use.browser.fill_log import (
    FILL_SOURCE,
    PASSWORD_REDACTED,
    chunk_outcomes,
    fill_step_detail,
    merge_fill_outcomes,
    to_outcome,
)
from computer_use.config.worker_config import WorkerConfig
from computer_use.worker import APPLIER_SERVICE, _post_fill_steps


def test_to_outcome_shape() -> None:
    o = to_outcome(label="Email", text="a@b.com", field_type="email", name="email")
    assert o["label"] == "Email"
    assert o["text"] == "a@b.com"
    assert o["source"] == FILL_SOURCE
    assert o["ok"] is True
    assert o["fieldType"] == "email"
    assert o["key"] == "email"


def test_merge_scrape_wins_over_typed() -> None:
    typed = [{"label": "Email", "text": "old@x.com", "name": "email"}]
    scraped = [{"label": "Email", "text": "new@x.com", "name": "email", "fieldType": "email"}]
    out = merge_fill_outcomes(scraped, typed)
    assert len(out) == 1
    assert out[0]["text"] == "new@x.com"
    assert out[0]["source"] == "apply-agents"


def test_merge_keeps_typed_when_not_in_scrape() -> None:
    typed = [{"label": "OTP", "text": "123456", "fieldType": "text"}]
    out = merge_fill_outcomes([], typed)
    assert out[0]["label"] == "OTP"
    assert out[0]["text"] == "123456"


def test_password_redacted() -> None:
    scraped = [
        {
            "label": "Password",
            "text": "secret",
            "fieldType": "password",
            "name": "password",
        }
    ]
    out = merge_fill_outcomes(scraped, None)
    assert out[0]["text"] == PASSWORD_REDACTED


def test_chunk_outcomes() -> None:
    rows = [to_outcome(label=f"Q{i}", text=str(i)) for i in range(5)]
    chunks = chunk_outcomes(rows, size=2)
    assert len(chunks) == 3
    assert len(chunks[0]) == 2
    assert len(chunks[-1]) == 1


def test_fill_step_detail() -> None:
    outcomes = [to_outcome(label="Phone", text="555")]
    detail = fill_step_detail(
        outcomes,
        page=1,
        applier={"service": APPLIER_SERVICE},
    )
    assert detail["page"] == 1
    assert detail["filled"] == ["Phone"]
    assert detail["outcomes"][0]["source"] == FILL_SOURCE
    assert detail["applier"]["service"] == APPLIER_SERVICE


def test_post_fill_steps_posts_landed_shape() -> None:
    client = MagicMock()
    cfg = WorkerConfig(landed_api_base="http://localhost:8180", worker_id="apply-agents")
    outcomes = [
        to_outcome(label="Email", text="a@b.com", field_type="email"),
        to_outcome(label="Phone", text="555"),
    ]
    n = _post_fill_steps(client, "app-1", outcomes, worker_cfg=cfg)
    assert n == 2
    client.step.assert_called_once()
    kwargs = client.step.call_args.kwargs
    assert kwargs["name"] == "fill"
    assert kwargs["status"] == "ok"
    detail: dict[str, Any] = kwargs["detail"]
    assert detail["outcomes"][0]["source"] == "apply-agents"
    assert detail["applier"]["service"] == "apply-agents"
    assert "Email" in detail["filled"]


def test_post_fill_steps_skips_empty() -> None:
    client = MagicMock()
    cfg = WorkerConfig(landed_api_base="http://localhost:8180")
    assert _post_fill_steps(client, "app-1", [], worker_cfg=cfg) == 0
    client.step.assert_not_called()
