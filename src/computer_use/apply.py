"""Apply to a configured job URL using a resume PDF via local Camoufox."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import DEFAULT_CONFIG_PATH, load_apply_config


def _resolve_model(model: str | None = None) -> str:
    resolved = (model or os.getenv("OPENAI_COMPUTER_USE_MODEL") or "").strip()
    if not resolved:
        raise ValueError(
            "Set OPENAI_COMPUTER_USE_MODEL in .env or pass --model (e.g. gpt-6-luna)."
        )
    return resolved


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Apply to a job URL from apply.config.json using a resume PDF"
    )
    parser.add_argument(
        "--config",
        default=os.getenv("APPLY_CONFIG", str(DEFAULT_CONFIG_PATH)),
        help="Path to apply.config.json (job_url + resume_path)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Overrides OPENAI_COMPUTER_USE_MODEL from .env",
    )
    parser.add_argument(
        "--job-url",
        default=None,
        help="Override job_url from config for this run",
    )
    parser.add_argument(
        "--resume",
        default=None,
        help="Override resume_path from config for this run",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Actually click the final Submit / Apply button (overrides config)",
    )
    parser.add_argument(
        "--costs",
        default=os.getenv("COSTS_PATH", "costs.json"),
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Open Camoufox once for Cloudflare + Google sign-in; saves cookies",
    )
    parser.add_argument(
        "--ensure-nopecha",
        action="store_true",
        help=(
            "Only download/cache the NopeCHA addon into .cache/nopecha "
            "(does not open the browser — the solver loads on a normal apply/login run)"
        ),
    )
    parser.add_argument(
        "--force-nopecha",
        action="store_true",
        help="With --ensure-nopecha, re-download even if the addon is already cached",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("BROWSER_PROFILE", ".camoufox-profile"),
        help="Persistent Camoufox profile directory",
    )
    args = parser.parse_args(argv)

    if args.ensure_nopecha:
        from .captcha.nopecha import ensure_nopecha_cached

        dest = ensure_nopecha_cached(force=args.force_nopecha)
        print(
            "NopeCHA is cached only — it is not running yet.\n"
            f"  Addon: {dest.resolve()}\n"
            "  It loads automatically on: python -m computer_use.apply\n"
            "  (or: python -m computer_use.apply --login)",
            flush=True,
        )
        return 0

    if args.login:
        from .browser import save_browser_login

        asyncio.run(save_browser_login(profile_dir=Path(args.profile)))
        return 0

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is required in .env", file=sys.stderr)
        return 2

    if args.job_url:
        os.environ["JOB_URL"] = args.job_url
    if args.resume:
        os.environ["RESUME_PATH"] = args.resume
    if args.submit:
        os.environ["SUBMIT_APPLICATION"] = "1"

    try:
        model = _resolve_model(args.model)
        config = load_apply_config(Path(args.config))
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.submit:
        from dataclasses import replace

        config = replace(config, submit=True)

    from .browser import run_local_apply

    return asyncio.run(
        run_local_apply(
            model=model,
            config=config,
            costs_path=args.costs,
            profile_dir=args.profile,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
