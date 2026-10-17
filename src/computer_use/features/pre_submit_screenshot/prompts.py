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
  again before submitting. The capture scrolls the page to the top — after
  CAPTURED, scroll back down until the Submit/Apply button is visible, then
  click it. Do not reuse pre-screenshot click coordinates from the bottom.
""".strip()


def user_prompt_block(_ctx: ApplyRunContext) -> str:
    return (
        "PRE-SUBMIT SCREENSHOT: Before the final Submit/Apply click, call "
        f"{TOOL_NAME} once so the filled form is saved as evidence. "
        "After CAPTURED (or ALREADY_CAPTURED), scroll down to bring Submit/Apply "
        "back into view, then click it (the screenshot jumps the viewport to the "
        "top). Dry-run: stop at the review step instead of submitting. "
        "Do not call the screenshot tool earlier."
    )
