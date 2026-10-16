"""Apply learnings feature."""

from __future__ import annotations

from ..base import define_feature
from .prompts import SYSTEM_INSTRUCTIONS, learnings_prompt_block, user_prompt_block
from .service import (
    hard_run_turn_threshold,
    learnings_path,
    load_learnings,
    record_hard_run,
    record_tip,
    recent_tips,
)
from .tool import TOOL_NAME, build_tools

LearningsFeature = define_feature(
    "learnings",
    tools=build_tools,
    system=SYSTEM_INSTRUCTIONS,
    user=user_prompt_block,
)

__all__ = [
    "TOOL_NAME",
    "LearningsFeature",
    "hard_run_turn_threshold",
    "learnings_path",
    "learnings_prompt_block",
    "load_learnings",
    "record_hard_run",
    "record_tip",
    "recent_tips",
]
