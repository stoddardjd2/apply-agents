"""Agent prompts for email verification / OTP and click-to-verify links."""

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
- ACCOUNT / EMAIL VERIFY LINK: Only when the live page shows a verify-account /
  email-sent gate (e.g. Workday "Verify your account before you sign in") and
  there is NO code field — never at session start from saved state alone. If a
  SAVED EMPLOYER ACCOUNT is verification=needs_verification, click Resend /
  Send again on that page first (when present), then call open_verification_link
  so Gmail sees a fresh message. Otherwise call open_verification_link after the
  site has just sent the email. After OPENED, Sign In or continue, then call
  record_employer_account with verification_status=verified when available. If
  NOT_FOUND / UNAVAILABLE / FAILED and verification is required, stop and report
  blocked.
""".strip()


def user_prompt_block(ctx: ApplyRunContext) -> str:
    parts = [
        "EMAIL VERIFICATION CODES: check_verification_code is available. When the "
        "form asks for a security / verification / one-time / email / OTP code "
        "that was just emailed, call that tool (optionally pass company=). Type "
        "the CODE: value exactly. If NOT_FOUND or UNAVAILABLE and the field is "
        "required, stop and report blocked."
    ]
    if ctx.browser_computer is not None:
        parts.append(
            "ACCOUNT EMAIL VERIFY LINKS: open_verification_link is available. Use "
            "it only when the live page shows a verify-link gate (no OTP field) — "
            "not at session start. If saved verification=needs_verification, click "
            "Resend / Send again first when available, then call "
            "open_verification_link. After OPENED, Sign In and continue. If "
            "NOT_FOUND / UNAVAILABLE / FAILED and verification is required, stop "
            "and report blocked."
        )
    return " ".join(parts)
