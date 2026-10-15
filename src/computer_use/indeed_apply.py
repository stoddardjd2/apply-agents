"""End-to-end Indeed Quick Apply flow via OpenAI Agents API computer use."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from .session import create_computer_use_session, run_computer_use_task

AGENT_INSTRUCTIONS = """
You are an automated QA agent testing Indeed Quick Apply in a real browser.

Rules:
- Work only on Indeed properties unless redirected by Indeed itself.
- Prefer Easy Apply / Quick Apply jobs that can be completed in-browser.
- Sign in when Indeed requires authentication.
- Fill application fields using obvious profile defaults already present in the
  account or sensible placeholder text only when a required field is empty.
- Never invent a fake SSN, government ID, or payment details.
- Be careful and deliberate: wait for pages to settle after navigation.
- Report clearly what happened at the end: job title, company, URL, and whether
  the application was submitted or stopped before submit.
""".strip()


def build_prompt(
    *,
    query: str,
    location: str,
    submit_application: bool,
    job_url: str | None,
) -> str:
    if job_url:
        start = f"Open this Indeed job URL: {job_url}"
    else:
        start = (
            f"Open https://www.indeed.com and search for '{query}' in '{location}'. "
            "Open a listing that supports Easy Apply / Quick Apply."
        )

    if submit_application:
        finish = (
            "Complete the Easy Apply / Quick Apply flow end to end and submit the "
            "application if the form can be completed with available account data. "
            "If a required field cannot be completed safely, stop and report why."
        )
    else:
        finish = (
            "Complete the Easy Apply / Quick Apply form until the final review / "
            "submit step, then STOP without clicking the final Submit / Apply button. "
            "Confirm that the form is ready to submit."
        )

    return (
        f"{start} Sign in if prompted. {finish} "
        "When finished, report: job title, company, job URL, steps completed, "
        "and whether the application was submitted."
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Indeed Quick Apply via OpenAI computer use")
    parser.add_argument("--query", default=os.getenv("INDEED_QUERY", "software engineer"))
    parser.add_argument("--location", default=os.getenv("INDEED_LOCATION", "Remote"))
    parser.add_argument("--job-url", default=os.getenv("INDEED_JOB_URL"))
    parser.add_argument(
        "--submit",
        action="store_true",
        default=os.getenv("SUBMIT_APPLICATION", "0") in {"1", "true", "TRUE", "yes", "YES"},
        help="Actually click the final Submit / Apply button",
    )
    parser.add_argument(
        "--keep-session",
        action="store_true",
        default=os.getenv("KEEP_SESSION", "0") in {"1", "true", "TRUE", "yes", "YES"},
    )
    parser.add_argument(
        "--artifacts",
        default="artifacts",
        help="Directory for screenshots and run output",
    )
    args = parser.parse_args(argv)

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is required. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 2

    if not os.getenv("INDEED_EMAIL") or not os.getenv("INDEED_PASSWORD"):
        print(
            "Warning: INDEED_EMAIL / INDEED_PASSWORD are not set. "
            "You will be prompted interactively if sign-in is required.",
            file=sys.stderr,
        )

    client = OpenAI()
    prompt = build_prompt(
        query=args.query,
        location=args.location,
        submit_application=args.submit,
        job_url=args.job_url,
    )

    print("Creating hosted computer-use session...", flush=True)
    session = create_computer_use_session(
        client,
        instructions=AGENT_INSTRUCTIONS,
        include_screenshots=True,
    )
    print(f"Session ID: {session.id}", flush=True)
    print(f"Submit enabled: {args.submit}", flush=True)

    result = run_computer_use_task(
        client,
        session,
        prompt,
        artifacts_dir=Path(args.artifacts),
        delete_on_success=not args.keep_session,
    )

    summary = "\n".join(result.output_text).strip()
    if summary:
        Path(args.artifacts).mkdir(parents=True, exist_ok=True)
        (Path(args.artifacts) / "result.txt").write_text(summary + "\n", encoding="utf-8")

    print("Completed successfully." if result.completed else "Did not complete.", flush=True)
    client.close()
    return 0 if result.completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
