"""Detect Glassdoor/Indeed → employer/ATS escapes (mirrors Landed aggregator.js)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Glassdoor / Indeed apply hosts — leaving these triggers escape_aggregator.
_AGGREGATOR_HOST = re.compile(
    r"(^|\.)(glassdoor\.[a-z.]+|indeed\.[a-z.]+)$",
    re.IGNORECASE,
)

# First matching host fragment → adapter name (lowercase, Landed-style).
_ADAPTER_HOSTS: list[tuple[str, str]] = [
    ("boards.greenhouse.io", "greenhouse"),
    ("job-boards.greenhouse.io", "greenhouse"),
    ("greenhouse.io", "greenhouse"),
    ("jobs.lever.co", "lever"),
    ("lever.co", "lever"),
    ("jobs.ashbyhq.com", "ashby"),
    ("ashbyhq.com", "ashby"),
    ("myworkdayjobs.com", "workday"),
    ("workday.com", "workday"),
    ("workable.com", "workable"),
    ("smartrecruiters.com", "smartrecruiters"),
    ("applytojob.com", "jazzhr"),
    ("greenhouse.io", "greenhouse"),
    ("smartapply.indeed.com", "indeed"),
    ("indeed.com", "indeed"),
    ("glassdoor.com", "glassdoor"),
    ("linkedin.com", "linkedin"),
    ("ziprecruiter.com", "ziprecruiter"),
]


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def is_aggregator_host(url: str | None) -> bool:
    """True when URL is on Glassdoor or Indeed (including regional TLDs)."""
    if not url or not str(url).strip():
        return False
    host = _host(str(url).strip())
    if not host:
        return False
    return bool(_AGGREGATOR_HOST.search(host))


def adapter_for_url(url: str | None) -> str:
    """Best-effort adapter id for Landed detail.adapter (default generic)."""
    host = _host(str(url or "").strip())
    if not host:
        return "generic"
    for needle, name in _ADAPTER_HOSTS:
        if host == needle or host.endswith("." + needle):
            return name
    return "generic"
