"""Employer-site account credentials store.

Persists email/password + verification status per career/ATS host so later
applies Sign In instead of Create Account.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_ACCOUNTS_PATH = Path("employer_accounts.json")
_MAX_ACCOUNTS = 200

VerificationStatus = str  # verified | needs_verification | unknown


def accounts_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.getenv("EMPLOYER_ACCOUNTS_PATH")
    return Path(env) if env else DEFAULT_ACCOUNTS_PATH


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def host_from_url(url: str | None) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    except Exception:
        return None
    host = (parsed.hostname or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def load_accounts(path: Path | None = None) -> dict[str, Any]:
    kb_path = accounts_path(path)
    if not kb_path.exists():
        return {"version": 1, "accounts": []}
    try:
        data = json.loads(kb_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "accounts": []}
    if not isinstance(data, dict):
        return {"version": 1, "accounts": []}
    accounts = data.get("accounts")
    if not isinstance(accounts, list):
        accounts = []
    return {"version": int(data.get("version") or 1), "accounts": accounts}


def save_accounts(data: dict[str, Any], path: Path | None = None) -> Path:
    kb_path = accounts_path(path)
    accounts = list(data.get("accounts") or [])
    if len(accounts) > _MAX_ACCOUNTS:
        accounts = accounts[-_MAX_ACCOUNTS:]
    payload = {"version": int(data.get("version") or 1), "accounts": accounts}
    kb_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return kb_path


def find_accounts_for_site(
    *,
    site_url: str | None = None,
    host: str | None = None,
    company: str | None = None,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Match saved accounts by host (preferred) or company name substring."""
    data = load_accounts(path)
    want_host = (host or host_from_url(site_url) or "").strip().lower()
    want_company = str(company or "").strip().lower()
    matches: list[dict[str, Any]] = []
    for row in data.get("accounts") or []:
        if not isinstance(row, dict):
            continue
        row_host = str(row.get("host") or "").strip().lower()
        row_company = str(row.get("company") or "").strip().lower()
        host_hit = bool(want_host and row_host and (want_host == row_host or want_host.endswith("." + row_host) or row_host.endswith("." + want_host)))
        company_hit = bool(
            want_company
            and row_company
            and (want_company in row_company or row_company in want_company)
        )
        if host_hit or company_hit:
            matches.append(row)

    # Newest first, then prefer exact host matches (stable sorts).
    matches.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    matches.sort(
        key=lambda r: (
            0
            if want_host and str(r.get("host") or "").strip().lower() == want_host
            else 1
        )
    )
    return matches


def upsert_account(
    *,
    email: str,
    password: str,
    site_url: str | None = None,
    host: str | None = None,
    company: str | None = None,
    verification_status: str = "unknown",
    notes: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Create or update an employer account keyed by host + email."""
    email_n = str(email or "").strip().lower()
    password_n = str(password or "").strip()
    if not email_n or not password_n:
        return {"ok": False, "message": "email and password are required"}

    use_host = (host or host_from_url(site_url) or "").strip().lower()
    if not use_host:
        return {"ok": False, "message": "site_url or host is required"}

    status = str(verification_status or "unknown").strip().lower()
    if status not in {"verified", "needs_verification", "unknown"}:
        status = "unknown"

    data = load_accounts(path)
    accounts: list[dict[str, Any]] = list(data.get("accounts") or [])
    now = _utc_now()
    existing: dict[str, Any] | None = None
    for row in accounts:
        if not isinstance(row, dict):
            continue
        if str(row.get("host") or "").strip().lower() != use_host:
            continue
        if str(row.get("email") or "").strip().lower() != email_n:
            continue
        existing = row
        break

    if existing is None:
        entry = {
            "id": f"acct_{uuid.uuid4().hex[:12]}",
            "host": use_host,
            "site_url": str(site_url or "").strip() or f"https://{use_host}/",
            "company": str(company or "").strip() or None,
            "email": email_n,
            "password": password_n,
            "verification_status": status,
            "notes": str(notes or "").strip() or None,
            "created_at": now,
            "updated_at": now,
            "last_used_at": now,
        }
        accounts.append(entry)
        data["accounts"] = accounts
        save_accounts(data, path)
        return {"ok": True, "message": "created", "account": entry}

    existing["password"] = password_n
    existing["site_url"] = str(site_url or existing.get("site_url") or "").strip() or f"https://{use_host}/"
    if company:
        existing["company"] = str(company).strip()
    existing["verification_status"] = status
    if notes is not None:
        existing["notes"] = str(notes).strip() or None
    existing["updated_at"] = now
    existing["last_used_at"] = now
    data["accounts"] = accounts
    save_accounts(data, path)
    return {"ok": True, "message": "updated", "account": existing}


def mark_verification(
    *,
    host: str | None = None,
    site_url: str | None = None,
    email: str | None = None,
    verification_status: str,
    path: Path | None = None,
) -> dict[str, Any]:
    """Update verification_status on a matching account."""
    status = str(verification_status or "").strip().lower()
    if status not in {"verified", "needs_verification", "unknown"}:
        return {"ok": False, "message": "verification_status must be verified|needs_verification|unknown"}
    use_host = (host or host_from_url(site_url) or "").strip().lower()
    email_n = str(email or "").strip().lower() or None
    if not use_host:
        return {"ok": False, "message": "site_url or host is required"}

    data = load_accounts(path)
    accounts = list(data.get("accounts") or [])
    updated = None
    now = _utc_now()
    for row in accounts:
        if not isinstance(row, dict):
            continue
        if str(row.get("host") or "").strip().lower() != use_host:
            continue
        if email_n and str(row.get("email") or "").strip().lower() != email_n:
            continue
        row["verification_status"] = status
        row["updated_at"] = now
        updated = row
        if email_n:
            break
    if updated is None:
        return {"ok": False, "message": "no matching account"}
    data["accounts"] = accounts
    save_accounts(data, path)
    return {"ok": True, "message": "updated", "account": updated}


def format_accounts_for_prompt(accounts: list[dict[str, Any]]) -> str:
    if not accounts:
        return ""
    lines = [
        "SAVED EMPLOYER ACCOUNTS for this site (reuse — Sign In, do NOT Create Account again):"
    ]
    for row in accounts[:5]:
        host = row.get("host") or "?"
        email = row.get("email") or "?"
        password = row.get("password") or "?"
        status = row.get("verification_status") or "unknown"
        company = row.get("company") or ""
        site = row.get("site_url") or ""
        lines.append(
            f"- host={host}"
            + (f" company={company}" if company else "")
            + (f" site={site}" if site else "")
            + f" email={email} password={password} verification={status}"
        )
        if status == "needs_verification":
            lines.append(
                "  → Account still needs email verification: call open_verification_link "
                "before Sign In if that tool is available, then mark verified via "
                "record_employer_account."
            )
        elif status == "verified":
            lines.append("  → Prefer Sign In with these credentials.")
    return "\n".join(lines)
