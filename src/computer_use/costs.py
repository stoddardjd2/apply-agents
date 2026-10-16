"""Estimate and persist Agents API computer-use run costs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Standard per-1M-token rates for computer-use-capable models (USD).
# Source: https://developers.openai.com/api/docs/pricing
MODEL_PRICING_USD_PER_MTOTOKEN: dict[str, dict[str, float]] = {
    "gpt-6-astra": {"input": 10.0, "cached_input": 1.0, "output": 50.0},
    "gpt-6.1-sol": {"input": 2.0, "cached_input": 0.10, "output": 10.0},
    "gpt-6-luna": {"input": 0.10, "cached_input": 0.01, "output": 0.50},
}

DEFAULT_COSTS_PATH = Path("costs.json")


def estimate_cost_usd(
    *,
    model: str,
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
) -> float | None:
    pricing = MODEL_PRICING_USD_PER_MTOTOKEN.get(model)
    if pricing is None:
        return None

    uncached = max(input_tokens - cached_tokens, 0)
    cost = (
        (uncached / 1_000_000) * pricing["input"]
        + (cached_tokens / 1_000_000) * pricing["cached_input"]
        + (output_tokens / 1_000_000) * pricing["output"]
    )
    return round(cost, 6)


def record_run_cost(
    *,
    costs_path: Path = DEFAULT_COSTS_PATH,
    session_id: str,
    model: str,
    mode: str,
    usage_bundle: dict[str, Any],
    completed: bool,
    notes: str | None = None,
) -> dict[str, Any]:
    totals = usage_bundle.get("totals") or {}
    estimated = estimate_cost_usd(
        model=model,
        input_tokens=int(totals.get("input_tokens", 0)),
        cached_tokens=int(totals.get("cached_tokens", 0)),
        output_tokens=int(totals.get("output_tokens", 0)),
    )

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "model": model,
        "mode": mode,
        "completed": completed,
        "usage": totals,
        "turns": usage_bundle.get("turns") or [],
        "estimated_cost_usd": estimated,
        "pricing_note": (
            "Estimate from Agents API turn usage and published per-token rates. "
            "Not a final bill; usage can be null/late and may omit sandbox/tool fees."
        ),
        "notes": notes,
    }

    payload: dict[str, Any]
    if costs_path.exists():
        payload = json.loads(costs_path.read_text(encoding="utf-8"))
    else:
        payload = {"runs": [], "totals": {"estimated_cost_usd": 0.0, "runs": 0}}

    runs = list(payload.get("runs") or [])
    runs.append(entry)
    payload["runs"] = runs

    total_cost = 0.0
    for run in runs:
        value = run.get("estimated_cost_usd")
        if isinstance(value, (int, float)):
            total_cost += float(value)
    payload["totals"] = {
        "runs": len(runs),
        "estimated_cost_usd": round(total_cost, 6),
        "input_tokens": sum(int((r.get("usage") or {}).get("input_tokens", 0)) for r in runs),
        "output_tokens": sum(int((r.get("usage") or {}).get("output_tokens", 0)) for r in runs),
    }

    costs_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return entry
