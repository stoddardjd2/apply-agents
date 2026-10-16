"""Agent prompts for pre-submit full-page screenshot evidence."""

from __future__ import annotations

from ..base import ApplyRunContext

TOOL_NAME = "capture_pre_submit_screenshot"

SYSTEM_INSTRUCTIONS = """
- PRE-SUBMIT SCREENSHOT: When every REQUIRED field/question on the current
  apply form is filled and you are about to click the final Submit/Apply
  (not Continue/Next), call capture_pre_submit_screenshot once first. Do not
  call it while required fields are still empty, on mid-flow Continue/Next,
  or after Submit. If it returns INCOMPLETE, finish those fields and call
  again before submitting.
""".strip()


def user_prompt_block(_ctx: ApplyRunContext) -> str:
    return (
        "PRE-SUBMIT SCREENSHOT: Before the final Submit/Apply click, call "
        f"{TOOL_NAME} once so the filled form is saved as evidence. "
        "Only after CAPTURED (or ALREADY_CAPTURED) should you click Submit/Apply "
        "(or stop at the review step in dry-run). Do not call it earlier."
    )
