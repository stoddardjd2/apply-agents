"""Load job-apply config (URL + resume PDF + applicant profile)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .salary import enrich_profile_salary


DEFAULT_CONFIG_PATH = Path(os.getenv("APPLY_CONFIG", "apply.config.json"))


def normalize_always_fill_fields(raw: Any) -> list[str]:
    """Normalize always_fill_fields to exact profile keys (deduped, order kept)."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


@dataclass(frozen=True)
class ApplyConfig:
    job_url: str
    resume_path: Path
    submit: bool = False
    notes: str | None = None
    profile: dict[str, Any] = field(default_factory=dict)
    account_signup: dict[str, Any] = field(default_factory=dict)
    always_fill_fields: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.job_url or not self.job_url.startswith(("http://", "https://")):
            raise ValueError(
                "apply.config.json must set a real job_url (https://...)."
            )
        if "example.com/jobs/your-listing" in self.job_url:
            raise ValueError(
                f"Replace the placeholder job_url in your config: {self.job_url}"
            )
        if not self.resume_path.is_file():
            raise FileNotFoundError(
                f"Resume PDF not found: {self.resume_path.resolve()}\n"
                "Put your PDF there or update resume_path in apply.config.json."
            )
        if self.resume_path.suffix.lower() != ".pdf":
            raise ValueError(f"resume_path must be a PDF file, got: {self.resume_path}")


def _load_raw(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Missing {config_path}. Create it with job_url and resume_path."
        )
    return json.loads(config_path.read_text(encoding="utf-8"))


def _profile_and_signup(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = dict(raw.get("profile") or {})
    # Underscore keys are local docs/comments only (not sent to the agent).
    profile = {k: v for k, v in profile.items() if not str(k).startswith("_")}
    if os.getenv("APPLICANT_EMAIL"):
        profile["email"] = os.environ["APPLICANT_EMAIL"]
    if os.getenv("APPLICANT_PHONE"):
        profile["phone"] = os.environ["APPLICANT_PHONE"]

    account_signup = dict(raw.get("account_signup") or {})
    signup_password = os.getenv("APPLY_ACCOUNT_PASSWORD", "").strip()
    if signup_password:
        account_signup["password"] = signup_password
    if os.getenv("APPLY_ACCOUNT_EMAIL", "").strip():
        account_signup["email"] = os.environ["APPLY_ACCOUNT_EMAIL"].strip()
    return profile, account_signup


def _resolve_submit(raw: dict[str, Any], submit_override: bool | None = None) -> bool:
    if submit_override is not None:
        return submit_override
    submit_raw = os.getenv("SUBMIT_APPLICATION")
    if submit_raw is None:
        return bool(raw.get("submit", False))
    return submit_raw in {"1", "true", "TRUE", "yes", "YES"}


def load_apply_config(path: Path | None = None) -> ApplyConfig:
    """Load config for a manual/single-URL apply run."""
    config_path = path or DEFAULT_CONFIG_PATH
    raw = _load_raw(config_path)

    resume = Path(raw.get("resume_path") or "")
    if not resume.is_absolute():
        resume = (config_path.parent / resume).resolve()

    job_url = os.getenv("JOB_URL") or raw.get("job_url") or ""
    resume_env = os.getenv("RESUME_PATH")
    if resume_env:
        resume = Path(resume_env).expanduser().resolve()

    profile, account_signup = _profile_and_signup(raw)
    # Manual apply has no claim job range; config number still wins via enrich.
    profile = enrich_profile_salary(profile)
    cfg = ApplyConfig(
        job_url=str(job_url).strip(),
        resume_path=resume,
        submit=_resolve_submit(raw),
        notes=raw.get("notes"),
        profile=profile,
        account_signup=account_signup,
        always_fill_fields=normalize_always_fill_fields(raw.get("always_fill_fields")),
    )
    cfg.validate()
    return cfg


def load_apply_config_for_job(
    *,
    job_url: str,
    resume_path: Path,
    cover_letter: str | None = None,
    submit: bool | None = None,
    path: Path | None = None,
    notes: str | None = None,
    job: dict[str, Any] | None = None,
    fields: dict[str, Any] | None = None,
) -> ApplyConfig:
    """Base apply.config.json profile/signup + per-job URL/resume/cover from Landed."""
    config_path = path or DEFAULT_CONFIG_PATH
    raw = _load_raw(config_path)
    profile, account_signup = _profile_and_signup(raw)
    if cover_letter is not None and str(cover_letter).strip():
        profile = dict(profile)
        profile["cover_letter"] = str(cover_letter).strip()
    profile = enrich_profile_salary(profile, job=job, fields=fields)

    cfg = ApplyConfig(
        job_url=str(job_url).strip(),
        resume_path=Path(resume_path).expanduser().resolve(),
        submit=_resolve_submit(raw, submit),
        notes=notes if notes is not None else raw.get("notes"),
        profile=profile,
        account_signup=account_signup,
        always_fill_fields=normalize_always_fill_fields(raw.get("always_fill_fields")),
    )
    cfg.validate()
    return cfg


def with_submit(config: ApplyConfig, submit: bool) -> ApplyConfig:
    return replace(config, submit=submit)
