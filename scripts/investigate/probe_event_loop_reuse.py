"""Verify worker-style single event loop can run two applies back-to-back.

Broken pattern (old worker):
  asyncio.run(job1); asyncio.run(job2)  → job2 Event loop is closed

Fixed pattern:
  async def main(): await job1; await job2
  asyncio.run(main())

Usage:
  .\\.venv\\Scripts\\python scripts\\investigate\\probe_event_loop_reuse.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
load_dotenv(ROOT / ".env")

from computer_use.browser.local import run_local_apply  # noqa: E402
from computer_use.config import load_apply_config  # noqa: E402


async def _short_run(label: str) -> int:
    os.environ["JOB_URL"] = "https://example.com"
    os.environ["MAX_TURNS"] = "2"
    config = load_apply_config(Path("apply.config.json"))
    from dataclasses import replace

    config = replace(
        config,
        job_url="https://example.com",
        submit=False,
        notes=f"event-loop reuse probe ({label})",
    )
    model = os.getenv("OPENAI_COMPUTER_USE_MODEL") or ""
    print(f"[{label}] starting run_local_apply", flush=True)
    code = await run_local_apply(model=model, config=config, costs_path="costs.json")
    print(f"[{label}] exit={code}", flush=True)
    return code


async def _fixed_pattern() -> tuple[int, int]:
    """Same shape as the fixed worker: one loop, await jobs sequentially."""
    code_a = await _short_run("A")
    code_b = await _short_run("B")
    return code_a, code_b


def _broken_pattern() -> tuple[int | str, int | str]:
    """Old worker shape — expected to fail on B."""
    try:
        a = asyncio.run(_short_run("broken-A"))
    except Exception as exc:
        print(f"[broken-A] EXC {type(exc).__name__}: {exc}", flush=True)
        a = f"EXC:{type(exc).__name__}"
    try:
        b = asyncio.run(_short_run("broken-B"))
    except Exception as exc:
        print(f"[broken-B] EXC {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        b = f"EXC:{type(exc).__name__}"
    return a, b


def main() -> int:
    print("=== FIXED pattern (one asyncio.run, two awaits) ===", flush=True)
    try:
        code_a, code_b = asyncio.run(_fixed_pattern())
    except Exception as exc:
        print(f"FIXED EXC {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        return 1
    print(f"FIXED SUMMARY A={code_a} B={code_b}", flush=True)
    if code_b not in (0, 1):  # 1 = max turns / agent reported not submitted — still ran
        return 1

    print("\n=== BROKEN pattern (two asyncio.run) — expect B to fail ===", flush=True)
    broken_a, broken_b = _broken_pattern()
    print(f"BROKEN SUMMARY A={broken_a} B={broken_b}", flush=True)
    if isinstance(broken_b, str) and (
        "Event loop" in broken_b or broken_b == "EXC:RuntimeError"
    ):
        print("Broken pattern still fails as expected; fixed pattern OK.", flush=True)
        return 0
    # If broken also works, environment may have changed — fixed path still OK.
    print("Fixed pattern OK.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
