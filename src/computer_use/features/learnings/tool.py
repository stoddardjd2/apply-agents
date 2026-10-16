"""Agents SDK tool for record_apply_learning."""

from __future__ import annotations

from typing import Any

from agents import function_tool

from ..base import ApplyRunContext
from .service import learnings_path, record_tip

TOOL_NAME = "record_apply_learning"


def build_tools(ctx: ApplyRunContext) -> list[Any]:
    job_url = ctx.job_url
    company = ctx.company
    kb_path = learnings_path()

    @function_tool(name_override=TOOL_NAME)
    def record_apply_learning(
        summary: str,
        detail: str | None = None,
        board: str | None = None,
    ) -> str:
        """Record a reusable apply tip for future runs.

        Call when you discover something that wasted turns or will help next time
        on this board/ATS (resume picker quirks, tab switches, captcha timing,
        post-submit redirects, hidden required fields, etc.). Keep summary short.
        """
        result = record_tip(
            summary=summary,
            detail=detail,
            job_url=job_url,
            company=company,
            board=board,
            path=kb_path,
        )
        if not result.get("ok"):
            return "LEARNING_SKIPPED: empty summary"
        return f"LEARNING_RECORDED: {result['entry']['summary']}"

    return [record_apply_learning]
