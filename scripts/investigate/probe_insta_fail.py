"""Investigate intermittent first-turn 'Error getting response' on Glassdoor CUA.

Investigation only — does not modify production code.
Captures the real OpenAI/Agents exception (SDK only prints 'Error getting response').

Usage:
  .\\.venv\\Scripts\\python scripts\\investigate\\probe_insta_fail.py
  .\\.venv\\Scripts\\python scripts\\investigate\\probe_insta_fail.py --attempts 5
  .\\.venv\\Scripts\\python scripts\\investigate\\probe_insta_fail.py --settle 1.5
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
load_dotenv(ROOT / ".env")

from agents import Agent, ComputerTool, ModelSettings, Runner  # noqa: E402

from computer_use.browser.local import LocalCamoufoxComputer  # noqa: E402
from computer_use.prompts import AGENT_INSTRUCTIONS, build_prompt  # noqa: E402

DEFAULT_URL = "https://www.glassdoor.com/job-listing/j?jl=1010290518631"


def _find_resume() -> Path | None:
    resumes = ROOT / "resumes"
    if not resumes.is_dir():
        return None
    pdfs = sorted(resumes.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def _b64_stats(label: str, data: str | bytes) -> None:
    if isinstance(data, bytes):
        print(f"  {label}: type=bytes len={len(data)}", flush=True)
        return
    prefix = data[:48].replace("\n", "\\n")
    looks_data_url = data.startswith("data:")
    try:
        raw = data.split(",", 1)[-1] if looks_data_url else data
        decoded = base64.b64decode(raw, validate=False)
        png = decoded[:8] == b"\x89PNG\r\n\x1a\n"
        print(
            f"  {label}: type=str len={len(data)} data_url={looks_data_url} "
            f"decoded_bytes={len(decoded)} png_header={png} prefix={prefix!r}",
            flush=True,
        )
    except Exception as exc:
        print(f"  {label}: type=str len={len(data)} DECODE_FAIL={exc} prefix={prefix!r}", flush=True)


async def _one_attempt(
    *,
    attempt: int,
    url: str,
    resume: Path | None,
    settle_s: float,
    max_turns: int,
    tool_choice: str,
) -> dict:
    model = os.getenv("OPENAI_COMPUTER_USE_MODEL") or ""
    out: dict = {
        "attempt": attempt,
        "ok": False,
        "error_type": None,
        "error": None,
        "elapsed_s": None,
        "screenshot_lens": [],
    }
    print(f"\n=== attempt {attempt} model={model!r} settle={settle_s}s tool_choice={tool_choice!r} ===", flush=True)
    t0 = time.monotonic()
    try:
        async with LocalCamoufoxComputer(
            start_url=url,
            profile_dir=Path(os.getenv("BROWSER_PROFILE", ".camoufox-profile")),
            resume_path=resume,
        ) as computer:
            page = computer.page
            print(f"  after goto: url={page.url!r}", flush=True)

            if settle_s > 0:
                await asyncio.sleep(settle_s)
                print(f"  settled {settle_s}s → url={page.url!r}", flush=True)

            # Warm-up screenshot (same path the SDK will use on first computer_call).
            shot = await computer.screenshot()
            out["screenshot_lens"].append(len(shot) if isinstance(shot, str) else -1)
            _b64_stats("warmup_screenshot", shot)

            # Monkeypatch screenshot to log every capture during Runner.
            original = computer.screenshot

            async def logging_screenshot() -> str:
                s = await original()
                out["screenshot_lens"].append(len(s) if isinstance(s, str) else -1)
                _b64_stats(f"runner_screenshot#{len(out['screenshot_lens'])-1}", s)
                return s

            computer.screenshot = logging_screenshot  # type: ignore[method-assign]

            prompt = build_prompt(
                job_url=url,
                resume_path=str(resume) if resume else "resume.pdf",
                submit_application=True,
                profile={
                    "email": os.getenv("APPLICANT_EMAIL", "probe@example.com"),
                    "first_name": "Jared",
                    "last_name": "Stoddard",
                },
            )
            print(f"  prompt_len={len(prompt)}", flush=True)

            # Match production run_local_apply agent settings as closely as possible.
            agent = Agent(
                name="Job Apply",
                instructions=AGENT_INSTRUCTIONS
                + "\nBrowser cookies from prior login may already be present. "
                "Fill the form completely before Submit/Apply. hCaptcha is handled by NoneCap; "
                "other captchas by NopeCHA — only after they appear (usually post-submit). "
                "Never click or solve them; call wait after Submit until the challenge clears. "
                "When the review step is ready (or you are blocked), stop using the browser "
                "tool and write the final status report.",
                tools=[ComputerTool(computer=computer)],
                model=model,
                model_settings=ModelSettings(tool_choice=tool_choice),  # type: ignore[arg-type]
            )
            result = await Runner.run(agent, prompt, max_turns=max_turns)
            out["ok"] = True
            out["final"] = (result.final_output or "")[:200]
            print(f"  OK final={out['final']!r}", flush=True)
    except Exception as exc:
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)
        print(f"  FAIL {out['error_type']}: {exc}", flush=True)
        traceback.print_exc()
        # Common nested attrs on OpenAI errors
        for attr in ("status_code", "code", "type", "param", "body", "request_id"):
            if hasattr(exc, attr):
                print(f"  .{attr}={getattr(exc, attr)!r}", flush=True)
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                print(f"  .response.status_code={getattr(resp, 'status_code', None)}", flush=True)
                print(f"  .response.text={getattr(resp, 'text', None)}", flush=True)
            except Exception:
                pass
    finally:
        out["elapsed_s"] = round(time.monotonic() - t0, 2)
        print(f"  elapsed={out['elapsed_s']}s screenshots={out['screenshot_lens']}", flush=True)
    return out


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--settle", type=float, default=0.0, help="Seconds to wait after goto before Runner")
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument(
        "--tool-choice",
        default="auto",
        choices=["auto", "computer", "required"],
        help="ModelSettings.tool_choice (production currently uses auto)",
    )
    parser.add_argument(
        "--compare-tool-choice",
        action="store_true",
        help="Run each attempt twice: tool_choice=auto then computer",
    )
    args = parser.parse_args()

    resume = _find_resume()
    print(f"cwd={ROOT}", flush=True)
    print(f"url={args.url}", flush=True)
    print(f"resume={resume}", flush=True)
    print(f"OPENAI_COMPUTER_USE_MODEL={os.getenv('OPENAI_COMPUTER_USE_MODEL')!r}", flush=True)

    results: list[dict] = []
    for i in range(1, args.attempts + 1):
        choices = ["auto", "computer"] if args.compare_tool_choice else [args.tool_choice]
        for tc in choices:
            results.append(
                await _one_attempt(
                    attempt=i,
                    url=args.url,
                    resume=resume,
                    settle_s=args.settle,
                    max_turns=args.max_turns,
                    tool_choice=tc,
                )
            )

    ok = sum(1 for r in results if r["ok"])
    fail = len(results) - ok
    print(f"\n=== SUMMARY ok={ok} fail={fail} / {len(results)} ===", flush=True)
    for r in results:
        status = "OK" if r["ok"] else f"FAIL:{r['error_type']}"
        err = (r["error"] or "")[:160].replace("\n", " ")
        print(
            f"  attempt={r['attempt']} {status} elapsed={r['elapsed_s']}s "
            f"shots={r['screenshot_lens']} {err}",
            flush=True,
        )
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
