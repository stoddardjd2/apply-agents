"""Agents SDK tool for check_verification_code."""

from __future__ import annotations

from typing import Any

from agents import function_tool

from ..base import ApplyRunContext
from .service import (
    DEFAULT_POLL_S,
    DEFAULT_TIMEOUT_S,
    check_verification_code_message,
)

TOOL_NAME = "check_verification_code"


def build_tools(ctx: ApplyRunContext) -> list[Any]:
    client = ctx.landed_client
    app_id = str(ctx.application_id or "").strip()
    if client is None or not app_id:
        return []

    since = ctx.verification_since
    default_company = ctx.company
    on_step = ctx.on_verification_step

    @function_tool(name_override=TOOL_NAME)
    def check_verification_code(company: str | None = None) -> str:
        """Fetch an email security / verification / OTP code from Gmail via Landed.

        Call when the form asks for a security code, verification code, one-time
        code, email code, OTP, or passcode that was just sent to the applicant's
        email. Do NOT invent a code or use profile values. Do NOT call for normal
        email address or password fields.

        Returns CODE: <value> when found, NOT_FOUND: … if Gmail has nothing yet,
        or UNAVAILABLE: … if Gmail is not configured.
        """
        return check_verification_code_message(
            client,
            app_id,
            since=since,
            company=company,
            default_company=default_company,
            timeout_s=DEFAULT_TIMEOUT_S,
            poll_s=DEFAULT_POLL_S,
            on_step=on_step,
        )

    return [check_verification_code]
