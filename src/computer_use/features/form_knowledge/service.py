"""Form knowledge service.

Owns the form_knowledge.json store and resolve logic: look up prior answers,
match the applicant profile, allow AI generation for soft essays, and record
required unknowns as pending entries for the human to fill later.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_KB_PATH = Path("form_knowledge.json")

# Free-text soft prompts the agent should write every time (non-critical).
_AI_SOFT_ESSAY_RE = re.compile(
    r"\b("
    r"why (are you|do you want|this (company|role|position|job|opportunity)|"
    r"join|work|apply)|"
    r"interested in|"
    r"mission|"
    r"values|"
    r"align(s|ed|ment)?|"
    r"motivation|"
    r"cover letter|"
    r"tell us about (yourself|you)|"
    r"what (excites|interests|motivates|draws) you|"
    r"in your own words|"
    r"personal and professional|"
    r"culture fit|"
    r"passion (for|about)|"
    r"how (would|do) you (describe|contribute)"
    r")\b",
    re.I,
)

# Never auto-generate these even if a soft keyword appears.
_AI_FACTUAL_BLOCK_RE = re.compile(
    r"\b("
    r"clearance|ts/?sci|secret clearance|"
    r"salary|compensation|expected pay|pay expectation|"
    r"ssn|social security|"
    r"visa|sponsorship|sponsor|"
    r"authorized to work|work authorization|citizenship|citizen|"
    r"disability|medical|accommodation|"
    r"criminal|conviction|felony|misdemeanor|"
    r"drug test|background check|"
    r"security clearance"
    r")\b",
    re.I,
)

# question-substring → profile key (checked after custom_answers / exact key match)
_PROFILE_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("email", "e-mail"), "email"),
    (("phone", "mobile", "telephone"), "phone"),
    (("first name", "given name"), "first_name"),
    (("last name", "surname", "family name"), "last_name"),
    (("full name", "legal name"), "full_name"),
    (("city",), "city"),
    (("state", "province"), "state"),
    (("zip", "postal code", "postcode"), "postal_code"),
    (("country",), "country"),
    (("linkedin",), "linkedin_url"),
    (("github",), "github_url"),
    (("website", "portfolio", "personal site"), "website_url"),
    (("years of experience", "years experience", "how many years"), "years_experience"),
    (("current title", "job title", "most recent title"), "current_title"),
    (("current company", "employer", "most recent company"), "current_company"),
    (("work authorization", "authorized to work", "legally authorized"), "work_authorization"),
    (("sponsorship", "visa sponsorship", "require sponsorship"), "require_sponsorship"),
    (("citizen", "permanent resident", "u.s. citizen"), "citizen_or_permanent_resident"),
    (("relocate", "willing to relocate"), "willing_to_relocate"),
    (("remote", "work from home"), "remote_preference"),
    (("start date", "earliest start", "available to start"), "earliest_start_date"),
    (("notice period", "notice"), "notice_period"),
    (("salary", "compensation", "pay expectation", "expected pay"), "salary_expectation_usd"),
    (("how did you hear", "how you heard", "referral source"), "how_heard"),
    (("cover letter",), "cover_letter"),
    (("timezone", "time zone"), "timezone"),
    (("over 18", "18 years"), "custom_answers.are_you_over_18"),
    (("background check",), "custom_answers.can_you_pass_background_check"),
    (("worked here before", "previously employed", "former employee"), "custom_answers.have_you_worked_here_before"),
    (("drug test",), "custom_answers.willing_to_take_drug_test"),
    (("async", "asynchronous"), "custom_answers.comfortable_with_async_remote"),
]


def form_knowledge_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    env = (os.getenv("FORM_KNOWLEDGE_PATH") or "").strip()
    return Path(env) if env else DEFAULT_KB_PATH


def normalize_question(text: str) -> str:
    s = (text or "").lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug_id(normalized: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")[:48] or "question"
    return base


def _answer_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    return bool(str(value).strip())


def _format_answer(value: Any, *, profile_key: str | None = None) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if profile_key == "salary_expectation_usd":
        try:
            amount = int(float(str(value).replace(",", "").replace("$", "").strip()))
            return f"${amount:,}"
        except (TypeError, ValueError):
            pass
    return str(value).strip()


def load_kb(path: Path | str | None = None) -> dict[str, Any]:
    kb_path = form_knowledge_path(path)
    if not kb_path.is_file():
        return {"version": 1, "entries": []}
    try:
        data = json.loads(kb_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "entries": []}
    if not isinstance(data, dict):
        return {"version": 1, "entries": []}
    entries = data.get("entries")
    if not isinstance(entries, list):
        entries = []
    return {"version": int(data.get("version") or 1), "entries": entries}


def save_kb(data: dict[str, Any], path: Path | str | None = None) -> Path:
    kb_path = form_knowledge_path(path)
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": int(data.get("version") or 1),
        "entries": list(data.get("entries") or []),
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    tmp = kb_path.with_suffix(kb_path.suffix + f".{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(kb_path)
    return kb_path


def is_ai_generatable_question(
    question: str,
    options: list[str] | None = None,
) -> bool:
    """True for soft free-text prompts (mission/values / why interested / etc.).

    Multiple-choice / Yes-No screens and factual topics stay human-pending.
    """
    opts = [str(o).strip() for o in (options or []) if str(o).strip()]
    if opts:
        return False
    key = normalize_question(question)
    if not key:
        return False
    if _AI_FACTUAL_BLOCK_RE.search(key):
        return False
    return bool(_AI_SOFT_ESSAY_RE.search(key))


def _ai_may_answer(entry: dict[str, Any]) -> bool:
    """True when the entry flag is set or the question matches soft-essay heuristics."""
    if bool(entry.get("ai_may_answer")):
        return True
    opts = entry.get("options")
    options = [str(o) for o in opts] if isinstance(opts, list) else None
    return is_ai_generatable_question(str(entry.get("question") or ""), options)


def answered_entries(path: Path | str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in load_kb(path).get("entries") or []:
        if isinstance(entry, dict) and _answer_nonempty(entry.get("answer")):
            out.append(entry)
    return out


def ai_may_answer_entries(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Pending entries the agent may generate (flag or soft-essay heuristic)."""
    out: list[dict[str, Any]] = []
    for entry in load_kb(path).get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if _answer_nonempty(entry.get("answer")):
            continue
        if _ai_may_answer(entry):
            out.append(entry)
    return out


