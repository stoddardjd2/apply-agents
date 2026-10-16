"""Learnings service.

Persists reusable apply tips (agent-recorded) and hard multi-turn runs
(harness-recorded) to apply_learnings.json for future prompt injection and review.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LEARNINGS_PATH = Path("apply_learnings.json")
_MAX_ENTRIES = 200
_MAX_EXCERPTS = 8
_MAX_EXCERPT_CHARS = 400


def learnings_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.getenv("APPLY_LEARNINGS_PATH")
    return Path(env) if env else DEFAULT_LEARNINGS_PATH


def hard_run_turn_threshold() -> int:
    """LEARNING_TURN_THRESHOLD — record a hard_run when turns >= this (default 12)."""
    raw = os.getenv("LEARNING_TURN_THRESHOLD", "12")
    try:
        return max(3, int(raw))
    except ValueError:
        return 12


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(text: str, limit: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (s or "learning")[:limit]


def load_learnings(path: Path | None = None) -> dict[str, Any]:
    kb_path = learnings_path(path)
    if not kb_path.exists():
        return {"version": 1, "entries": []}
    try:
        data = json.loads(kb_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "entries": []}
    if not isinstance(data, dict):
        return {"version": 1, "entries": []}
    entries = data.get("entries")
    if not isinstance(entries, list):
        entries = []
    return {"version": int(data.get("version") or 1), "entries": entries}


def save_learnings(data: dict[str, Any], path: Path | None = None) -> Path:
    kb_path = learnings_path(path)
    entries = list(data.get("entries") or [])
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]
    payload = {"version": int(data.get("version") or 1), "entries": entries}
    kb_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return kb_path


def _clip(text: str, limit: int = _MAX_EXCERPT_CHARS) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def record_tip(
    *,
    summary: str,
    detail: str | None = None,
    job_url: str | None = None,
    company: str | None = None,
    board: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Append a reusable tip (agent- or harness-discovered)."""
    summary = _clip(summary, 280)
    if not summary:
        return {"ok": False, "message": "empty summary"}
    data = load_learnings(path)
    entry = {
        "id": f"tip_{_slug(summary)}_{_utc_now().replace(':', '').replace('-', '')}",
        "kind": "tip",
        "summary": summary,
        "detail": _clip(detail or "", 800) or None,
        "job_url": job_url,
        "company": company,
        "board": board,
        "updated_at": _utc_now(),
    }
    data["entries"].append(entry)
    save_learnings(data, path)
    return {"ok": True, "entry": entry}


def record_hard_run(
    *,
    turns: int,
    job_url: str | None = None,
    company: str | None = None,
    summary: str | None = None,
    thinking_excerpts: list[str] | None = None,
    actions_summary: str | None = None,
    final_report: str | None = None,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Append a hard multi-turn run for later review (skips if under threshold)."""
    if turns < hard_run_turn_threshold():
        return None
    excerpts = [
        _clip(x)
        for x in (thinking_excerpts or [])
        if str(x or "").strip()
    ][-_MAX_EXCERPTS:]
    data = load_learnings(path)
    entry = {
        "id": f"hard_{turns}_{_slug(job_url or 'job')}_{_utc_now().replace(':', '').replace('-', '')}",
        "kind": "hard_run",
        "turns": int(turns),
        "summary": _clip(
            summary
            or f"Apply run used {turns} turns — review thinking excerpts for bottlenecks.",
            400,
        ),
        "thinking_excerpts": excerpts,
        "actions_summary": _clip(actions_summary or "", 400) or None,
        "final_report": _clip(final_report or "", 600) or None,
        "job_url": job_url,
        "company": company,
        "updated_at": _utc_now(),
    }
    data["entries"].append(entry)
    save_learnings(data, path)
    return entry


def recent_tips(*, limit: int = 12, path: Path | None = None) -> list[dict[str, Any]]:
    entries = load_learnings(path).get("entries") or []
    tips = [e for e in entries if isinstance(e, dict) and e.get("kind") == "tip"]
    return tips[-limit:]
