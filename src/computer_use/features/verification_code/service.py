"""Verification code / link service.

Polls Landed's Gmail API for security / OTP codes or click-to-verify URLs during
an apply, formats hits for the agent tools, and reports timeline steps.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from computer_use.landed.client import LandedApiError, LandedClient

DEFAULT_TIMEOUT_S = 90.0
DEFAULT_POLL_S = 4.0

# (status, detail) — harness wires Landed timeline step name + application id.
StepCallback = Callable[[str, dict[str, Any]], None]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_code_hit(hit: dict[str, Any]) -> str:
    code = str(hit.get("code") or "").strip()
    from_addr = str(hit.get("from") or "").strip()
    subject = str(hit.get("subject") or "").strip()
    parts = [f"CODE: {code}"]
    extras: list[str] = []
    if from_addr:
        extras.append(f"from: {from_addr}")
    if subject:
        extras.append(f"subject: {subject}")
    if extras:
        parts.append("(" + "; ".join(extras) + ")")
    return " ".join(parts)


def format_link_hit(hit: dict[str, Any]) -> str:
    url = str(hit.get("url") or "").strip()
    from_addr = str(hit.get("from") or "").strip()
    subject = str(hit.get("subject") or "").strip()
    parts = [f"LINK: {url}"]
    extras: list[str] = []
    if from_addr:
        extras.append(f"from: {from_addr}")
    if subject:
        extras.append(f"subject: {subject}")
    if extras:
        parts.append("(" + "; ".join(extras) + ")")
    return " ".join(parts)


def soft_company_token(company: str | None) -> str | None:
    """Short Gmail-friendly token from a legal company name.

    Prefer a leading acronym (BCBST); skip trailing parenthetical aliases like
    ``(AWS)`` so ranking uses ``Amazon`` (what mail actually says).
    """
    raw = str(company or "").strip()
    if not raw:
        return None
    head = raw.split(",", 1)[0].strip().replace('"', "")
    if not head:
        return None
    words = head.split()
    skip = {"inc", "llc", "corp", "ltd", "company", "the", "and", "of"}
    for w in words:
        if w.startswith("(") and w.endswith(")"):
            continue
        clean = "".join(ch for ch in w if ch.isalnum())
        if len(clean) >= 2 and clean.isupper() and any(ch.isalpha() for ch in clean):
            return clean
    for w in words:
        if w.startswith("(") and w.endswith(")"):
            continue
        clean = "".join(ch for ch in w if ch.isalnum())
        if len(clean) >= 4 and clean.lower() not in skip:
            return clean
    return None


def wait_for_verification_code(
    client: LandedClient,
    application_id: str,
    *,
    since: str | None = None,
    company: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    poll_s: float = DEFAULT_POLL_S,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any] | None:
    """Poll until a code is found, timeout, or Gmail is unavailable (raises)."""
    deadline = monotonic() + max(5.0, float(timeout_s))
    last_error: LandedApiError | None = None
    while monotonic() < deadline:
        try:
            hit = client.verification_code(
                application_id,
                since=since,
                company=company,
            )
            if hit and str(hit.get("code") or "").strip():
                return hit
        except LandedApiError as exc:
            last_error = exc
            # 409 / 404 → stop; agent must report blocked.
            if exc.status in {404, 409}:
                raise
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(float(poll_s), remaining))
    if last_error is not None and last_error.status not in {None, 204}:
        raise last_error
    return None


def wait_for_verification_link(
    client: LandedClient,
    application_id: str,
    *,
    since: str | None = None,
    company: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    poll_s: float = DEFAULT_POLL_S,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any] | None:
    """Poll until a verify URL is found, timeout, or Gmail is unavailable (raises)."""
    deadline = monotonic() + max(5.0, float(timeout_s))
    last_error: LandedApiError | None = None
    while monotonic() < deadline:
        try:
            hit = client.verification_link(
                application_id,
                since=since,
                company=company,
            )
            if hit and str(hit.get("url") or "").strip():
                return hit
        except LandedApiError as exc:
            last_error = exc
            if exc.status in {404, 409}:
                raise
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(float(poll_s), remaining))
    if last_error is not None and last_error.status not in {None, 204}:
        raise last_error
    return None


def check_verification_code_message(
    client: LandedClient | None,
    application_id: str | None,
    *,
    since: str | None = None,
    company: str | None = None,
    default_company: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    poll_s: float = DEFAULT_POLL_S,
    on_step: StepCallback | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] | None = None,
) -> str:
    """Pure helper used by the tool (and tests). Returns CODE: / NOT_FOUND: / UNAVAILABLE:."""
    if client is None or not str(application_id or "").strip():
        return (
            "UNAVAILABLE: no Landed application id — verification codes are only "
            "available on the worker claim path with Gmail connected."
        )
    use_company = soft_company_token(company or default_company)
    clock = monotonic or time.monotonic
    try:
        hit = wait_for_verification_code(
            client,
            str(application_id).strip(),
            since=since,
            company=use_company,
            timeout_s=timeout_s,
            poll_s=poll_s,
            sleep=sleep,
            monotonic=clock,
        )
        # Soft token still missed — retry once without company.
        if not hit and use_company:
            hit = wait_for_verification_code(
                client,
                str(application_id).strip(),
                since=since,
                company=None,
                timeout_s=min(30.0, float(timeout_s)),
                poll_s=poll_s,
                sleep=sleep,
                monotonic=clock,
            )
    except LandedApiError as exc:
        if on_step is not None:
            try:
                on_step(
                    "failed",
                    {
                        "kind": "code",
                        "error": str(exc),
                        "status": exc.status,
                        "company": use_company,
                    },
                )
            except Exception:
                pass
        if exc.status == 409:
            return (
                "UNAVAILABLE: Gmail is not connected or not enabled for this user "
                f"({exc}). Connect Gmail in Landed integrations, or paste the code."
            )
        if exc.status == 404:
            return f"UNAVAILABLE: application not found ({exc})."
        return f"NOT_FOUND: Gmail lookup failed ({exc})."

    if not hit:
        if on_step is not None:
            try:
                on_step(
                    "failed",
                    {
                        "kind": "code",
                        "error": "No security code in Gmail yet",
                        "company": use_company,
                        "since": since,
                    },
                )
            except Exception:
                pass
        return (
            "NOT_FOUND: no matching security / verification code email yet "
            "(timed out). Wait a moment and call again, or stop if the field is "
            "required and the email never arrives."
        )

    if on_step is not None:
        try:
            on_step(
                "ok",
                {
                    "kind": "code",
                    "code": hit.get("code"),
                    "from": hit.get("from"),
                    "subject": hit.get("subject"),
                    "messageId": hit.get("messageId"),
                    "company": use_company,
                },
            )
        except Exception:
            pass
    return format_code_hit(hit)


def check_verification_link_message(
    client: LandedClient | None,
    application_id: str | None,
    *,
    since: str | None = None,
    company: str | None = None,
    default_company: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    poll_s: float = DEFAULT_POLL_S,
    on_step: StepCallback | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] | None = None,
) -> str:
    """Poll for a verify URL. Returns LINK: / NOT_FOUND: / UNAVAILABLE: (no browser open)."""
    if client is None or not str(application_id or "").strip():
        return (
            "UNAVAILABLE: no Landed application id — verification links are only "
            "available on the worker claim path with Gmail connected."
        )
    use_company = soft_company_token(company or default_company)
    clock = monotonic or time.monotonic
    try:
        # Landed ranks by company when present; omit soft token from the query path
        # by still sending it for preference only — and retry bare if needed.
        hit = wait_for_verification_link(
            client,
            str(application_id).strip(),
            since=since,
            company=use_company,
            timeout_s=timeout_s,
            poll_s=poll_s,
            sleep=sleep,
            monotonic=clock,
        )
        if not hit and use_company:
            hit = wait_for_verification_link(
                client,
                str(application_id).strip(),
                since=since,
                company=None,
                timeout_s=min(30.0, float(timeout_s)),
                poll_s=poll_s,
                sleep=sleep,
                monotonic=clock,
            )
    except LandedApiError as exc:
        if on_step is not None:
            try:
                on_step(
                    "failed",
                    {
                        "kind": "link",
                        "error": str(exc),
                        "status": exc.status,
                        "company": use_company,
                    },
                )
            except Exception:
                pass
        if exc.status == 409:
            return (
                "UNAVAILABLE: Gmail is not connected or not enabled for this user "
                f"({exc}). Connect Gmail in Landed integrations."
            )
        if exc.status == 404:
            return f"UNAVAILABLE: application not found ({exc})."
        return f"NOT_FOUND: Gmail lookup failed ({exc})."

    if not hit:
        if on_step is not None:
            try:
                on_step(
                    "failed",
                    {
                        "kind": "link",
                        "error": "No verification link in Gmail yet",
                        "company": use_company,
                        "since": since,
                    },
                )
            except Exception:
                pass
        return (
            "NOT_FOUND: no matching account / email verification link yet "
            "(timed out). Wait a moment and call again, or stop if verification "
            "is required and the email never arrives."
        )

    if on_step is not None:
        try:
            on_step(
                "ok",
                {
                    "kind": "link",
                    "url": hit.get("url"),
                    "from": hit.get("from"),
                    "subject": hit.get("subject"),
                    "messageId": hit.get("messageId"),
                    "company": use_company,
                },
            )
        except Exception:
            pass
    return format_link_hit(hit)