def pending_count(path: Path | str | None = None) -> int:
    """Entries waiting for a human-filled answer (not AI-generatable)."""
    n = 0
    for entry in load_kb(path).get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if _answer_nonempty(entry.get("answer")):
            continue
        if _ai_may_answer(entry):
            continue
        n += 1
    return n


def lookup_entry(question: str, path: Path | str | None = None) -> dict[str, Any] | None:
    key = normalize_question(question)
    if not key:
        return None
    for entry in load_kb(path).get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if normalize_question(str(entry.get("question") or "")) == key:
            return entry
    return None


def lookup_answer(question: str, path: Path | str | None = None) -> dict[str, Any] | None:
    entry = lookup_entry(question, path)
    if entry is not None and _answer_nonempty(entry.get("answer")):
        return entry
    return None


def _generate_ok_message(entry: dict[str, Any] | None = None) -> str:
    opts = None
    if entry is not None:
        raw = entry.get("options")
        if isinstance(raw, list) and raw:
            opts = [str(o) for o in raw if str(o).strip()]
    extra = f" Prefer one of: {', '.join(opts)}." if opts else ""
    return (
        "GENERATE_OK: You may write a short human-voice answer for this question "
        "using PROFILE, the job listing, and known facts. Do not invent clearance, "
        "salary, legal, medical, or SSN details."
        + extra
    )


