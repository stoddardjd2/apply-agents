"""Account signup feature — prompts + employer credential persistence tool."""

from __future__ import annotations

from ..base import define_feature
from .prompts import SYSTEM_INSTRUCTIONS, user_prompt_block
from .tool import TOOL_NAME, build_tools

AccountSignupFeature = define_feature(
    "account_signup",
    tools=build_tools,
    system=SYSTEM_INSTRUCTIONS,
    user=user_prompt_block,
)

__all__ = ["AccountSignupFeature", "TOOL_NAME", "build_tools"]
