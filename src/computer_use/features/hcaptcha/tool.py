"""Agents SDK tool for solve_hcaptcha (NoneCap)."""

from __future__ import annotations

from typing import Any

from agents import function_tool

from ..base import ApplyRunContext

TOOL_NAME = "solve_hcaptcha"


def build_tools(ctx: ApplyRunContext) -> list[Any]:
    computer = ctx.browser_computer
    if computer is None:
        return []

    @function_tool(name_override=TOOL_NAME)
    async def solve_hcaptcha() -> str:
        """Solve a visible hCaptcha via NoneCap and inject the token.

        Call when you see an hCaptcha checkbox or image-grid challenge (including
        after Submit/Send). Do NOT click the captcha tiles yourself. Do not call
        for Cloudflare Turnstile or reCAPTCHA (those use NopeCHA + wait).

        Returns SOLVED / ALREADY_SOLVED / NO_SITEKEY / NOT_HCAPTCHA / DISABLED / FAILED.
        """
        solve = getattr(computer, "solve_hcaptcha_now", None)
        if solve is None:
            return "UNAVAILABLE: browser hCaptcha helper missing"
        result = await solve()
        return str(result or "FAILED: empty result")

    return [solve_hcaptcha]