def _profile_get(profile: dict[str, Any], dotted: str) -> Any:
    cur: Any = profile
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def answer_from_profile(question: str, profile: dict[str, Any] | None) -> str | None:
    """Best-effort answer from profile / custom_answers without writing to the KB."""
    if not profile:
        return None
    key = normalize_question(question)
    if not key:
        return None

    custom = profile.get("custom_answers")
    if isinstance(custom, dict):
        for ck, cv in custom.items():
            ck_norm = normalize_question(str(ck).replace("_", " "))
            if ck_norm and (ck_norm == key or ck_norm in key or key in ck_norm):
                if _answer_nonempty(cv):
                    return _format_answer(cv)

    # Exact / near-exact top-level keys mentioned in the question
    for pk, pv in profile.items():
        if pk == "custom_answers" or str(pk).startswith("_") or isinstance(pv, (dict, list)):
            continue
        pk_norm = normalize_question(str(pk).replace("_", " "))
        if pk_norm and pk_norm in key and _answer_nonempty(pv):
            return _format_answer(pv, profile_key=str(pk))

    for needles, dotted in _PROFILE_HINTS:
        if any(n in key for n in needles):
            val = _profile_get(profile, dotted)
            if _answer_nonempty(val):
                return _format_answer(val, profile_key=dotted)
    return None


