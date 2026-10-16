"""Agents SDK tool for resolve_form_question."""

from __future__ import annotations

from typing import Any

from agents import function_tool

from ..base import ApplyRunContext
from .service import form_knowledge_path, resolve_form_question

TOOL_NAME = "resolve_form_question"


def build_tools(ctx: ApplyRunContext) -> list[Any]:
    profile = ctx.profile or {}
    job_url = ctx.job_url
    kb_path = form_knowledge_path()

    @function_tool(name_override=TOOL_NAME)
    def resolve_form_question_tool(
        question: str,
        required: bool = False,
        options: list[str] | None = None,
        suggested_answer: str | None = None,
        company: str | None = None,
        field_label: str | None = None,
    ) -> str:
        """Resolve a REQUIRED form/screening question from KB or profile.

        Call ONLY for required fields when PROFILE and FORM KNOWLEDGE do not
        already cover the question. Do not call for optional fields — leave
        those blank. Prefer answering yourself from PROFILE/KB first — do not
        record routine name/email/phone fields.

        Set required=true only when the control is clearly required. Returns
        ANSWER: … when known, GENERATE_OK: … for soft essays (mission/values,
        why interested) or ai_may_answer=true, SKIP_OPTIONAL: … when not
        required (leave blank), or RECORDED_PENDING: … only for required
        factual unknowns (user must answer).
        """
        return resolve_form_question(
            question=question,
            required=required,
            options=options,
            suggested_answer=suggested_answer,
            company=company,
            field_label=field_label,
            job_url=job_url,
            profile=profile,
            path=kb_path,
        )

    return [resolve_form_question_tool]
