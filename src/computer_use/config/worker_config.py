"""Worker queue config: one blocklist that matches adapters and URL hosts."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_WORKER_CONFIG_PATH = Path(os.getenv("WORKER_CONFIG", "worker.config.json"))

# One config name → adapter ids + host suffixes checked against apply URLs.
SITE_ALIASES: dict[str, dict[str, list[str]]] = {
    "linkedin": {
        "adapters": ["linkedin"],
        "hosts": ["linkedin.com"],
    },
    "workday": {
        "adapters": ["workday"],
        "hosts": ["myworkdayjobs.com", "workday.com"],
    },
    "indeed": {
        "adapters": ["indeed"],
        "hosts": ["indeed.com", "smartapply.indeed.com"],
    },
    "glassdoor": {
        "adapters": ["glassdoor"],
        "hosts": ["glassdoor.com"],
    },
    "ziprecruiter": {
        "adapters": ["ziprecruiter"],
        "hosts": ["ziprecruiter.com"],
    },
    "greenhouse": {
        "adapters": ["greenhouse"],
        "hosts": ["greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io"],
    },
    "lever": {
        "adapters": ["lever"],
        "hosts": ["lever.co", "jobs.lever.co"],
    },
    "ashby": {
        "adapters": ["ashby"],
        "hosts": ["ashbyhq.com", "jobs.ashbyhq.com"],
    },
}


@dataclass(frozen=True)
class WorkerConfig:
    landed_api_base: str
    poll_interval_seconds: float = 15.0
    worker_id: str = "apply-agents"
    blocklist: list[str] = field(default_factory=lambda: ["linkedin", "workday"])
    allowlist: list[str] = field(default_factory=list)
    submit: bool | None = None
    apply_config_path: Path = Path("apply.config.json")
    costs_path: str = "costs.json"
    browser_profile: str = ".camoufox-profile"
    resume_dir: Path = Path(".cache/worker-resumes")

    def claim_adapters(self) -> list[str]:
        """Adapters sent to Landed claim. Empty = claim any; allowlist restricts claim."""
        if not self.allowlist:
            return []
        adapters: list[str] = []
        for entry in self.allowlist:
            adapters.extend(_expand_entry(entry)["adapters"])
        # De-dupe, preserve order
        seen: set[str] = set()
        out: list[str] = []
        for a in adapters:
            if a not in seen:
                seen.add(a)
                out.append(a)
        return out

    def is_blocked(self, *, adapter: str | None, apply_url: str | None) -> str | None:
        """Return matching blocklist entry if blocked, else None."""
        adapter_l = (adapter or "").strip().lower()
        host = _hostname(apply_url)

        if self.allowlist:
            if not _matches_any(self.allowlist, adapter_l, host):
                return f"not in allowlist (adapter={adapter_l or '?'}, host={host or '?'})"

        for entry in self.blocklist:
            if _entry_matches(entry, adapter_l, host):
                return entry
        return None


def _hostname(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _expand_entry(entry: str) -> dict[str, list[str]]:
    key = entry.strip().lower()
    if not key:
        return {"adapters": [], "hosts": []}
    if key in SITE_ALIASES:
        alias = SITE_ALIASES[key]
        return {
            "adapters": list(alias["adapters"]),
            "hosts": list(alias["hosts"]),
        }
    # Raw host or adapter id
    if "." in key:
        return {"adapters": [], "hosts": [key.lstrip(".")]}
    return {"adapters": [key], "hosts": []}


def _host_matches(host: str, pattern: str) -> bool:
    if not host or not pattern:
        return False
    pattern = pattern.lower().lstrip(".")
    return host == pattern or host.endswith("." + pattern)


def _entry_matches(entry: str, adapter: str, host: str) -> bool:
    expanded = _expand_entry(entry)
    if adapter and adapter in expanded["adapters"]:
        return True
    return any(_host_matches(host, h) for h in expanded["hosts"])


def _matches_any(entries: list[str], adapter: str, host: str) -> bool:
    return any(_entry_matches(e, adapter, host) for e in entries)


def load_worker_config(path: Path | None = None) -> WorkerConfig:
    config_path = path or DEFAULT_WORKER_CONFIG_PATH
    raw: dict[str, Any] = {}
    if config_path.is_file():
        raw = json.loads(config_path.read_text(encoding="utf-8"))

    from ..landed.env import DEFAULT_LANDED_API_URL, load_landed_connection

    env_api, _env_token, _src = load_landed_connection()
    api_base = (
        (raw.get("landed_api_base") or "").strip()
        or env_api
        or DEFAULT_LANDED_API_URL
    ).strip()

    submit_raw = raw.get("submit", None)
    submit: bool | None
    if submit_raw is None:
        submit = None
    else:
        submit = bool(submit_raw)

    apply_cfg = Path(
        os.getenv("APPLY_CONFIG")
        or raw.get("apply_config")
        or "apply.config.json"
    )
    resume_dir = Path(raw.get("resume_dir") or ".cache/worker-resumes")
    if not resume_dir.is_absolute():
        resume_dir = resume_dir.resolve()

    return WorkerConfig(
        landed_api_base=api_base,
        poll_interval_seconds=float(raw.get("poll_interval_seconds") or 15),
        worker_id=str(raw.get("worker_id") or "apply-agents"),
        blocklist=[str(x).strip() for x in (raw.get("blocklist") or ["linkedin", "workday"]) if str(x).strip()],
        allowlist=[str(x).strip() for x in (raw.get("allowlist") or []) if str(x).strip()],
        submit=submit,
        apply_config_path=apply_cfg,
        costs_path=str(raw.get("costs_path") or os.getenv("COSTS_PATH") or "costs.json"),
        browser_profile=str(
            raw.get("browser_profile")
            or os.getenv("BROWSER_PROFILE")
            or ".camoufox-profile"
        ),
        resume_dir=resume_dir,
    )
