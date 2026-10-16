"""Open JazzHR apply page, detect captcha, wait for NopeCHA (no agent).

Usage:
  .\\.venv\\Scripts\\python scripts\\investigate\\probe_jazzhr_recaptcha.py
"""

from __future__ import annotations

import asyncio
import json
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
from computer_use.captcha.nopecha import (  # noqa: E402
    runtime_addon_dir,
    nopecha_api_key,
    nopecha_solve_timeout_ms,
)

URL = (
    "https://vivsofttechnologiesfa.applytojob.com/apply/G1EVapDRUh/"
    "Full-Stack-Developer?source=INDE&~"
)


async def main() -> int:
    key = nopecha_api_key()
    timeout_s = nopecha_solve_timeout_ms() / 1000
    print(f"url={URL}", flush=True)
    print(f"NOPECHA_API_KEY set={bool(key)} timeout_s={timeout_s}", flush=True)

    # Use a throwaway profile so we don't fight a locked worker profile.
    profile = ROOT / ".camoufox-profile-probe-jazzhr"
    profile.mkdir(parents=True, exist_ok=True)

    api_hits: list[dict] = []

    async with LocalCamoufoxComputer(
        start_url=URL,
        resume_path=None,
        profile_dir=profile,
    ) as computer:
        page = computer.page
        context = page.context

        async def on_response(response) -> None:
            url = response.url or ""
            if "api.nopecha.com" not in url.lower():
                return
            body = ""
            try:
                body = (await response.text())[:300]
            except Exception as exc:  # noqa: BLE001
                body = f"<read fail: {exc}>"
            api_hits.append(
                {"status": response.status, "url": url[:120], "body": body}
            )
            print(f"nopecha_api status={response.status} url={url[:100]} body={body!r}", flush=True)

        context.on("response", on_response)

        manifest_path = runtime_addon_dir() / "manifest.json"
        if manifest_path.is_file():
            block = json.loads(manifest_path.read_text(encoding="utf-8")).get("nopecha", {})
            print(
                "runtime_settings "
                f"recaptcha_auto_open={block.get('recaptcha_auto_open')} "
                f"recaptcha_auto_solve={block.get('recaptcha_auto_solve')} "
                f"key_set={bool(block.get('key'))}",
                flush=True,
            )

        await asyncio.sleep(2)
        print(f"page={page.url}", flush=True)

        # Cookie banner can sit on top of Human Check
        for label in ("Allow", "Accept", "Accept All"):
            try:
                btn = page.get_by_role("button", name=label)
                if await btn.count() and await btn.first.is_visible():
                    await btn.first.click(timeout=2000)
                    print(f"clicked cookie button={label!r}", flush=True)
                    await asyncio.sleep(0.5)
                    break
            except Exception:  # noqa: BLE001
                pass

        info = await page.evaluate(
            """() => {
              const frames = [...document.querySelectorAll('iframe')].map((f) => ({
                src: (f.getAttribute('src') || '').slice(0, 180),
                w: f.offsetWidth, h: f.offsetHeight,
                title: f.getAttribute('title') || '',
              }));
              const hasG = !!document.querySelector(
                '.g-recaptcha, #g-recaptcha, textarea[name="g-recaptcha-response"]'
              );
              return { frames, hasG };
            }"""
        )
        print(f"detect_dom={info}", flush=True)

        kind = await computer._detect_interactive_captcha(page)
        print(f"detect_kind={kind!r}", flush=True)

        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)
        kind2 = await computer._detect_interactive_captcha(page)
        print(f"detect_kind_after_scroll={kind2!r}", flush=True)

        computer._captcha_armed = True
        computer._captcha_wait_exhausted = False
        print("Calling _resolve_captcha_if_needed (NopeCHA wait)…", flush=True)
        t0 = time.monotonic()
        await computer._resolve_captcha_if_needed(page)
        print(
            f"resolve done in {time.monotonic()-t0:.1f}s "
            f"armed={computer._captcha_armed} exhausted={computer._captcha_wait_exhausted}",
            flush=True,
        )

        kind3 = await computer._detect_interactive_captcha(page)
        token = await page.evaluate(
            """() => {
              const el = document.querySelector(
                'textarea[name="g-recaptcha-response"], textarea[name="h-captcha-response"]'
              );
              return el ? {name: el.name, len: (el.value||'').length} : null;
            }"""
        )
        print(f"after kind={kind3!r} token={token}", flush=True)
        print(f"nopecha_api_hits={len(api_hits)}", flush=True)

        await asyncio.sleep(3)
    return 0 if kind3 is None and token and token.get("len", 0) > 40 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
