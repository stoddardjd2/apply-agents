"""Apply feature protocol — each feature package owns tools + prompts (+ optional service)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from computer_use.landed.client import LandedClient

# Landed step callback: (status, detail) -> None
VerificationStepCallback = Callable[[str, dict[str, Any]], None]

ToolsBuilder = Callable[["ApplyRunContext"], list[Any]]
PromptText = str | Callable[["ApplyRunContext"], str]
EnabledGate = Callable[["ApplyRunContext"], bool]


@dataclass
class ApplyRunContext:
    """Everything a feature needs to decide enablement and build tools/prompts."""

    job_url: str
    profile: dict[str, Any] = field(default_factory=dict)
    company: str | None = None
    account_signup: dict[str, Any] | None = None
    submit: bool = False
    resume_path: str = ""
    landed_client: LandedClient | None = None
    application_id: str | None = None
    # Set by the harness when Landed verification polling is wired.
    verification_since: str | None = None
    on_verification_step: VerificationStepCallback | None = None
    # Set by the harness once Camoufox is up (pre_submit_screenshot tool).
    browser_computer: Any | None = None


@dataclass(frozen=True)
class ComposedFeatures:
    """Injected into Agent instructions / tools / user task prompt."""

    names: tuple[str, ...]
    tools: list[Any]
    system_instructions: str
    user_blocks: tuple[str, ...]


class ApplyFeature(Protocol):
    """Capability unit: tool name(s) + system text + user block + enable gate."""

    name: str

    def enabled(self, ctx: ApplyRunContext) -> bool: ...

    def tools(self, ctx: ApplyRunContext) -> list[Any]: ...

    def system_instructions(self, ctx: ApplyRunContext) -> str: ...

    def user_prompt_block(self, ctx: ApplyRunContext) -> str: ...


def _resolve_prompt(value: PromptText, ctx: ApplyRunContext) -> str:
    if callable(value):
        return str(value(ctx) or "")
    return str(value or "")


@dataclass(frozen=True)
class DefinedFeature:
    """Declarative feature produced by ``define_feature``."""

    name: str
    _tools: ToolsBuilder | None = None
    _system: PromptText = ""
    _user: PromptText = ""
    _enabled: EnabledGate | None = None

    def enabled(self, ctx: ApplyRunContext) -> bool:
        if self._enabled is None:
            return True
        return bool(self._enabled(ctx))

    def tools(self, ctx: ApplyRunContext) -> list[Any]:
        if self._tools is None:
            return []
        return list(self._tools(ctx) or [])

    def system_instructions(self, ctx: ApplyRunContext) -> str:
        return _resolve_prompt(self._system, ctx)

    def user_prompt_block(self, ctx: ApplyRunContext) -> str:
        return _resolve_prompt(self._user, ctx)


def define_feature(
    name: str,
    *,
    tools: ToolsBuilder | None = None,
    system: PromptText = "",
    user: PromptText = "",
    enabled: EnabledGate | None = None,
) -> DefinedFeature:
    """Declare a feature by wiring name + tools/prompts (and optional enable gate).

    ``system`` / ``user`` may be a plain string or ``(ctx) -> str``.
    ``tools`` is ``(ctx) -> list`` (Agents SDK function tools). Omit for prompt-only.
    """
    return DefinedFeature(
        name=name,
        _tools=tools,
        _system=system,
        _user=user,
        _enabled=enabled,
    )


class FeatureBase:
    """Optional base with empty tools / prompts for subclass-style features."""

    name: str = ""

    def enabled(self, ctx: ApplyRunContext) -> bool:
        return True

    def tools(self, ctx: ApplyRunContext) -> list[Any]:
        return []

    def system_instructions(self, ctx: ApplyRunContext) -> str:
        return ""

    def user_prompt_block(self, ctx: ApplyRunContext) -> str:
        return ""
