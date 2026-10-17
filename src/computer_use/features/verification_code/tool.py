"""Agents SDK tools for check_verification_code and open_verification_link."""

from __future__ import annotations

from typing import Any

from agents import function_tool

from ..base import ApplyRunContext
from .service import (
    DEFAULT_POLL_S,
    DEFAULT_TIMEOUT_S,
    check_verification_code_message,
    check_verification_link_message,
)

TOOL_NAME = "check_verification_code"
LINK_TOOL_NAME = "open_verification_link"


def build_tools(ctx: ApplyRunContext) -> list[Any]:
    client = ctx.landed_client
    app_id = str(ctx.application_id or "").strip()
    if client is None or not app_id:
        return []

    since = ctx.verification_since
    default_company = ctx.company
    on_step = ctx.on_verification_step
    computer = ctx.browser_computer
    tools: list[Any] = []

    @function_tool(name_override=TOOL_NAME)
    def check_verification_code(company: str | None = None) -> str:
        """Fetch an email security / verification / OTP code from Gmail via Landed.

        Call when the form asks for a security code, verification code, one-time
        code, email code, OTP, or passcode that was just sent to the applicant's
        email. Do NOT invent a code or use profile values. Do NOT call for normal
        email address or password fields. Do NOT call for Workday-style "verify
        your account" gates with no code field — use open_verification_link.

        Returns CODE: <value> when found, NOT_FOUND: … if Gmail has nothing yet,
        or UNAVAILABLE: … if Gmail is not configured.
        """
        msg = check_verification_code_message(
            client,
            app_id,
            since=since,
            company=company,
            default_company=default_company,
            timeout_s=DEFAULT_TIMEOUT_S,
            poll_s=DEFAULT_POLL_S,
            on_step=on_step,
        )
        print(f"check_verification_code → {msg[:200]}", flush=True)
        return msg

    tools.append(check_verification_code)

    if computer is not None:

        @function_tool(name_override=LINK_TOOL_NAME)
        async def open_verification_link(company: str | None = None) -> str:
            """Open an emailed account / email verification link from Gmail via Landed.

            Call when the site says to verify your account or email (e.g. Workday
            "Verify your account before you sign in", "An email has been sent…
            Please verify") and there is NO on-page OTP / security-code field.
            Polls Gmail for the verify URL and navigates this browser to it.

            After OPENED, look for Sign In / continue and resume the application.
            Do NOT use check_verification_code for this gate.

            Returns OPENED: <url> when navigated, NOT_FOUND: / UNAVAILABLE: /
            FAILED: otherwise.
            """
            msg = check_verification_link_message(
                client,
                app_id,
                since=since,
                company=company,
                default_company=default_company,
                timeout_s=DEFAULT_TIMEOUT_S,
                poll_s=DEFAULT_POLL_S,
                on_step=on_step,
            )
            if not msg.startswith("LINK:"):
                print(f"open_verification_link → {msg[:240]}", flush=True)
                return msg
            # "LINK: https://… (from: …; subject: …)"
            rest = msg[len("LINK:") :].strip()
            url = rest.split(" (", 1)[0].strip()
            open_fn = getattr(computer, "open_url", None)
            if open_fn is None:
                out = "UNAVAILABLE: browser open_url helper missing"
                print(f"open_verification_link → {out}", flush=True)
                return out
            result = await open_fn(url)
            text = str(result or "FAILED: empty result")
            if text.startswith("OPENED:") and " (" in rest:
                extras = rest.split(" (", 1)[1]
                text = f"{text} ({extras}"
            print(f"open_verification_link → {text[:240]}", flush=True)
            return text

        tools.append(open_verification_link)

    return tools
