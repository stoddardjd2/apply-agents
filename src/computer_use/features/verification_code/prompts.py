"""Agent prompts for email verification / OTP."""

from __future__ import annotations

from ..base import ApplyRunContext

SYSTEM_INSTRUCTIONS = """
- EMAIL VERIFICATION / OTP: When a field asks for a security code, verification
  code, one-time code, email code, OTP, or passcode that was emailed to the
  applicant, call check_verification_code. Type the CODE: value exactly into
  the field. Do not invent a code or use PROFILE. Do not call this tool for
  normal email-address or password fields. If the tool returns NOT_FOUND or
  UNAVAILABLE and the field is required, stop and report blocked (Gmail /
  code missing).
""".strip()


def user_prompt_block(_ctx: ApplyRunContext) -> str:
    return (
        "EMAIL VERIFICATION CODES: check_verification_code is available. When the "
        "form asks for a security / verification / one-time / email / OTP code "
        "that was just emailed, call that tool (optionally pass company=). Type "
        "the CODE: value exactly. If NOT_FOUND or UNAVAILABLE and the field is "
        "required, stop and report blocked."
    )
