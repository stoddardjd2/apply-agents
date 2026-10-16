"""Per-turn AI think/did/say logs, plus hard-run learnings at end of apply."""

from __future__ import annotations

import os
from collections import Counter
from typing import Any

from agents import RunHooks
from colorama import Fore, Style, init as colorama_init

from computer_use.features.learnings import (
    hard_run_turn_threshold,
    record_hard_run,
)

_AI = Fore.LIGHTMAGENTA_EX
_DID = Fore.LIGHTYELLOW_EX
_SAY = Fore.CYAN
_THINK = Fore.LIGHTGREEN_EX
_DIM = Fore.LIGHTBLACK_EX


def ai_turn_logs_enabled() -> bool:
    """AI_TURN_LOGS_ENABLED — default on. Set 0/false/off to silence turn logs."""
    raw = os.getenv("AI_TURN_LOGS_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def make_apply_run_hooks(
    *,
    job_url: str | None = None,
    company: str | None = None,
) -> ApplyRunHooks | None:
    """Return hooks when logging is enabled; None otherwise (Runner skips)."""
    if not ai_turn_logs_enabled():
        return None
    return ApplyRunHooks(job_url=job_url, company=company)


def _line(color: str, label: str, body: str) -> str:
    return f"  {color}{Style.BRIGHT}{label}{Style.NORMAL}{color}: {body}{Style.RESET_ALL}"


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            dumped = obj.model_dump()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            pass
    out: dict[str, Any] = {}
    for key in (
        "type",
        "text",
        "summary",
        "content",
        "action",
        "actions",
        "name",
        "arguments",
        "call_id",
    ):
        if hasattr(obj, key):
            out[key] = getattr(obj, key)
    return out


