"""Account signup feature — prompt-only (no tool)."""

from __future__ import annotations

from ..base import define_feature
from .prompts import SYSTEM_INSTRUCTIONS, user_prompt_block

AccountSignupFeature = define_feature(
    "account_signup",
    system=SYSTEM_INSTRUCTIONS,
    user=user_prompt_block,
)

__all__ = ["AccountSignupFeature"]
