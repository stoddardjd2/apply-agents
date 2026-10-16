"""Mimic `python -m computer_use.apply` for investigation (full real path).

Uses the same entrypoint as production: computer_use.apply.main().
Extra: prints full tracebacks if Agents SDK only logs 'Error getting response'.

Examples:
  .\\.venv\\Scripts\\python scripts\\investigate\\run_apply_like.py
  .\\.venv\\Scripts\\python scripts\\investigate\\run_apply_like.py --job-url https://www.glassdoor.com/job-listing/j?jl=1010290518631
  .\\.venv\\Scripts\\python scripts\\investigate\\run_apply_like.py --attempts 3
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Wrapper around computer_use.apply.main for investigation",
        add_help=False,
    )
    parser.add_argument("--attempts", type=int, default=1)
    # Everything else is forwarded to apply.main (same CLI as python -m computer_use.apply).
    args, forward = parser.parse_known_args()

    from computer_use.apply import main as apply_main

    print(f"mimic: python -m computer_use.apply {' '.join(forward)}", flush=True)
    print(f"attempts={args.attempts}", flush=True)

    codes: list[int] = []
    for i in range(1, args.attempts + 1):
        print(f"\n######## apply attempt {i}/{args.attempts} ########", flush=True)
        try:
            code = apply_main(forward)
        except Exception as exc:
            print(f"UNCAUGHT {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc()
            code = 99
        codes.append(code)
        print(f"######## attempt {i} exit={code} ########\n", flush=True)

    fails = sum(1 for c in codes if c != 0)
    print(f"SUMMARY exits={codes} fails={fails}/{len(codes)}", flush=True)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
