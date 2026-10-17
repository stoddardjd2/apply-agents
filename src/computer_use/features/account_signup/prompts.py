"""Agent prompts for employer-site account signup."""

from __future__ import annotations

from ..base import ApplyRunContext
from .service import find_accounts_for_site, format_accounts_for_prompt

SYSTEM_INSTRUCTIONS = """
- Account creation: only on the employer's own career/ATS site, and only when
  ACCOUNT SIGNUP rules in the task allow it. Prefer Google SSO over
  email/password. Never invent a password.
- When SAVed EMPLOYER ACCOUNTS are listed for this site, Sign In with those
  credentials — do not Create Account again. If verification=needs_verification,
  open the emailed verify link first (open_verification_link when available).
- After Create Account (or after email verify succeeds), call
  record_employer_account so credentials can be reused on later visits.
""".strip()


def user_prompt_block(ctx: ApplyRunContext) -> str:
    cfg = ctx.account_signup or {}
    saved = find_accounts_for_site(
        site_url=ctx.job_url,
        company=ctx.company,
    )
    saved_block = format_accounts_for_prompt(saved)

    if not cfg.get("enabled"):
        parts = [
            "ACCOUNT SIGNUP: disabled. Do not create new employer accounts. "
            "Sign in only if already logged in or via Google SSO when available."
        ]
        if saved_block:
            parts.append(saved_block)
        return "\n".join(parts)

    email = str(cfg.get("email") or "").strip()
    password = str(cfg.get("password") or "").strip()
    prefer_sso = bool(cfg.get("prefer_google_sso", True))
    allow_create = bool(cfg.get("create_on_non_major_employers", True))
    majors = [
        str(m).strip() for m in (cfg.get("major_employers") or []) if str(m).strip()
    ]
    majors_text = ", ".join(majors) if majors else "(none listed)"

    if not allow_create:
        parts = [
            "ACCOUNT SIGNUP: do not create accounts. Prefer Google SSO if offered; "
            "otherwise stop and report that sign-in is required."
        ]
        if saved_block:
            parts.append(saved_block)
        return "\n".join(parts)

    if not email or not password:
        parts = [
            "ACCOUNT SIGNUP: create-on-non-major is enabled, but email/password are "
            "missing. Set account_signup.email / account_signup.password in "
            "apply.config.json, or APPLY_ACCOUNT_EMAIL / APPLY_ACCOUNT_PASSWORD in "
            ".env. Prefer Google SSO if offered; otherwise stop and report that "
            "signup credentials are missing.\n"
            f"Treat these as major employers (do not create accounts): {majors_text}."
        ]
        if saved_block:
            parts.append(saved_block)
        return "\n".join(parts)

    sso = (
        "Prefer Continue with Google / Google SSO whenever it is offered. "
        if prefer_sso
        else ""
    )
    never_hosts = [
        str(h).strip().lower()
        for h in (cfg.get("never_signup_on") or [])
        if str(h).strip()
    ] or [
        "glassdoor.com",
        "indeed.com",
        "linkedin.com",
        "ziprecruiter.com",
    ]
    never_text = ", ".join(never_hosts)

    parts = [
        "ACCOUNT SIGNUP RULES:\n"
        f"- NEVER create accounts on these job boards/hosts: {never_text}. "
        "Do not fill Join/Sign up on those sites. Click Apply / continue until you "
        "land on the employer's own career/ATS domain, then signup only there.\n"
        f"- {sso}"
        "Judge major vs non-major by the HIRING COMPANY on the employer site after "
        "redirect — not by the job board you started from.\n"
        "Once on the employer's site, if it requires Create Account / Sign Up to "
        "apply and the employer is NOT a major company, you MUST create an account "
        "using these credentials (do not skip signup and stop):\n"
        f"  email: {email}\n"
        f"  password: {password}\n"
        f"- Do NOT create accounts for major employers: {majors_text}. "
        "For those, use Google SSO if available, or stop and report that a major-"
        "company account would be needed.\n"
        "- If Create Account fails (error, email already used, verify email), try "
        "Sign In with the same email/password. If that also fails, stop and report "
        "the exact on-screen error.\n"
        "- After Create Account (or successful Sign In on a new host), call "
        "record_employer_account with site_url=the employer career URL, "
        "verification_status=needs_verification if the site requires emailed "
        "verify, or verified if Sign In works. After open_verification_link "
        "succeeds, call record_employer_account again with verification_status="
        "verified.\n"
        "- Report whether an employer account was created (never a job-board account)."
    ]
    if saved_block:
        parts.append(saved_block)
        parts.append(
            "If a SAVED EMPLOYER ACCOUNT matches this career host, Sign In with "
            "those credentials instead of Create Account."
        )
    return "\n".join(parts)