def _clip(text: str, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _extract_text(item: Any) -> str:
    d = _as_dict(item)
    chunks: list[str] = []
    for part in d.get("summary") or []:
        pd = _as_dict(part)
        if pd.get("text"):
            chunks.append(str(pd["text"]))
    content = d.get("content")
    if isinstance(content, str) and content.strip():
        chunks.append(content)
    elif isinstance(content, list):
        for part in content:
            pd = _as_dict(part)
            if pd.get("text"):
                chunks.append(str(pd["text"]))
    if d.get("text") and not chunks:
        chunks.append(str(d["text"]))
    return " ".join(chunks).strip()


def _action_type(action: Any) -> str:
    d = _as_dict(action)
    typ = str(d.get("type") or getattr(action, "type", None) or "action").strip()
    lower = typ.lower()
    for name in (
        "click",
        "type",
        "scroll",
        "keypress",
        "wait",
        "screenshot",
        "drag",
        "move",
        "double_click",
    ):
        if name in lower:
            return name
    return typ or "action"


def parse_turn(output: Any) -> dict[str, Any]:
    """Structured fields from one model response (think / did / say / tools)."""
    items = list(output or [])
    action_counts: Counter[str] = Counter()
    tools: list[str] = []
    say = ""
    think_parts: list[str] = []

    for item in items:
        d = _as_dict(item)
        typ = str(d.get("type") or getattr(item, "type", None) or type(item).__name__)
        lower = typ.lower()

        if "reasoning" in lower:
            text = _extract_text(item)
            if text:
                think_parts.append(text)
            continue

        if typ in {"message", "output_text"} or typ.endswith("message"):
            text = _extract_text(item)
            if text and (not say or len(text) > len(say)):
                say = text
            continue

        if "computer" in lower:
            action = d.get("action")
            actions = d.get("actions")
            if action is not None:
                action_counts[_action_type(action)] += 1
            if isinstance(actions, list):
                for act in actions:
                    action_counts[_action_type(act)] += 1
            if action is None and not actions:
                action_counts["computer"] += 1
            continue

        if "function_call" in lower or typ == "custom_tool_call":
            name = str(d.get("name") or getattr(item, "name", "") or "tool").strip()
            if name and name not in tools:
                tools.append(name)
            continue

    think = " ".join(think_parts).strip()
    did_parts: list[str] = []
    if action_counts:
        did_parts.append(
            ", ".join(
                f"{name}×{n}" if n > 1 else name
                for name, n in action_counts.most_common()
            )
        )
    if tools:
        did_parts.append("tools: " + ", ".join(tools))
    did = "; ".join(did_parts)

    return {
        "think": think,
        "did": did,
        "say": say,
        "tools": tools,
        "action_counts": dict(action_counts),
    }


def summarize_turn(output: Any) -> list[str]:
    """Stdout lines for a model turn — always includes think when available."""
    parsed = parse_turn(output)
    if not any(parsed.get(k) for k in ("think", "did", "say")) and not (
        output or []
    ):
        return [_line(_DIM, "did", "(no output)")]

    lines: list[str] = []
    think = parsed["think"]
    did = parsed["did"]
    say = parsed["say"]

    if think:
        lines.append(_line(_THINK, "think", _clip(think, 360)))
    else:
        lines.append(_line(_DIM, "think", "(no reasoning summary this turn)"))

    if did:
        lines.append(_line(_DID, "did", did))
    else:
        lines.append(_line(_DID, "did", "thinking / no browser action"))

    if say:
        # Final reports can be long — keep more of them.
        limit = 280 if say.lstrip().startswith("**") else 200
        lines.append(_line(_SAY, "say", _clip(say, limit)))

    return lines


# Kept for tests / callers that still format a single item.
def format_model_output_item(item: Any) -> list[str]:
    return summarize_turn([item])


class ApplyRunHooks(RunHooks[Any]):
    """Stdout per turn + append hard_run learnings when a job burns many turns."""

    def __init__(
        self,
        *,
        job_url: str | None = None,
        company: str | None = None,
    ) -> None:
        colorama_init(autoreset=False)
        self._turn = 0
        self._enabled = ai_turn_logs_enabled()
        self._job_url = job_url
        self._company = company
        self._turns: list[dict[str, Any]] = []
        self._hard_run_written = False

    @property
    def turn_count(self) -> int:
        return self._turn

    async def on_llm_end(self, context: Any, agent: Any, response: Any) -> None:
        if not self._enabled:
            return
        self._turn += 1
        parsed = parse_turn(getattr(response, "output", None) or [])
        self._turns.append({"turn": self._turn, **parsed})
        print(
            f"\n{_AI}{Style.BRIGHT}--- AI turn {self._turn} ---{Style.RESET_ALL}",
            flush=True,
        )
        for line in summarize_turn(getattr(response, "output", None) or []):
            print(line, flush=True)

    async def on_agent_end(self, context: Any, agent: Any, output: Any) -> None:
        self.maybe_record_hard_run(final_report=str(output or ""))

    async def on_tool_start(self, context: Any, agent: Any, tool: Any) -> None:
        return

    async def on_tool_end(
        self, context: Any, agent: Any, tool: Any, result: object
    ) -> None:
        return

    def maybe_record_hard_run(self, *, final_report: str = "") -> dict[str, Any] | None:
        """Write apply_learnings.json hard_run when turn count is high."""
        if self._hard_run_written or self._turn < hard_run_turn_threshold():
            return None
        excerpts = [
            t["think"]
            for t in self._turns
            if str(t.get("think") or "").strip()
        ]
        # Prefer later turns (usually where stuck/solved).
        excerpts = excerpts[-8:]
        action_bits: list[str] = []
        totals: Counter[str] = Counter()
        for t in self._turns:
            for name, n in (t.get("action_counts") or {}).items():
                totals[str(name)] += int(n)
            for tool in t.get("tools") or []:
                totals[f"tool:{tool}"] += 1
        if totals:
            action_bits.append(
                ", ".join(
                    f"{name}×{n}" if n > 1 else name
                    for name, n in totals.most_common(12)
                )
            )
        entry = record_hard_run(
            turns=self._turn,
            job_url=self._job_url,
            company=self._company,
            summary=(
                f"Hard apply run: {self._turn} turns"
                + (f" on {self._company}" if self._company else "")
                + ". Review thinking excerpts for what burned turns."
            ),
            thinking_excerpts=excerpts,
            actions_summary="; ".join(action_bits),
            final_report=final_report,
        )
        if entry:
            self._hard_run_written = True
            print(
                f"{_DIM}Recorded hard_run learning "
                f"({self._turn} turns) → apply_learnings.json{Style.RESET_ALL}",
                flush=True,
            )
        return entry
