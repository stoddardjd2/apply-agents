"""Check whether a second Camoufox on the same profile fails intermittently.

Investigation only. Opens one context on BROWSER_PROFILE, then tries a second
parallel AsyncCamoufox on the SAME profile (what happens if worker + probe overlap).

Usage:
  .\\.venv\\Scripts\\python scripts\\investigate\\probe_profile_contention.py
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

from computer_use.browser.camoufox_setup import apply_camoufox_install_dir  # noqa: E402

apply_camoufox_install_dir()
from camoufox.async_api import AsyncCamoufox  # noqa: E402

from computer_use.browser.local import _camoufox_kwargs, _resolve_nopecha_addons  # noqa: E402


async def _open(label: str, profile: Path) -> tuple[str, Exception | None]:
    print(f"[{label}] launching profile={profile}", flush=True)
    try:
        addons = _resolve_nopecha_addons()
        async with AsyncCamoufox(**_camoufox_kwargs(profile, addons=addons)) as ctx:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto("https://example.com", wait_until="domcontentloaded")
            png = await page.screenshot(full_page=False)
            print(f"[{label}] OK url={page.url} screenshot_bytes={len(png)}", flush=True)
            await asyncio.sleep(2)  # hold open so overlap is real
            return label, None
    except Exception as exc:
        print(f"[{label}] FAIL {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        return label, exc


async def main() -> int:
    profile = Path(os.getenv("BROWSER_PROFILE", ".camoufox-profile")).resolve()
    print(f"shared_profile={profile}", flush=True)
    print("Launching two Camoufox instances concurrently on the same profile…", flush=True)
    results = await asyncio.gather(
        _open("A", profile),
        _open("B", profile),
        return_exceptions=False,
    )
    fails = [(lab, err) for lab, err in results if err is not None]
    print(f"\n=== SUMMARY fails={len(fails)} / {len(results)} ===", flush=True)
    for lab, err in fails:
        print(f"  {lab}: {type(err).__name__}: {err}", flush=True)
    if not fails:
        print("  Both instances succeeded (contention may be OS/timing specific).", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
