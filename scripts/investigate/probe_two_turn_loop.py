"""Manual 2-turn computer loop: responses → screenshot → computer_call_output.

Investigation only. Closest minimal reproduction of Agents SDK first failure
window without MaxTurns noise. Runs many iterations on Glassdoor.

Usage:
  .\\.venv\\Scripts\\python scripts\\investigate\\probe_two_turn_loop.py --attempts 8
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
load_dotenv(ROOT / ".env")

from computer_use.browser.local import LocalCamoufoxComputer  # noqa: E402

DEFAULT_URL = "https://www.glassdoor.com/job-listing/j?jl=1010290518631"


async def _run_once(client: OpenAI, model: str, url: str, attempt: int) -> dict:
    out: dict = {"attempt": attempt, "ok": False, "phase": None, "error": None}
    t0 = time.monotonic()
    print(f"\n=== attempt {attempt} ===", flush=True)
    try:
        async with LocalCamoufoxComputer(start_url=url, resume_path=None) as computer:
            out["phase"] = "first_response"
            first = client.responses.create(
                model=model,
                tools=[{"type": "computer"}],
                input=f"Look at the browser showing {url}. Take a screenshot and describe the page briefly.",
                truncation="auto",
            )
            call = next((o for o in (first.output or []) if getattr(o, "type", None) == "computer_call"), None)
            if call is None:
                out["error"] = f"no computer_call in first response status={first.status}"
                print(f"  FAIL {out['error']}", flush=True)
                return out
            call_id = call.call_id
            print(f"  first OK id={first.id} call_id={call_id}", flush=True)

            out["phase"] = "screenshot"
            shot = await computer.screenshot()
            if not isinstance(shot, str) or not shot:
                out["error"] = f"bad screenshot type={type(shot).__name__}"
                print(f"  FAIL {out['error']}", flush=True)
                return out
            try:
                raw = base64.b64decode(shot, validate=True)
                png_ok = raw.startswith(b"\x89PNG\r\n\x1a\n")
            except Exception as exc:
                out["error"] = f"screenshot b64 invalid: {exc}"
                print(f"  FAIL {out['error']}", flush=True)
                return out
            image_url = f"data:image/png;base64,{shot}"
            print(f"  screenshot ok len={len(shot)} png={png_ok} bytes={len(raw)}", flush=True)

            # Optional: open a tab mid-flight to stress race before second call.
            out["phase"] = "second_response"
            second = client.responses.create(
                model=model,
                tools=[{"type": "computer"}],
                previous_response_id=first.id,
                input=[
                    {
                        "type": "computer_call_output",
                        "call_id": call_id,
                        "output": {"type": "computer_screenshot", "image_url": image_url},
                    }
                ],
                truncation="auto",
            )
            types = [getattr(o, "type", None) for o in (second.output or [])]
            print(f"  second OK id={second.id} status={second.status} types={types}", flush=True)
            out["ok"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        print(f"  FAIL at {out['phase']}: {out['error']}", flush=True)
        traceback.print_exc()
    finally:
        out["elapsed"] = round(time.monotonic() - t0, 2)
        print(f"  elapsed={out['elapsed']}s", flush=True)
    return out


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()
    model = os.getenv("OPENAI_COMPUTER_USE_MODEL") or ""
    client = OpenAI()
    print(f"model={model!r} url={args.url}", flush=True)

    results = []
    for i in range(1, args.attempts + 1):
        results.append(await _run_once(client, model, args.url, i))

    ok = sum(1 for r in results if r["ok"])
    print(f"\n=== SUMMARY ok={ok} fail={len(results)-ok} / {len(results)} ===", flush=True)
    for r in results:
        print(
            f"  attempt={r['attempt']} ok={r['ok']} phase={r['phase']} "
            f"elapsed={r.get('elapsed')} err={r.get('error')}",
            flush=True,
        )
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
