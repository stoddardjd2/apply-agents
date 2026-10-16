"""Agent prompts for apply learnings."""

from __future__ import annotations

from pathlib import Path

from ..base import ApplyRunContext
from .service import recent_tips

SYSTEM_INSTRUCTIONS = """
- LEARNINGS: When you discover a reusable board/ATS gotcha that wasted turns
  (resume picker, tab switch, captcha timing, post-submit redirect, hidden
  required field), call record_apply_learning with a short tip so future runs
  benefit. Do not call it for routine field fills.
""".strip()


def learnings_prompt_block(*, limit: int = 12, path: Path | None = None) -> str:
    tips = recent_tips(limit=limit, path=path)
    if not tips:
        return (
            "APPLY LEARNINGS: (none yet). If you discover a reusable board/ATS gotcha "
            "(e.g. tab handling, resume picker, post-submit redirect), call "
            "record_apply_learning with a short tip."
        )
    lines = [
        "APPLY LEARNINGS (reusable tips from prior runs — follow when relevant):",
    ]
    for tip in tips:
        board = tip.get("board") or tip.get("company") or ""
        prefix = f"[{board}] " if board else ""
        lines.append(f"- {prefix}{tip.get('summary')}")
        detail = tip.get("detail")
        if detail:
            lines.append(f"  detail: {detail}")
    lines.append(
        "If you learn a new reusable gotcha, call record_apply_learning "
        "(short summary; optional board/ATS name)."
    )
    return "\n".join(lines)


def user_prompt_block(_ctx: ApplyRunContext, *, limit: int = 12) -> str:
    return learnings_prompt_block(limit=limit)
