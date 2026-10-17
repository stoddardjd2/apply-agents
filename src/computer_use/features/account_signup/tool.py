"""Agents SDK tool to persist employer-site login credentials."""

from __future__ import annotations

from typing import Any

from agents import function_tool

from ..base import ApplyRunContext
from .service import accounts_path, upsert_account

TOOL_NAME = "record_employer_account"


def build_tools(ctx: ApplyRunContext) -> list[Any]:
    default_company = ctx.company
    default_url = ctx.job_url
    cfg = ctx.account_signup or {}
    default_email = str(cfg.get("email") or "").strip()
    default_password = str(cfg.get("password") or "").strip()
    path = accounts_path()

    @function_tool(name_override=TOOL_NAME)
    def record_employer_account(
        email: str | None = None,
        password: str | None = None,
        site_url: str | None = None,
        company: str | None = None,
        verification_status: str = "unknown",
        notes: str | None = None,
    ) -> str:
        """Save or update employer-site login credentials for reuse on later applies.

        Call AFTER you successfully Create Account (or confirm Sign In works) on an
        employer career/ATS site. Pass the email/password you used, the employer
        site URL (career host, not Glassdoor/Indeed), and verification_status:
        - needs_verification — site requires emailed verify link/code before Sign In
        - verified — email verified or Sign In works without further verify
        - unknown — created but verify status unclear

        Also call again after open_verification_link succeeds to set
        verification_status=verified.

        Returns SAVED: … or UPDATED: … or FAILED: …
        """
        use_email = (email or default_email or "").strip()
        use_password = (password or default_password or "").strip()
        use_url = (site_url or default_url or "").strip()
        use_company = (company or default_company or "").strip() or None
        result = upsert_account(
            email=use_email,
            password=use_password,
            site_url=use_url,
            company=use_company,
            verification_status=verification_status,
            notes=notes,
            path=path,
        )
        if not result.get("ok"):
            return f"FAILED: {result.get('message') or 'could not save account'}"
        acct = result.get("account") or {}
        action = "SAVED" if result.get("message") == "created" else "UPDATED"
        return (
            f"{action}: host={acct.get('host')} email={acct.get('email')} "
            f"verification={acct.get('verification_status')}"
        )

    return [record_employer_account]
