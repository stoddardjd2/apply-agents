"""Form knowledge feature."""

from __future__ import annotations

from ..base import define_feature
from .prompts import SYSTEM_INSTRUCTIONS, user_prompt_block
from .service import (
    ai_may_answer_entries,
    answer_from_profile,
    answered_entries,
    form_knowledge_path,
    is_ai_generatable_question,
    lookup_answer,
    normalize_question,
    pending_count,
    record_question,
    resolve_form_question,
)
from .tool import TOOL_NAME, build_tools

FormKnowledgeFeature = define_feature(
    "form_knowledge",
    tools=build_tools,
    system=SYSTEM_INSTRUCTIONS,
    user=user_prompt_block,
)

__all__ = [
    "TOOL_NAME",
    "FormKnowledgeFeature",
    "ai_may_answer_entries",
    "answer_from_profile",
    "answered_entries",
    "form_knowledge_path",
    "is_ai_generatable_question",
    "lookup_answer",
    "normalize_question",
    "pending_count",
    "record_question",
    "resolve_form_question",
]
