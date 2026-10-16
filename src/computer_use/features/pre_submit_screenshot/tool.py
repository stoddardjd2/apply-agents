"""Agents SDK tool for capture_pre_submit_screenshot."""

from __future__ import annotations

from typing import Any

from agents import function_tool

from ..base import ApplyRunContext

TOOL_NAME = "capture_pre_submit_screenshot"


def build_tools(ctx: ApplyRunContext) -> list[Any]:
    computer = ctx.browser_computer
    if computer is None:
        return []

    @function_tool(name_override=TOOL_NAME)
    async def capture_pre_submit_screenshot() -> str:
        """Capture a full-page screenshot of the completed application form.

        Call ONCE when every REQUIRED field/question is filled and you are about
        to click the final Submit/Apply button (not Continue/Next). Do not call
        earlier while required fields are empty, and do not call after Submit.

        Returns CAPTURED: … on success, INCOMPLETE: … if required fields remain,
        ALREADY_CAPTURED if already taken this run, or FAILED/UNAVAILABLE.
        """
        capture = getattr(computer, "capture_pre_submit_evidence", None)
        if capture is None:
            return "UNAVAILABLE: browser screenshot helper missing"
        result = await capture()
        return str(result or "FAILED: empty result")

    return [capture_pre_submit_screenshot]
