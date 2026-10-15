"""Indeed Quick Apply computer-use smoke / e2e tests."""

from __future__ import annotations

import os

import pytest

from computer_use.indeed_apply import build_prompt, main
from computer_use.session import create_computer_use_session, run_computer_use_task


def test_build_prompt_dry_run_stops_before_submit() -> None:
    prompt = build_prompt(
        query="software engineer",
        location="Remote",
        submit_application=False,
        job_url=None,
    )
    assert "Easy Apply" in prompt or "Quick Apply" in prompt
    assert "STOP without clicking the final Submit" in prompt


def test_build_prompt_submit_mode() -> None:
    prompt = build_prompt(
        query="qa",
        location="Austin, TX",
        submit_application=True,
        job_url="https://www.indeed.com/viewjob?jk=example",
    )
    assert "https://www.indeed.com/viewjob?jk=example" in prompt
    assert "submit the application" in prompt.lower()


@pytest.mark.skipif(
    os.getenv("RUN_INDEED_E2E") != "1",
    reason="Set RUN_INDEED_E2E=1 with OPENAI_API_KEY and Indeed credentials to run live e2e",
)
def test_indeed_quick_apply_e2e(tmp_path) -> None:
    assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY required for e2e"
    from openai import OpenAI
    from computer_use.indeed_apply import AGENT_INSTRUCTIONS

    client = OpenAI()
    session = create_computer_use_session(
        client,
        instructions=AGENT_INSTRUCTIONS,
        include_screenshots=True,
    )
    prompt = build_prompt(
        query=os.getenv("INDEED_QUERY", "software engineer"),
        location=os.getenv("INDEED_LOCATION", "Remote"),
        submit_application=os.getenv("SUBMIT_APPLICATION", "0")
        in {"1", "true", "TRUE", "yes", "YES"},
        job_url=os.getenv("INDEED_JOB_URL"),
    )
    result = run_computer_use_task(
        client,
        session,
        prompt,
        artifacts_dir=tmp_path,
        delete_on_success=os.getenv("KEEP_SESSION", "0")
        not in {"1", "true", "TRUE", "yes", "YES"},
    )
    client.close()

    assert result.completed
    joined = "\n".join(result.output_text).lower()
    assert "indeed" in joined or "apply" in joined or "job" in joined


@pytest.mark.skipif(
    os.getenv("RUN_INDEED_E2E") != "1",
    reason="Set RUN_INDEED_E2E=1 to exercise the CLI entrypoint live",
)
def test_cli_entrypoint_live() -> None:
    code = main([])
    assert code == 0
