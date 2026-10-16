"""Annual salary expectation for application forms.

Priority:
1. ``profile.salary_expectation_usd`` set to a number in apply.config — **overrides**
   auto calculation.
2. Else, when the job has a USD salary range (claim/DB), pick a point in that range
   from ``years_experience`` (and similar profile signals).
3. Else, reuse a Landed package ``salaryExpectation`` answer if present.
4. Else leave unset (agent must not invent salary).
"""

from __future__ import annotations

import math
import re
from typing import Any

_MIN_ANNUAL = 20_000
_MAX_ANNUAL = 600_000
_AMOUNT_RE = re.compile(
    r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(k|K)?",
)


def round_to_5k(value: float) -> int:
    return int(round(value / 5_000.0) * 5_000)


def format_salary_usd(amount: int | float) -> str:
    return f"${int(amount):,}"


def parse_salary_number(value: Any) -> int | None:
    """Parse a config/DB/answer value into an annual USD integer, or None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = int(value)
        if _MIN_ANNUAL <= n <= _MAX_ANNUAL:
            return n
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "na"}:
        return None
    # Prefer the first plausible annual amount in the string.
    for match in _AMOUNT_RE.finditer(text):
        raw = match.group(1).replace(",", "")
        try:
            n = float(raw)
        except ValueError:
            continue
        if match.group(2):
            n *= 1_000
        # Hourly-looking numbers are out of annual bounds after *1000 check above.
        ni = int(n)
        if _MIN_ANNUAL <= ni <= _MAX_ANNUAL:
            return ni
    return None


def _as_annual(value: Any) -> int | None:
    return parse_salary_number(value)


def extract_job_salary_range(
    job: dict[str, Any] | None = None,
    *,
    fields: dict[str, Any] | None = None,
) -> tuple[int | None, int | None, str | None]:
    """Return (min, max, currency) from a Landed claim job / fields blob."""
    job = job or {}
    currency = (
        job.get("salaryCurrency")
        or job.get("salary_currency")
        or None
    )
    if currency is not None:
        currency = str(currency).strip() or None

    low = _as_annual(
        job.get("salaryMin")
        if job.get("salaryMin") is not None
        else job.get("salary_min")
    )
    high = _as_annual(
        job.get("salaryMax")
        if job.get("salaryMax") is not None
        else job.get("salary_max")
    )

    if low is None and high is None and fields:
        # Fallback: Landed package / dynamic answer already computed a point.
        answers = fields.get("answers") or []
        if isinstance(answers, list):
            for ans in answers:
                if not isinstance(ans, dict):
                    continue
                key = str(ans.get("key") or "").strip()
                if key != "salaryExpectation":
                    continue
                point = parse_salary_number(ans.get("text"))
                if point is not None:
                    return point, point, currency or "USD"
    return low, high, currency


def _years_experience(profile: dict[str, Any]) -> float:
    raw = profile.get("years_experience")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return max(0.0, float(raw))
    if raw is not None:
        try:
            return max(0.0, float(str(raw).strip()))
        except ValueError:
            pass
    experience = profile.get("experience")
    if isinstance(experience, list) and experience:
        return min(12.0, float(len(experience)) * 1.25)
    return 2.0


def expectation_from_range(
    low: int,
    high: int,
    *,
    years_experience: float,
) -> int:
    """Pick a point in [low, high] biased by years of experience.

    Early-career sits near the lower third; ~5y near midpoint; senior toward
    the upper third. Rounded to the nearest $5k (Landed-compatible).
    """
    lo = min(low, high)
    hi = max(low, high)
    if lo == hi:
        return round_to_5k(lo)
    # Map 0y → 0.28, 2y → 0.40, 5y → 0.55, 8y → 0.68, 12y+ → 0.78
    t = max(0.0, min(1.0, years_experience / 12.0))
    frac = 0.28 + 0.50 * math.sqrt(t)
    return round_to_5k(lo + frac * (hi - lo))


def resolve_salary_expectation(
    profile: dict[str, Any],
    *,
    job: dict[str, Any] | None = None,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return profile copy with salary_expectation_usd filled when possible.

    A numeric ``salary_expectation_usd`` already on the profile is treated as an
    explicit apply.config override and is never replaced by auto calculation.
    """
    out = dict(profile)
    configured = parse_salary_number(out.get("salary_expectation_usd"))
    if configured is not None:
        out["salary_expectation_usd"] = configured
        out["salary_expectation_source"] = "apply.config override"
        if not str(out.get("salary_currency") or "").strip():
            out["salary_currency"] = "USD"
        return out

    low, high, currency = extract_job_salary_range(job, fields=fields)
    if currency and currency.upper() != "USD":
        # Only auto-fill USD annual expectations for now.
        return out

    if low is not None or high is not None:
        lo = low if low is not None else high
        hi = high if high is not None else low
        assert lo is not None and hi is not None
        years = _years_experience(out)
        point = expectation_from_range(lo, hi, years_experience=years)
        out["salary_expectation_usd"] = point
        out["salary_expectation_source"] = (
            f"auto from job range {format_salary_usd(lo)}–{format_salary_usd(hi)} "
            f"@ {years:g}y experience"
        )
        out["salary_currency"] = "USD"
        return out

    return out


def enrich_profile_salary(
    profile: dict[str, Any],
    *,
    job: dict[str, Any] | None = None,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Public entry used by apply config loaders / worker."""
    cleaned = {k: v for k, v in profile.items() if not str(k).startswith("_")}
    return resolve_salary_expectation(cleaned, job=job, fields=fields)
