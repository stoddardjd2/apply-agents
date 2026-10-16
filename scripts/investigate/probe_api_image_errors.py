"""Map bad computer screenshot payloads to OpenAI error messages.

Investigation only. Uses Responses API + GA `computer` tool (no Camoufox).
Helps confirm whether 'Error getting response' is an invalid image_url 400.

Usage:
  .\\.venv\\Scripts\\python scripts\\investigate\\probe_api_image_errors.py
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
load_dotenv(ROOT / ".env")

TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _try(label: str, image_url: str, *, model: str, client: OpenAI, call_id: str) -> None:
    print(f"\n-- {label} --", flush=True)
    print(f"  image_url preview={image_url[:80]!r}… len={len(image_url)}", flush=True)
    try:
        client.responses.create(
            model=model,
            tools=[{"type": "computer"}],
            previous_response_id=None,
            input=[
                {
                    "type": "computer_call_output",
                    "call_id": call_id,
                    "output": {
                        "type": "computer_screenshot",
                        "image_url": image_url,
                    },
                }
            ],
            truncation="auto",
        )
        print("  OK (unexpected — call_id may have been ignored)", flush=True)
    except Exception as exc:
        print(f"  FAIL {type(exc).__name__}: {exc}", flush=True)


def main() -> int:
    model = os.getenv("OPENAI_COMPUTER_USE_MODEL") or ""
    client = OpenAI()
    print(f"model={model!r}", flush=True)

    # Step 1: get a real computer_call + call_id from the model.
    print("\n== initial computer call ==", flush=True)
    first = client.responses.create(
        model=model,
        tools=[{"type": "computer"}],
        input="Take a screenshot of the screen.",
        truncation="auto",
    )
    call_id = None
    for item in first.output or []:
        if getattr(item, "type", None) == "computer_call":
            call_id = getattr(item, "call_id", None)
            break
    print(f"response_id={first.id} status={first.status} call_id={call_id}", flush=True)
    if not call_id:
        print("No computer_call in first response; cannot test outputs.", flush=True)
        return 1

    cases = {
        "valid_tiny_png_data_url": f"data:image/png;base64,{TINY_PNG_B64}",
        "raw_b64_no_prefix": TINY_PNG_B64,
        "empty_string": "",
        "data_url_empty_b64": "data:image/png;base64,",
        "data_url_invalid_b64": "data:image/png;base64,@@@not-valid@@@",
        "double_prefixed": f"data:image/png;base64,data:image/png;base64,{TINY_PNG_B64}",
        "bytes_repr_as_string": f"data:image/png;base64,{base64.b64decode(TINY_PNG_B64)!r}",
    }

    # Use a fresh computer_call for each bad case by chaining from previous_response
    # when possible; for invalid ones the call_id from `first` is enough to show the 400.
    for label, image_url in cases.items():
        # Re-issue a short request that expects a computer call, then reply with the payload.
        # Simpler: reply to the original call_id — API validates image even if call is stale.
        _try(label, image_url, model=model, client=client, call_id=call_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
