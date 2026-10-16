"""Tests for AI turn log formatting."""

from __future__ import annotations

from computer_use.browser.agent_log import (
    ai_turn_logs_enabled,
    format_model_output_item,
    make_apply_run_hooks,
    parse_turn,
    summarize_turn,
)


def test_formats_reasoning_summary() -> None:
    item = {
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "I will click Submit next."}],
    }
    lines = format_model_output_item(item)
    assert any("think" in line and "Submit" in line for line in lines)


def test_formats_computer_click() -> None:
    item = {
        "type": "computer_call",
        "action": {"type": "click", "x": 10, "y": 20, "button": "left"},
    }
    lines = format_model_output_item(item)
    assert any("did" in line and "click" in line for line in lines)
    assert "x=10" not in "".join(lines)


def test_formats_function_call() -> None:
    item = {
        "type": "function_call",
        "name": "resolve_form_question",
        "arguments": '{"question":"Clearance?"}',
    }
    lines = format_model_output_item(item)
    assert any("resolve_form_question" in line for line in lines)
    assert "Clearance" not in "".join(lines)


def test_summarize_turn_shows_think_and_actions() -> None:
    output = [
        {
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "Fill the email field then continue."}],
        },
        {"type": "computer_call", "action": {"type": "click", "x": 1, "y": 2}},
        {"type": "computer_call", "action": {"type": "click", "x": 3, "y": 4}},
        {"type": "computer_call", "action": {"type": "type", "text": "a@b.com"}},
        {
            "type": "function_call",
            "name": "resolve_form_question",
            "arguments": '{"question":"x"}',
        },
    ]
    lines = summarize_turn(output)
    blob = "\n".join(lines)
    assert "think" in blob
    assert "Fill the email" in blob
    assert "click×2" in blob
    assert "type" in blob
    assert "resolve_form_question" in blob
    assert "a@b.com" not in blob


def test_parse_turn_extracts_think() -> None:
    parsed = parse_turn(
        [
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "Open the apply tab."}],
            },
            {"type": "computer_call", "action": {"type": "click", "x": 1, "y": 2}},
        ]
    )
    assert "Open the apply tab" in parsed["think"]
    assert "click" in parsed["did"]


def test_missing_reasoning_still_logs_think_placeholder() -> None:
    lines = summarize_turn(
        [{"type": "computer_call", "action": {"type": "wait"}}]
    )
    blob = "\n".join(lines)
    assert "think" in blob
    assert "no reasoning" in blob.lower()
    assert "wait" in blob


def test_ai_turn_logs_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AI_TURN_LOGS_ENABLED", raising=False)
    assert ai_turn_logs_enabled() is True
    assert make_apply_run_hooks() is not None


def test_ai_turn_logs_can_disable(monkeypatch) -> None:
    monkeypatch.setenv("AI_TURN_LOGS_ENABLED", "0")
    assert ai_turn_logs_enabled() is False
    assert make_apply_run_hooks() is None
