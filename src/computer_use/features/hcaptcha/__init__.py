"""hCaptcha solve feature (NoneCap API via agent tool)."""

from __future__ import annotations

from ..base import define_feature
from .prompts import SYSTEM_INSTRUCTIONS, user_prompt_block
from .tool import TOOL_NAME, build_tools

HcaptchaFeature = define_feature(
    "hcaptcha",
    tools=build_tools,
    system=SYSTEM_INSTRUCTIONS,
    user=user_prompt_block,
    enabled=lambda ctx: ctx.browser_computer is not None,
)

__all__ = [
    "TOOL_NAME",
    "HcaptchaFeature",
]
