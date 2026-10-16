"""Resolve Landed API URL + worker token without duplicating secrets.

Defaults match Landed's browser-worker:
  LANDED_API_URL=http://localhost:8180
  LANDED_WORKER_TOKEN from ../landed/.env (sibling repo)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_LANDED_API_URL = "http://localhost:8180"

# src/computer_use/landed/env.py → repo root → sibling ../landed/.env
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_LANDED_ENV = _REPO_ROOT.parent / "landed" / ".env"


def _candidate_landed_env_paths() -> list[Path]:
    paths: list[Path] = []
    override = os.getenv("LANDED_ENV_FILE", "").strip()
    if override:
        paths.append(Path(override).expanduser())
    paths.append(_DEFAULT_LANDED_ENV)
    paths.append(_REPO_ROOT.parent / "landed-wt" / ".env")
    return paths


def load_landed_connection() -> tuple[str, str, str | None]:
    """Return (api_base, worker_token, source_note). Local env wins over Landed .env."""
    landed_vals: dict[str, str | None] = {}
    source: str | None = None
    for path in _candidate_landed_env_paths():
        if path.is_file():
            landed_vals = dict(dotenv_values(path))
            source = str(path.resolve())
            break

    api = (
        os.getenv("LANDED_API_BASE", "").strip()
        or os.getenv("LANDED_API_URL", "").strip()
        or (landed_vals.get("LANDED_API_URL") or "").strip()
        or (landed_vals.get("LANDED_API_BASE") or "").strip()
        or DEFAULT_LANDED_API_URL
    )
    token = (
        os.getenv("LANDED_WORKER_TOKEN", "").strip()
        or (landed_vals.get("LANDED_WORKER_TOKEN") or "").strip()
    )
    return api.rstrip("/"), token, source
