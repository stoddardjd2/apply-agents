"""Agent prompts for form knowledge."""

from __future__ import annotations

from ..base import ApplyRunContext
from .service import (
    ai_may_answer_entries,
    answered_entries,
    autofill_required_enabled,
    pending_count,
)

SYSTEM_INSTRUCTIONS_DEFAULT = """
- OPTIONAL FIELDS: Do NOT fill fields that are not required (no asterisk /
  "required" marker / HTML required), EXCEPT items listed under ALWAYS FILL
  in the task — fill those from PROFILE even when optional. Leave other
  optionals blank. Do NOT call resolve_form_question for optional unknowns.
  Do NOT ask the user, stop, or add a Blocked line for optional blanks —
  skip and continue. Only required fields may block the apply.
- FORM KNOWLEDGE: answer from PROFILE and the FORM KNOWLEDGE answered list in
  the task whenever possible — do that yourself without any tool call. Only call
  resolve_form_question for REQUIRED screening/custom questions not covered by
  PROFILE/KB (e.g. clearance, salary band not in profile, employer-specific
  yes/no). required defaults to true — only pass required=false for clearly
  optional fields. Never record routine fields (name, email, phone, resume,
  EEO, relatives / family-at-company) that the profile already has — empty
  profile.relatives means No / None / N/A, never ask the user. Soft free-text prompts (mission/values
  alignment, why interested in the company/role, cover-letter style, "in your
  own words") are non-critical: the tool returns GENERATE_OK for those — always
  write a short human-voice answer from PROFILE + job/company context and
  continue. Never Blocked / ask the user for those. If the tool returns ANSWER:,
  use that value. If GENERATE_OK (or the prompt lists the question under AI may
  generate), write a short human-voice answer from PROFILE + job context — do
  not invent clearance, salary, legal, or medical facts. If SKIP_OPTIONAL, leave
  blank and continue. If RECORDED_PENDING and the field is required, do NOT
  stop mid-form: leave blank if the UI allows, else fill a temporary hire-safe
  value so Continue/Next works, and keep collecting other required unknowns.
  Only when the final Submit/Apply button is visible and any required pending
  remains: do not click Submit, do not engage captcha, and report once with
  **Application submitted:** No plus one **Blocked:** listing all pending
  ids/questions from this run. Never treat optional blanks or soft
  mission/values essays as pending/needs-human. Never invent clearance,
  salary, legal, or medical answers not in profile or FORM KNOWLEDGE unless
  GENERATE_OK explicitly allows a safe write.
""".strip()

SYSTEM_INSTRUCTIONS_AUTOFILL = """
- OPTIONAL FIELDS: Do NOT fill fields that are not required (no asterisk /
  "required" marker / HTML required), EXCEPT ALWAYS FILL items from the task
  (fill those from PROFILE). Leave other optionals blank. Do NOT call
  resolve_form_question for optional unknowns. Never ask the user about
  optional blanks — skip and continue.
- AUTOFILL REQUIRED (APPLY_AUTOFILL_REQUIRED=1): Fill EVERY required field
  yourself. Never ask for help, clarify with the user, stop for pending KB
  answers, or write a **Blocked:** line for unanswered screening questions.
  Answer from PROFILE first; for gaps use best judgment that does not hurt
  hire chances and stays consistent with PROFILE (e.g. No on exclusions /
  debarment / license discipline / criminal when PROFILE has no contrary fact;
  Yes on willingness / auth / background-check consent when PROFILE supports
  it; truthful work-authorization and sponsorship from PROFILE only). Soft
  essays: short human voice from PROFILE + job context. If resolve_form_question
  returns ANSWER:, AUTO_FILL_OK, or GENERATE_OK — answer and continue. Never
  invent clearance, SSN, medical diagnoses, or sponsorship needs absent from
  PROFILE.
""".strip()

# Back-compat for imports that expect a string constant.
SYSTEM_INSTRUCTIONS = SYSTEM_INSTRUCTIONS_DEFAULT


def system_instructions(_ctx: ApplyRunContext) -> str:
    if autofill_required_enabled():
        return SYSTEM_INSTRUCTIONS_AUTOFILL
    return SYSTEM_INSTRUCTIONS_DEFAULT


def user_prompt_block(ctx: ApplyRunContext) -> str:
    answered = answered_entries()
    ai_ok = ai_may_answer_entries()
    pending = pending_count()
    autofill = autofill_required_enabled()
    always = [str(k).strip() for k in (ctx.always_fill_fields or []) if str(k or "").strip()]
    always_line = (
        (
            "ALWAYS FILL even if optional (apply.config always_fill_fields): "
            + ", ".join(always)
            + ". Use PROFILE values; skip only if that PROFILE value is empty."
        )
        if always
        else ""
    )

    if autofill:
        lines = [
            "AUTOFILL REQUIRED is ON (APPLY_AUTOFILL_REQUIRED=1): fill every "
            "required field yourself from PROFILE + best hire-safe judgment. "
            "Never Blocked / ask / clarify / wait for form_knowledge.json.",
        ]
        if always_line:
            lines.append(always_line)
        if answered:
            lines.append(
                "FORM KNOWLEDGE (answered — prefer these when they match):"
            )
            for entry in answered:
                q = str(entry.get("question") or "").strip()
                a = entry.get("answer")
                if isinstance(a, bool):
                    a = "Yes" if a else "No"
                lines.append(f"- Q: {q}\n  A: {a}")
        lines.append(
            "Call resolve_form_question only if helpful; treat AUTO_FILL_OK / "
            "GENERATE_OK as permission to answer immediately and continue."
        )
        return "\n".join(lines)

    if not answered and not ai_ok and pending == 0:
        base = (
            "FORM KNOWLEDGE: empty. Answer from PROFILE first. Only call "
            "resolve_form_question for unknown screening questions you cannot "
            "answer safely from the profile."
        )
        return f"{always_line}\n{base}" if always_line else base

    lines: list[str] = []
    if always_line:
        lines.append(always_line)
    lines.append(
        "FORM KNOWLEDGE (answered — use these before calling resolve_form_question):"
    )
    if answered:
        for entry in answered:
            q = str(entry.get("question") or "").strip()
            a = entry.get("answer")
            if isinstance(a, bool):
                a = "Yes" if a else "No"
            lines.append(f"- Q: {q}\n  A: {a}")
    else:
        lines.append("- (no answered entries yet)")
    if ai_ok:
        lines.append(
            "FORM KNOWLEDGE (AI may generate — write a short human-voice answer "
            "from PROFILE + job context; do not invent clearance/salary/legal/"
            "medical facts):"
        )
        for entry in ai_ok:
            q = str(entry.get("question") or "").strip()
            lines.append(f"- Q: {q}")
    if pending:
        lines.append(
            f"({pending} pending entry/entries in form_knowledge.json — "
            "fill their answer fields offline, or set ai_may_answer=true. "
            "Continue through the form to the final Submit/Apply; if any "
            "required pending remains, stop without clicking Submit/captcha "
            "and report one **Blocked:** with all pendings.)"
        )
    lines.append(
        "Answer from PROFILE + the list above yourself whenever possible. "
        "Call resolve_form_question only when still unknown."
    )
    return "\n".join(lines)
