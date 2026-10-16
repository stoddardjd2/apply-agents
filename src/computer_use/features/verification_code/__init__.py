"""Email verification / OTP feature."""

from __future__ import annotations

from ..base import ApplyRunContext, define_feature
from .prompts import SYSTEM_INSTRUCTIONS, user_prompt_block
from .service import (
    DEFAULT_POLL_S,
    DEFAULT_TIMEOUT_S,
    check_verification_code_message,
    format_code_hit,
    utc_now_iso,
    wait_for_verification_code,
)
from .tool import TOOL_NAME, build_tools


def _verification_enabled(ctx: ApplyRunContext) -> bool:
    return ctx.landed_client is not None and bool(str(ctx.application_id or "").strip())


VerificationCodeFeature = define_feature(
    "verification_code",
    enabled=_verification_enabled,
    tools=build_tools,
    system=SYSTEM_INSTRUCTIONS,
    user=user_prompt_block,
)

__all__ = [
    "DEFAULT_POLL_S",
    "DEFAULT_TIMEOUT_S",
    "TOOL_NAME",
    "VerificationCodeFeature",
    "check_verification_code_message",
    "format_code_hit",
    "utc_now_iso",
    "wait_for_verification_code",
]
