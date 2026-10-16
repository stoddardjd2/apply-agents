"""Agent prompts for form knowledge."""

from __future__ import annotations

from ..base import ApplyRunContext
from .service import ai_may_answer_entries, answered_entries, pending_count

SYSTEM_INSTRUCTIONS = """
- OPTIONAL FIELDS: Do NOT fill fields that are not required (no asterisk /
  "required" marker / HTML required). Leave them blank. Do NOT call
  resolve_form_question for optional unknowns. Do NOT ask the user, stop, or
  add a Blocked line for optional blanks — skip and continue. Only required
  fields may block the apply.
- FORM KNOWLEDGE: answer from PROFILE and the FORM KNOWLEDGE answered list in
  the task whenever possible — do that yourself without any tool call. Only call
  resolve_form_question for REQUIRED screening/custom questions not covered by
  PROFILE/KB (e.g. clearance, salary band not in profile, employer-specific
  yes/no). Pass required=true only when the field is clearly required. Never
  record routine fields (name, email, phone, resume, EEO) that the profile
  already has. Soft free-text prompts (mission/values alignment, why interested
  in the company/role, cover-letter style, "in your own words") are non-critical:
  the tool returns GENERATE_OK for those — always write a short human-voice
  answer from PROFILE + job/company context and continue. Never Blocked / ask
  the user for those. If the tool returns ANSWER:, use that value. If
  GENERATE_OK (or the prompt lists the question under AI may generate), write a
  short human-voice answer from PROFILE + job context — do not invent clearance,
  salary, legal, or medical facts. If SKIP_OPTIONAL, leave blank and continue.
  If RECORDED_PENDING and the field is required, stop and report; never treat
  optional blanks or soft mission/values essays as pending/needs-human. Never
  invent clearance, salary, legal, or medical answers not in profile or FORM
  KNOWLEDGE unless GENERATE_OK explicitly allows a safe write.
""".strip()


def user_prompt_block(_ctx: ApplyRunContext) -> str:
    answered = answered_entries()
    ai_ok = ai_may_answer_entries()
    pending = pending_count()
    if not answered and not ai_ok and pending == 0:
        return (
            "FORM KNOWLEDGE: empty. Answer from PROFILE first. Only call "
            "resolve_form_question for unknown screening questions you cannot "
            "answer safely from the profile."
        )
    lines = [
        "FORM KNOWLEDGE (answered — use these before calling resolve_form_question):"
    ]
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
            "fill their answer fields offline, or set ai_may_answer=true.)"
        )
    lines.append(
        "Answer from PROFILE + the list above yourself whenever possible. "
        "Call resolve_form_question only when still unknown."
    )
    return "\n".join(lines)