def record_question(
    *,
    question: str,
    required: bool = False,
    options: list[str] | None = None,
    suggested_answer: str | None = None,
    company: str | None = None,
    field_label: str | None = None,
    job_url: str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Upsert a pending (or already-answered) entry. Never wipes an existing answer."""
    q = (question or "").strip()
    if not q:
        return {
            "status": "error",
            "id": None,
            "answer": None,
            "message": "question is empty",
        }

    key = normalize_question(q)
    kb = load_kb(path)
    entries: list[Any] = list(kb.get("entries") or [])
    now = _utc_now()
    opts = [str(o) for o in (options or []) if str(o).strip()] or None

    existing: dict[str, Any] | None = None
    existing_idx: int | None = None
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        if normalize_question(str(entry.get("question") or "")) == key:
            existing = entry
            existing_idx = i
            break

    if existing is not None and existing_idx is not None:
        entry = dict(existing)
        entry["question"] = q
        entry["required"] = bool(required) if required else bool(entry.get("required"))
        if opts is not None:
            entry["options"] = opts
        if suggested_answer is not None and str(suggested_answer).strip():
            # Keep suggestion for the user; do not overwrite a real answer.
            if not _answer_nonempty(entry.get("answer")):
                entry["suggested_answer"] = str(suggested_answer).strip()
        if company and str(company).strip():
            entry["company"] = str(company).strip()
        if field_label and str(field_label).strip():
            entry["field_label"] = str(field_label).strip()
        if job_url and str(job_url).strip():
            entry["job_url"] = str(job_url).strip()
        # Soft-essay heuristics (or an existing true flag) mark AI-writable.
        entry["ai_may_answer"] = bool(entry.get("ai_may_answer")) or is_ai_generatable_question(
            q, opts if opts is not None else entry.get("options")
        )
        entry["updated_at"] = now
        entries[existing_idx] = entry
        kb["entries"] = entries
        save_kb(kb, path)
        if _answer_nonempty(entry.get("answer")):
            return {
                "status": "answered",
                "id": entry.get("id"),
                "answer": _format_answer(entry.get("answer")),
                "message": f"ANSWER: {_format_answer(entry.get('answer'))}",
            }
        if _ai_may_answer(entry):
            return {
                "status": "generate_ok",
                "id": entry.get("id"),
                "answer": None,
                "message": _generate_ok_message(entry),
            }
        return {
            "status": "pending",
            "id": entry.get("id"),
            "answer": None,
            "message": (
                f"RECORDED_PENDING: already tracked as id={entry.get('id')}. "
                f"Fill form_knowledge.json answer for id={entry.get('id')}, "
                f"or set ai_may_answer=true to let the agent write it."
            ),
        }

    entry_id = _slug_id(key)
    # Avoid id collisions with different wording
    used = {str(e.get("id")) for e in entries if isinstance(e, dict)}
    if entry_id in used:
        entry_id = f"{entry_id}_{uuid.uuid4().hex[:6]}"

    ai_ok = is_ai_generatable_question(q, opts)
    entry = {
        "id": entry_id,
        "question": q,
        "required": bool(required),
        "options": opts,
        "suggested_answer": (
            str(suggested_answer).strip()
            if suggested_answer is not None and str(suggested_answer).strip()
            else None
        ),
        "answer": None,
        "ai_may_answer": ai_ok,
        "job_url": str(job_url).strip() if job_url and str(job_url).strip() else None,
        "company": str(company).strip() if company and str(company).strip() else None,
        "field_label": (
            str(field_label).strip() if field_label and str(field_label).strip() else None
        ),
        "updated_at": now,
    }
    entries.append(entry)
    kb["entries"] = entries
    save_kb(kb, path)
    if ai_ok:
        return {
            "status": "generate_ok",
            "id": entry_id,
            "answer": None,
            "message": _generate_ok_message(entry),
        }
    return {
        "status": "pending",
        "id": entry_id,
        "answer": None,
        "message": (
            f"RECORDED_PENDING: saved id={entry_id}. "
            f"Fill form_knowledge.json answer for id={entry_id}, "
            f"or set ai_may_answer=true to let the agent write it."
            + (" Required — stop and report if you cannot proceed." if required else
               " Optional — leave blank / skip if appropriate.")
        ),
    }


def resolve_form_question(
    *,
    question: str,
    required: bool = False,
    options: list[str] | None = None,
    suggested_answer: str | None = None,
    company: str | None = None,
    field_label: str | None = None,
    job_url: str | None = None,
    profile: dict[str, Any] | None = None,
    path: Path | str | None = None,
) -> str:
    """Lookup KB → profile → AI permission → only then record pending."""
    hit = lookup_answer(question, path)
    if hit is not None:
        return f"ANSWER: {_format_answer(hit.get('answer'))}"

    from_profile = answer_from_profile(question, profile)
    if from_profile is not None:
        return (
            f"ANSWER: {from_profile} "
            "(from applicant profile — use this; do not record as pending)"
        )

    existing = lookup_entry(question, path)
    if existing is not None and _ai_may_answer(existing):
        # Persist soft-essay auto-flag so the prompt lists it under AI may generate.
        if not bool(existing.get("ai_may_answer")) and is_ai_generatable_question(
            question, options if options is not None else existing.get("options")
        ):
            record_question(
                question=question,
                required=required or bool(existing.get("required")),
                options=options,
                suggested_answer=suggested_answer,
                company=company,
                field_label=field_label,
                job_url=job_url,
                path=path,
            )
        return _generate_ok_message(existing)

    # Soft free-text (mission/values / why interested): generate — do not pending.
    if is_ai_generatable_question(question, options):
        result = record_question(
            question=question,
            required=required,
            options=options,
            suggested_answer=suggested_answer,
            company=company,
            field_label=field_label,
            job_url=job_url,
            path=path,
        )
        return str(result.get("message") or _generate_ok_message())

    # Optional unknowns: never ask the user / never create a pending KB entry.
    if not required:
        return (
            "SKIP_OPTIONAL: field is not required — leave blank and continue. "
            "Do not ask the user and do not record this as pending."
        )

    result = record_question(
        question=question,
        required=required,
        options=options,
        suggested_answer=suggested_answer,
        company=company,
        field_label=field_label,
        job_url=job_url,
        path=path,
    )
    return str(result.get("message") or "RECORDED_PENDING")
