"""Agent prompts for NoneCap hCaptcha solving."""

from __future__ import annotations

from ..base import ApplyRunContext

TOOL_NAME = "solve_hcaptcha"

SYSTEM_INSTRUCTIONS = """
- HCAPTCHA: Never click hCaptcha checkboxes or image tiles. When you see an
  hCaptcha challenge (checkbox, invisible gate, or image grid) — especially
  after Submit/Send — call solve_hcaptcha once and wait for SOLVED. Then
  continue or re-click Submit if the form is still open. If it returns
  NO_SITEKEY or FAILED after one retry, stop and report blocked. Do not use
  this tool for Cloudflare Turnstile or Google reCAPTCHA (call wait instead).
""".strip()


def user_prompt_block(_ctx: ApplyRunContext) -> str:
    return (
        "HCAPTCHA: If an hCaptcha appears, call "
        f"{TOOL_NAME} (do not click the puzzle). "
        "Turnstile/reCAPTCHA: use wait so NopeCHA can clear them."
    )
