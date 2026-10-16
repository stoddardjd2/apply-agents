"""Probe Camoufox screenshot races / bad payloads that can cause OpenAI 400s.

Investigation only. Opens headed Camoufox, hammers screenshot while forcing
navigation / new tabs, and reports empty/corrupt captures.

Usage:
  .\\.venv\\Scripts\\python scripts\\investigate\\probe_screenshot_race.py
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
load_dotenv(ROOT / ".env")

from computer_use.browser.local import LocalCamoufoxComputer  # noqa: E402

DEFAULT_URL = "https://www.glassdoor.com/job-listing/j?jl=1010290518631"


def _analyze(label: str, shot: str | bytes) -> dict:
    info: dict = {"label": label, "ok": False, "reason": None, "len": None}
    if isinstance(shot, bytes):
        info["reason"] = "bytes_not_str"
        info["len"] = len(shot)
        print(f"  BAD {label}: returned bytes len={len(shot)}", flush=True)
        return info
    if not isinstance(shot, str) or not shot:
        info["reason"] = "empty_or_not_str"
        print(f"  BAD {label}: empty/non-str type={type(shot).__name__}", flush=True)
        return info
    info["len"] = len(shot)
    if shot.startswith("data:"):
        info["reason"] = "already_data_url"
        print(f"  BAD {label}: already data URL len={len(shot)}", flush=True)
        return info
    try:
        raw = base64.b64decode(shot, validate=True)
    except Exception as exc:
        info["reason"] = f"b64_invalid:{exc}"
        print(f"  BAD {label}: invalid base64 ({exc}) len={len(shot)}", flush=True)
        return info
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        info["reason"] = "not_png"
        print(f"  BAD {label}: decoded but not PNG header len_raw={len(raw)}", flush=True)
        return info
    info["ok"] = True
    print(f"  OK  {label}: b64_len={len(shot)} png_bytes={len(raw)}", flush=True)
    return info


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--bursts", type=int, default=8, help="Concurrent screenshots per burst")
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()

    results: list[dict] = []
    async with LocalCamoufoxComputer(
        start_url=args.url,
        profile_dir=Path(os.getenv("BROWSER_PROFILE", ".camoufox-profile")),
        resume_path=None,
    ) as computer:
        print(f"start url={computer.page.url}", flush=True)

        # Immediate screenshot right after domcontentloaded (production path).
        results.append(_analyze("immediate", await computer.screenshot()))

        # Concurrent screenshot storm (race with ourselves / navigation).
        for round_i in range(1, args.rounds + 1):
            print(f"\n-- concurrent burst round {round_i} x{args.bursts} --", flush=True)
            shots = await asyncio.gather(
                *[computer.screenshot() for _ in range(args.bursts)],
                return_exceptions=True,
            )
            for idx, shot in enumerate(shots):
                if isinstance(shot, Exception):
                    info = {"label": f"burst{round_i}_{idx}", "ok": False, "reason": repr(shot)}
                    print(f"  BAD burst{round_i}_{idx}: EXC {shot!r}", flush=True)
                    results.append(info)
                else:
                    results.append(_analyze(f"burst{round_i}_{idx}", shot))

        # Navigate again mid-flight (Glassdoor-like redirect churn).
        print("\n-- screenshot during reload --", flush=True)

        async def reload() -> None:
            await computer.page.reload(wait_until="domcontentloaded")

        reload_task = asyncio.create_task(reload())
        await asyncio.sleep(0.05)
        try:
            mid = await computer.screenshot()
            results.append(_analyze("during_reload", mid))
        except Exception as exc:
            results.append({"label": "during_reload", "ok": False, "reason": repr(exc)})
            print(f"  BAD during_reload: EXC {exc!r}", flush=True)
        await reload_task

        # Open a new tab while screenshotting (mimics Apply popup race).
        print("\n-- screenshot during new tab --", flush=True)
        assert computer._context is not None

        async def open_tab() -> None:
            p = await computer._context.new_page()
            await p.goto("https://example.com", wait_until="domcontentloaded")

        tab_task = asyncio.create_task(open_tab())
        await asyncio.sleep(0.05)
        try:
            mid2 = await computer.screenshot()
            results.append(_analyze("during_new_tab", mid2))
        except Exception as exc:
            results.append({"label": "during_new_tab", "ok": False, "reason": repr(exc)})
            print(f"  BAD during_new_tab: EXC {exc!r}", flush=True)
        await tab_task
        await asyncio.sleep(0.5)
        results.append(_analyze("after_new_tab_settle", await computer.screenshot()))

    bad = [r for r in results if not r.get("ok")]
    print(f"\n=== SUMMARY total={len(results)} bad={len(bad)} ===", flush=True)
    for r in bad:
        print(f"  {r}", flush=True)
    if not bad:
        print("  No bad screenshots observed in this run.", flush=True)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
