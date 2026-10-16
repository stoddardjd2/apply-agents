"""Log the exact first Responses API payload + errors (no computer loop).

Investigation only. Builds the same ComputerTool payload the Agents SDK would
send for gpt-6-luna / tool_choice=auto|computer, then calls responses.create
repeatedly to catch intermittent 400/429/5xx.

Usage:
  .\\.venv\\Scripts\\python scripts\\investigate\\probe_first_response.py --attempts 10
"""

from __future__ import annotations

import argparse
import asyncio
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

from agents import AsyncComputer, ComputerTool, ModelSettings  # noqa: E402
from agents.models.openai_responses import Converter  # noqa: E402


class _StubComputer(AsyncComputer):
    @property
    def environment(self):
        return "browser"

    @property
    def dimensions(self):
        return (1280, 800)

    async def screenshot(self) -> str:
        return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

    async def click(self, x, y, button="left"):
        pass

    async def double_click(self, x, y):
        pass

    async def scroll(self, x, y, scroll_x, scroll_y):
        pass

    async def type(self, text):
        pass

    async def wait(self):
        pass

    async def move(self, x, y):
        pass

    async def keypress(self, keys):
        pass

    async def drag(self, path):
        pass


def _build_tools(tool_choice: str) -> tuple[list, object]:
    model = os.getenv("OPENAI_COMPUTER_USE_MODEL")
    tools = [ComputerTool(computer=_StubComputer())]
    use_preview = Converter._should_use_preview_computer_tool(
        model=model,
        tool_choice=tool_choice,
    )
    converted = Converter.convert_tools(
        tools,
        [],
        model=model,
        tool_choice=tool_choice,
    )
    # ConvertedTools dataclass/object
    payload = getattr(converted, "tools", converted)
    return list(payload), use_preview


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--tool-choice", default="auto", choices=["auto", "computer"])
    parser.add_argument("--sleep", type=float, default=0.2)
    args = parser.parse_args()

    model = os.getenv("OPENAI_COMPUTER_USE_MODEL") or ""
    tools, use_preview = _build_tools(args.tool_choice)
    print(f"model={model!r} tool_choice={args.tool_choice!r} use_preview={use_preview}", flush=True)
    print(f"tools_payload={tools!r}", flush=True)

    client = OpenAI()
    ok = fail = 0
    for i in range(1, args.attempts + 1):
        t0 = time.monotonic()
        try:
            resp = client.responses.create(
                model=model,
                tools=tools,
                input=(
                    "Open https://www.glassdoor.com/job-listing/j?jl=1010290518631 "
                    "and begin the application. Use the computer tool."
                ),
                truncation="auto",
            )
            types = [getattr(o, "type", None) for o in (resp.output or [])]
            print(
                f"[{i}] OK {time.monotonic()-t0:.2f}s status={resp.status} output_types={types}",
                flush=True,
            )
            ok += 1
        except Exception as exc:
            fail += 1
            print(f"[{i}] FAIL {time.monotonic()-t0:.2f}s {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc()
        time.sleep(args.sleep)

    print(f"\n=== SUMMARY ok={ok} fail={fail} / {args.attempts} ===", flush=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    # Converter.convert_tools may need a running loop for nothing, but keep sync.
    raise SystemExit(main())
