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

# Short keys that appear inside unrelated wording (e.g. "state" in "state healthcare").
# These must match as field phrasing, never as bare substrings.
_AMBIGUOUS_PROFILE_KEYS = frozenset(
    {
        "state",
        "city",
        "country",
        "remote",
        "notice",
        "address",
        "summary",
        "headline",
        "open to",
        "skills",
    }
)

# question-substring → profile key (checked after custom_answers / exact key match)
_PROFILE_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("email", "e-mail"), "email"),
    (("phone", "mobile", "telephone"), "phone"),
    (("first name", "given name"), "first_name"),
    (("last name", "surname", "family name"), "last_name"),
    (("full name", "legal name"), "full_name"),
    (
        (
            "your city",
            "what city",
            "which city",
            "city of residence",
            "current city",
            "home city",
        ),
        "city",
    ),
    (
        (
            "your state",
            "what state",
            "which state",
            "state of residence",
            "state province",
            "state/province",
            "home state",
        ),
        "state",
    ),
    (("zip", "postal code", "postcode"), "postal_code"),
    (
        (
            "your country",
            "what country",
            "which country",
            "country of residence",
            "home country",
        ),
        "country",
    ),
    (("linkedin",), "linkedin_url"),
    (("github",), "github_url"),
    (("website", "portfolio", "personal site"), "website_url"),
    (("years of experience", "years experience", "how many years"), "years_experience"),
    (("current title", "job title", "most recent title"), "current_title"),
    (("current company", "most recent company"), "current_company"),
    (("work authorization", "authorized to work", "legally authorized"), "work_authorization"),
    (("sponsorship", "visa sponsorship", "require sponsorship"), "require_sponsorship"),
    (("citizen", "permanent resident", "u.s. citizen"), "citizen_or_permanent_resident"),
    (("relocate", "willing to relocate"), "willing_to_relocate"),
    (("work from home", "remote preference", "remote or hybrid"), "remote_preference"),
    (("start date", "earliest start", "available to start"), "earliest_start_date"),
    (("notice period",), "notice_period"),
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


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def autofill_required_enabled() -> bool:
    """APPLY_AUTOFILL_REQUIRED — fill every required field without asking the user."""
    return _env_bool("APPLY_AUTOFILL_REQUIRED", False)


def _pending_continue_guidance(*, required: bool) -> str:
    """Instruct the agent to keep collecting gaps until final Submit."""
    if not required:
        return "Optional — leave blank / skip if appropriate."
    return (
        "Required — do not stop now. Leave blank if the UI allows; otherwise "
        "fill a temporary hire-safe value so Continue/Next works (KB answer "
        "stays null for the user). Keep resolving other required unknowns. "
        "Only when the final Submit/Apply button is visible: do not click it "
        "and do not engage captcha if any required pending remains; then "
        "report **Application submitted:** No with one **Blocked:** listing "
        "all pending ids/questions from this run."
    )


def _autofill_ok_message(entry: dict[str, Any] | None = None) -> str:
    opts = None
    if entry is not None:
        raw = entry.get("options")
        if isinstance(raw, list) and raw:
            opts = [str(o) for o in raw if str(o).strip()]
    extra = f" Prefer one of: {', '.join(opts)}." if opts else ""
    return (
        "AUTO_FILL_OK: Autofill mode is on — answer this required question yourself "
        "now using PROFILE + best judgment. Never stop, ask the user, clarify, or "
        "write Blocked/needs-human. Choose the option that does not hurt hire "
        "chances while staying consistent with PROFILE (e.g. No on exclusions/"
        "discipline/criminal when PROFILE has no contrary fact; Yes on willingness/"
        "relocation/auth when PROFILE supports it; truthful work-auth from PROFILE). "
        "Do not invent clearance, SSN, medical diagnoses, or sponsorship needs "
        "absent from PROFILE."
        + extra
    )


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


# Relatives / family-at-company (not "family name" = surname).
_RELATIVE_Q_RE = re.compile(
    r"\b("
    r"relative|relatives|family member|family members|"
    r"related to anyone|know anyone (who |that )?(works|employed|working)|"
    r"anyone.*(employ|works at|working at)|"
    r"immediate family|close (personal )?relationship|"
    r"spouse.*(work|employ)|family relationship|"
    r"friend or relative|friends or relatives"
    r")\b",
    re.I,
)
_FAMILY_NAME_RE = re.compile(r"\b(family name|surname|last name)\b", re.I)


