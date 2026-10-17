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
        required: bool = True,
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

        required defaults to true (this tool is for required unknowns). Pass
        required=false only for clearly optional fields (returns SKIP_OPTIONAL
        and does not write the KB). Returns ANSWER: … when known, GENERATE_OK: …
        / AUTO_FILL_OK: … when you should answer yourself (APPLY_AUTOFILL_REQUIRED
        or soft essays), or RECORDED_PENDING: … when autofill is off and the user
        must answer later — that means saved for offline fill; continue the form
        and keep collecting other unknowns (do not abort mid-form).
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
