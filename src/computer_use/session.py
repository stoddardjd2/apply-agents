"""OpenAI Agents API computer-use session helpers."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai import OpenAI

from .approvals import respond_to_computer_use_approval


DEFAULT_MODEL = "gpt-6-astra"


@dataclass
class SessionResult:
    session_id: str
    completed: bool
    output_text: list[str] = field(default_factory=list)
    last_screenshot: bytes | None = None
    error: str | None = None


def create_computer_use_session(
    client: OpenAI,
    *,
    instructions: str,
    model: str | None = None,
    include_screenshots: bool = True,
) -> Any:
    return client.beta.agents.sessions.create(
        agent={
            "model": model or os.getenv("OPENAI_COMPUTER_USE_MODEL", DEFAULT_MODEL),
            "instructions": instructions,
            "tools": [{"type": "computer_use", "include_screenshots": include_screenshots}],
        },
        environment={
            "type": "openai_hosted",
            "desktop": {"enabled": True},
            "network": {"access": "enabled"},
        },
    )


def run_computer_use_task(
    client: OpenAI,
    session: Any,
    prompt: str,
    *,
    artifacts_dir: Path | None = None,
    delete_on_success: bool = True,
) -> SessionResult:
    """Stream a computer-use task until the main agent turn completes."""
    handled_requests: set[str] = set()
    completed = False
    output_text: list[str] = []
    last_screenshot: bytes | None = None
    error: str | None = None
    ready_to_delete = False

    try:
        with client.beta.agents.sessions.events.stream(session.id) as events:
            client.beta.agents.sessions.events.create(
                session.id,
                events=[
                    {
                        "type": "agent.session.input.message",
                        "input": [
                            {
                                "role": "user",
                                "content": [{"type": "input_text", "text": prompt}],
                            }
                        ],
                    }
                ],
            )

            for event in events:
                event_type = getattr(event, "type", None)

                if event_type == "agent.session.requires_action":
                    current = client.beta.agents.sessions.retrieve(session.id)
                    for approval in current.required_actions or []:
                        if (
                            getattr(approval, "type", None) == "computer_use_approval_request"
                            and approval.request_id not in handled_requests
                        ):
                            respond_to_computer_use_approval(client, session.id, approval)
                            handled_requests.add(approval.request_id)

                elif event_type == "agent.session.turn.item.done":
                    item = getattr(event, "item", None)
                    if item is not None and getattr(item, "type", None) == "computer_use_call":
                        output = getattr(item, "output", None)
                        if output is not None and getattr(output, "type", None) == "computer_screenshot":
                            image_url = getattr(output, "image_url", "") or ""
                            prefix = "data:image/jpeg;base64,"
                            if image_url.startswith(prefix):
                                last_screenshot = base64.b64decode(
                                    image_url[len(prefix) :], validate=True
                                )

                elif event_type == "agent.session.turn.output_text.done":
                    text = getattr(event, "text", "") or ""
                    if text:
                        print(text, flush=True)
                        output_text.append(text)

                elif event_type == "agent.session.turn.completed":
                    turn = getattr(event, "turn", None)
                    if turn is not None and getattr(turn, "subagent_id", None) is None:
                        completed = True
                        break

                elif event_type in {
                    "agent.session.turn.failed",
                    "agent.session.turn.cancelled",
                }:
                    turn = getattr(event, "turn", None)
                    if turn is not None and getattr(turn, "subagent_id", None) is None:
                        error = f"Browser task ended: {event_type}"
                        raise RuntimeError(error)

                elif event_type == "error":
                    message = getattr(getattr(event, "error", None), "message", "Unknown error")
                    error = str(message)
                    raise RuntimeError(error)

                elif event_type in {
                    "agent.session.failed",
                    "agent.session.environment.failed",
                }:
                    error = f"Session failed: {event_type}"
                    raise RuntimeError(error)
            else:
                error = "Stream closed before the browser task finished."
                raise RuntimeError(error)

        ready_to_delete = completed and delete_on_success
    except (Exception, KeyboardInterrupt):
        print(
            f"Session {session.id} was kept. Retrieve it before retrying.",
            flush=True,
        )
        raise
    finally:
        if artifacts_dir is not None and last_screenshot is not None:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            screenshot_path = artifacts_dir / "last-screenshot.jpg"
            screenshot_path.write_bytes(last_screenshot)
            print(f"Saved screenshot: {screenshot_path}", flush=True)

        if ready_to_delete:
            client.beta.agents.sessions.delete(session.id)

    return SessionResult(
        session_id=session.id,
        completed=completed,
        output_text=output_text,
        last_screenshot=last_screenshot,
        error=error,
    )