def is_relatives_question(question: str) -> bool:
    """True for employer relative / family-relationship screens (not surname fields)."""
    q = (question or "").strip()
    if not q or _FAMILY_NAME_RE.search(q):
        return False
    return bool(_RELATIVE_Q_RE.search(q))


def relatives_entries(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalized list from profile.relatives; missing/empty → no relatives."""
    if not profile:
        return []
    raw = profile.get("relatives")
    if raw is None:
        return []
    if isinstance(raw, list):
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                out.append(item)
            elif str(item or "").strip():
                out.append({"name": str(item).strip()})
        return out
    if isinstance(raw, dict):
        # Allow {"none": true} or a single entry object.
        if raw.get("none") is True or raw.get("has_relatives") is False:
            return []
        entries = raw.get("entries")
        if isinstance(entries, list):
            return [e for e in entries if isinstance(e, dict)]
        if any(raw.get(k) for k in ("name", "relationship", "company", "title")):
            return [raw]
    return []


def format_relatives_answer(
    question: str,
    profile: dict[str, Any] | None,
    options: list[str] | None = None,
) -> str | None:
    """Answer a relatives question from profile.relatives (empty ⇒ No / None)."""
    if not is_relatives_question(question):
        return None
    entries = relatives_entries(profile)
    opts = [str(o).strip() for o in (options or []) if str(o).strip()]
    key = normalize_question(question)
    wants_details = bool(
        re.search(
            r"\b(list|name|names|who|provide|identify|describe|enter|specify|"
            r"details|relationship|which relative)\b",
            key,
        )
    )
    wants_yes_no = bool(opts) and all(
        (
            normalize_question(o) in {"yes", "no", "y", "n", "true", "false"}
            or normalize_question(o).startswith("yes ")
            or normalize_question(o).startswith("no ")
        )
        for o in opts
    )
    # Unlabeled boolean screens: "Do you have relatives…?" — not "List any…".
    if not opts and not wants_details and re.search(
        r"\b(do you|have you|are you|is there)\b", key
    ):
        wants_yes_no = True

    if not entries:
        if wants_yes_no or (opts and any(normalize_question(o) == "no" for o in opts)):
            candidate = "No"
        elif opts:
            for prefer in ("none", "n a", "na", "not applicable", "no"):
                for o in opts:
                    if normalize_question(o) == prefer or prefer in normalize_question(o):
                        return o
            return None
        else:
            candidate = "None"
        if _answer_fits_options(candidate, options):
            return candidate
        return candidate if not opts else None

    # Has relatives listed.
    if wants_yes_no and not wants_details:
        candidate = "Yes"
        if _answer_fits_options(candidate, options):
            return candidate
        return candidate if not opts else None

    parts: list[str] = []
    for e in entries:
        bits = [
            str(e.get(k) or "").strip()
            for k in ("name", "relationship", "company", "title")
            if str(e.get(k) or "").strip()
        ]
        if bits:
            parts.append(", ".join(bits))
    text = "; ".join(parts) if parts else "Yes"
    if _answer_fits_options(text, options):
        return text
    return text if not opts else None


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
    if autofill_required_enabled() and bool(entry.get("required", True)):
        return True
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


def _phrase_in_question(needle: str, key: str) -> bool:
    """True when needle appears as a whole phrase in the normalized question."""
    n = (needle or "").strip()
    if not n or not key:
        return False
    return bool(re.search(rf"(?:^|\s){re.escape(n)}(?:\s|$)", key))


def _profile_key_matches_question(pk_norm: str, key: str) -> bool:
    """Match profile field names to questions without false hits like state⊂state healthcare."""
    if not pk_norm or not key:
        return False
    if pk_norm == key:
        return True
    ambiguous = pk_norm in _AMBIGUOUS_PROFILE_KEYS or len(pk_norm) <= 5
    if ambiguous:
        # Field-oriented phrasing only — bare "state"/"city"/"country" is too common.
        patterns = (
            rf"(?:^|\s)(?:your|applicant.?s?|current|home|mailing)\s+{re.escape(pk_norm)}(?:\s|$)",
            rf"(?:^|\s)(?:what|which)\s+(?:is\s+)?(?:your\s+)?{re.escape(pk_norm)}(?:\s|$)",
            rf"(?:^|\s){re.escape(pk_norm)}\s+(?:of residence|province|region)(?:\s|$)",
            rf"(?:^|\s){re.escape(pk_norm)}\s*\??$",
        )
        return any(re.search(p, key) for p in patterns)
    return _phrase_in_question(pk_norm, key)


def _answer_fits_options(answer: str, options: list[str] | None) -> bool:
    """When the form exposes choices, profile hits must match one (case-insensitive)."""
    opts = [str(o).strip() for o in (options or []) if str(o).strip()]
    if not opts:
        return True
    a = answer.strip().lower()
    return any(a == o.lower() for o in opts)


def answer_from_profile(
    question: str,
    profile: dict[str, Any] | None,
    options: list[str] | None = None,
) -> str | None:
    """Best-effort answer from profile / custom_answers without writing to the KB."""
    # Relatives: empty/missing profile.relatives ⇒ No / None (even if profile is {}).
    relatives_hit = format_relatives_answer(question, profile, options)
    if relatives_hit is not None:
        return relatives_hit

    if not profile:
        return None
    key = normalize_question(question)
    if not key:
        return None

    def _accept(raw: Any, *, profile_key: str | None = None) -> str | None:
        if not _answer_nonempty(raw):
            return None
        formatted = _format_answer(raw, profile_key=profile_key)
        if not _answer_fits_options(formatted, options):
            return None
        return formatted

    custom = profile.get("custom_answers")
    if isinstance(custom, dict):
        for ck, cv in custom.items():
            ck_norm = normalize_question(str(ck).replace("_", " "))
            if not ck_norm:
                continue
            # Prefer exact / contained custom keys; avoid tiny accidental overlaps.
            if ck_norm == key or (
                len(ck_norm) >= 8 and (ck_norm in key or key in ck_norm)
            ):
                hit = _accept(cv)
                if hit is not None:
                    return hit

    # Exact / near-exact top-level keys mentioned in the question
    for pk, pv in profile.items():
        if pk in {"custom_answers", "relatives", "eeo"} or str(pk).startswith("_"):
            continue
        if isinstance(pv, (dict, list)):
            continue
        pk_norm = normalize_question(str(pk).replace("_", " "))
        if pk_norm and _profile_key_matches_question(pk_norm, key):
            hit = _accept(pv, profile_key=str(pk))
            if hit is not None:
                return hit

    for needles, dotted in _PROFILE_HINTS:
        if any(_phrase_in_question(n, key) or n in key for n in needles):
            # Ambiguous short needles already use long field phrases in _PROFILE_HINTS.
            val = _profile_get(profile, dotted)
            hit = _accept(val, profile_key=dotted)
            if hit is not None:
                return hit
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

    autofill = autofill_required_enabled() and bool(required)

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
        # Soft-essay heuristics, existing flag, or autofill mode mark AI-writable.
        entry["ai_may_answer"] = (
            autofill
            or bool(entry.get("ai_may_answer"))
            or is_ai_generatable_question(
                q, opts if opts is not None else entry.get("options")
            )
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
        if autofill:
            return {
                "status": "autofill_ok",
                "id": entry.get("id"),
                "answer": None,
                "message": _autofill_ok_message(entry),
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
                f"or set ai_may_answer=true to let the agent write it. "
                + _pending_continue_guidance(required=bool(entry.get("required")))
            ),
        }

    entry_id = _slug_id(key)
    # Avoid id collisions with different wording
    used = {str(e.get("id")) for e in entries if isinstance(e, dict)}
    if entry_id in used:
        entry_id = f"{entry_id}_{uuid.uuid4().hex[:6]}"

    ai_ok = autofill or is_ai_generatable_question(q, opts)
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
    if autofill:
        return {
            "status": "autofill_ok",
            "id": entry_id,
            "answer": None,
            "message": _autofill_ok_message(entry),
        }
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
            f"or set ai_may_answer=true to let the agent write it. "
            + _pending_continue_guidance(required=bool(required))
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

    from_profile = answer_from_profile(question, profile, options=options)
    if from_profile is not None:
        return (
            f"ANSWER: {from_profile} "
            "(from applicant profile — use this; do not record as pending)"
        )

    existing = lookup_entry(question, path)
    if existing is not None and (
        _ai_may_answer(existing) or (autofill_required_enabled() and required)
    ):
        # Persist soft-essay / autofill flag so the prompt lists it under AI may generate.
        if not bool(existing.get("ai_may_answer")) or (
            autofill_required_enabled() and required and not bool(existing.get("ai_may_answer"))
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
        if autofill_required_enabled() and (
            required or bool(existing.get("required"))
        ):
            return _autofill_ok_message(existing)
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
