"""Compose enabled apply features for injection into the Agent."""

from __future__ import annotations

import os
from typing import Iterable

from .account_signup import AccountSignupFeature
from .base import ApplyFeature, ApplyRunContext, ComposedFeatures
from .form_knowledge import FormKnowledgeFeature
from .learnings import LearningsFeature
from .verification_code import VerificationCodeFeature

DEFAULT_FEATURES: tuple[ApplyFeature, ...] = (
    FormKnowledgeFeature,
    LearningsFeature,
    AccountSignupFeature,
    VerificationCodeFeature,
)


def disabled_feature_names() -> set[str]:
    """APPLY_DISABLE_FEATURES=form_knowledge,learnings — comma-separated names."""
    raw = os.getenv("APPLY_DISABLE_FEATURES", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def active_features(
    ctx: ApplyRunContext,
    features: Iterable[ApplyFeature] | None = None,
) -> list[ApplyFeature]:
    disabled = disabled_feature_names()
    out: list[ApplyFeature] = []
    for feat in features if features is not None else DEFAULT_FEATURES:
        if feat.name in disabled:
            continue
        if not feat.enabled(ctx):
            continue
        out.append(feat)
    return out


def compose(
    ctx: ApplyRunContext,
    features: Iterable[ApplyFeature] | None = None,
) -> ComposedFeatures:
    """Build tools + system/user prompt fragments from enabled features."""
    active = active_features(ctx, features)
    tools: list = []
    system_parts: list[str] = []
    user_blocks: list[str] = []
    names: list[str] = []
    for feat in active:
        names.append(feat.name)
        tools.extend(feat.tools(ctx) or [])
        sys_text = (feat.system_instructions(ctx) or "").strip()
        if sys_text:
            system_parts.append(sys_text)
        user_text = (feat.user_prompt_block(ctx) or "").strip()
        if user_text:
            user_blocks.append(user_text)
    return ComposedFeatures(
        names=tuple(names),
        tools=tools,
        system_instructions="\n\n".join(system_parts),
        user_blocks=tuple(user_blocks),
    )
