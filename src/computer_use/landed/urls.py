"""Sanitize job / confirmation URLs before uploading evidence to Landed."""

from __future__ import annotations

from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

# Query keys that identify the posting (host-specific allowlists).
_INDEED_KEEP = frozenset({"jk", "vjk"})
_GLASSDOOR_KEEP = frozenset({"jl"})

# Indeed opens these after Easy Apply — a different recommended job, not confirmation.
_POST_APPLY_NOISE_MARKERS = (
    "indeedapplyaltjobs",
    "altjobs",
    "post_apply",
    "post-apply",
    "smart-apply-action=post_apply",
)

# Drop these everywhere (arrival / ads / analytics — not which job).
_TRACKING_PARAMS = frozenset(
    {
        "gh_src",
        "source",
        "src",
        "ref",
        "referrer",
        "lever-source",
        "lever-origin",
        "trk",
        "trackingid",
        "fbclid",
        "gclid",
        "msclkid",
        "mode",
        "advn",
        "adid",
        "ad",
        "from",
        "dest",
        "desth",
        "acatk",
        "rjptk",
        "pub",
        "camk",
        "xkcb",
        "xpse",
        "xfps",
        "tk",
        "xk",
        "continuedurl",
        "continueurl",
        "redirect",
        "redirectedfrom",
    }
)


def clean_job_url(url: str | None) -> str | None:
    """Return a minimal URL that still identifies the job / page.

    Indeed keeps only ``jk`` / ``vjk``; Glassdoor keeps ``jl``; other hosts drop
    tracking/utm params. Fragments are removed. Empty / non-http input is returned
    unchanged (or None when blank).
    """
    if url is None:
        return None
    raw = str(url).strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return raw
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return raw
    host = (parsed.hostname or "").lower()
    if not host:
        return raw

    path = parsed.path or ""
    path = path.rstrip("/") or "/"
    # Keep root as empty path style: https://host vs https://host/
    if path == "/":
        path = ""

    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    keep_keys = _keep_keys_for_host(host)
    if keep_keys is not None:
        kept = [(k, v) for k, v in pairs if k.lower() in keep_keys]
    else:
        kept = [
            (k, v)
            for k, v in pairs
            if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
        ]

    # Stable order for allowlisted keys; otherwise preserve first-seen order.
    if keep_keys is not None:
        order = {name: i for i, name in enumerate(sorted(keep_keys))}
        kept.sort(key=lambda kv: order.get(kv[0].lower(), 99))

    query = urlencode(kept, doseq=True)
    netloc = host
    if parsed.port and parsed.port not in (80, 443):
        netloc = f"{host}:{parsed.port}"

    return urlunparse((scheme, netloc, path, "", query, ""))


def _keep_keys_for_host(host: str) -> frozenset[str] | None:
    h = host[4:] if host.startswith("www.") else host
    if h == "indeed.com" or h.endswith(".indeed.com"):
        return _INDEED_KEEP
    if "glassdoor." in h:
        return _GLASSDOOR_KEEP
    return None


def is_post_apply_noise_url(url: str | None) -> bool:
    """True for Indeed/Glassdoor post-submit 'similar jobs' redirects (wrong listing)."""
    if not url or not str(url).strip():
        return False
    lowered = str(url).strip().lower()
    if any(marker in lowered for marker in _POST_APPLY_NOISE_MARKERS):
        return True
    # Indeed viewjob opened as an alt recommendation after apply.
    try:
        parsed = urlparse(lowered)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if (host == "indeed.com" or host.endswith(".indeed.com")) and "viewjob" in (
        parsed.path or ""
    ):
        qs = parse_qs(parsed.query)
        from_vals = [v.lower() for v in qs.get("from", [])]
        if any("altjob" in v or "postapply" in v or "post_apply" in v for v in from_vals):
            return True
    return False


def job_identity_key(url: str | None) -> str | None:
    """Stable id for a posting (indeed jk / glassdoor jl / path), or None."""
    if not url or not str(url).strip():
        return None
    cleaned = clean_job_url(url) or str(url).strip()
    try:
        parsed = urlparse(cleaned)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    qs = {k.lower(): v for k, v in parse_qsl(parsed.query, keep_blank_values=False)}
    if host == "indeed.com" or host.endswith(".indeed.com"):
        jk = qs.get("jk") or qs.get("vjk")
        if jk:
            return f"indeed:{jk.lower()}"
    if "glassdoor." in host:
        jl = qs.get("jl")
        if jl:
            return f"glassdoor:{jl.lower()}"
    path = (parsed.path or "").rstrip("/").lower()
    if path:
        return f"{host}{path}"
    return None


def evidence_job_url(
    *,
    current_url: str | None,
    start_url: str | None,
    url_before_submit: str | None = None,
) -> str | None:
    """URL to report for Landed evidence — never a post-apply alt-jobs listing.

    Prefers the claim/start job when the active tab drifted to a different posting.
    """
    start_clean = clean_job_url(start_url)
    before_clean = clean_job_url(url_before_submit)
    current_clean = clean_job_url(current_url)

    if is_post_apply_noise_url(current_url):
        # Always the claimed job — not the Indeed "similar jobs" listing.
        return start_clean or before_clean or current_clean

    start_key = job_identity_key(start_url)
    current_key = job_identity_key(current_url)
    if start_key and current_key and start_key != current_key:
        # Active tab is a different job than the one we claimed — keep the claim URL.
        return start_clean or before_clean or current_clean

    return current_clean or before_clean or start_clean
