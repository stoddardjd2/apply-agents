"""Landed application.run worker — claim via API, apply with Camoufox, finish."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from colorama import Fore, Style, init as colorama_init
from dotenv import load_dotenv

from .browser.fill_log import chunk_outcomes, fill_step_detail
from .config import load_apply_config_for_job
from .config.worker_config import DEFAULT_WORKER_CONFIG_PATH, WorkerConfig, load_worker_config
from .landed import LandedApiError, LandedClient, load_landed_connection
from .landed.urls import clean_job_url

# Stored on applications.worker_instance (via X-Landed-Worker) and finish/step details
# so UI/DB can tell this Camoufox worker apart from Landed's Node browser-worker.
APPLIER_SERVICE = "apply-agents"
APPLIER_RUNTIME = "camoufox+openai-agents"
# Must match computer_use.browser.local exit codes
EXIT_NEEDS_HUMAN = 3
EXIT_DUPLICATE = 4
EXIT_POSTING_UNAVAILABLE = 5


def escape_step_should_abort(ack: Any) -> bool:
    """True when Landed escape_aggregator StepAck says duplicate/cancelled."""
    if not isinstance(ack, dict):
        return False
    return bool(ack.get("duplicate") or ack.get("cancelled"))


def _resolve_model(model: str | None = None) -> str:
    resolved = (model or os.getenv("OPENAI_COMPUTER_USE_MODEL") or "").strip()
    if not resolved:
        raise ValueError(
            "Set OPENAI_COMPUTER_USE_MODEL in .env or pass --model (e.g. gpt-6-luna)."
        )
    return resolved


def _max_applications_from_env() -> int | None:
    """Return max jobs to run, or None for unlimited.

    WORKER_MAX_APPLICATIONS: positive int, or 0 / infinite / inf for unlimited.
    """
    raw = (os.getenv("WORKER_MAX_APPLICATIONS") or "").strip().lower()
    if not raw or raw in {"0", "infinite", "inf", "none", "unlimited"}:
        return None
    try:
        n = int(raw)
    except ValueError as exc:
        raise ValueError(
            "WORKER_MAX_APPLICATIONS must be a positive integer, "
            "or 0/infinite for unlimited."
        ) from exc
    if n < 0:
        raise ValueError(
            "WORKER_MAX_APPLICATIONS must be a positive integer, "
            "or 0/infinite for unlimited."
        )
    return n


def _claim_fields(
    claim: dict[str, Any],
) -> tuple[str, str, str | None, str | None, bool, dict[str, Any], dict[str, Any]]:
    app = claim.get("application") or {}
    job_raw = claim.get("job") or {}
    fields_raw = claim.get("fields") or {}
    job = dict(job_raw) if isinstance(job_raw, dict) else {}
    fields = dict(fields_raw) if isinstance(fields_raw, dict) else {}

    application_id = str(app.get("id") or claim.get("applicationId") or "").strip()
    if not application_id:
        raise ValueError("Claim payload missing application.id")

    apply_url = (
        str(app.get("applyUrl") or app.get("apply_url") or "").strip()
        or str(job.get("applyUrl") or job.get("apply_url") or job.get("jobUrl") or "").strip()
    )
    if not apply_url:
        raise ValueError(f"Claim {application_id} missing applyUrl")

    adapter = str(app.get("adapter") or claim.get("adapter") or "").strip() or None
    cover = fields.get("coverLetter")
    if cover is None:
        cover = fields.get("cover_letter")
    cover_letter = str(cover).strip() if cover else None

    dry_run = bool(app.get("dryRun") if app.get("dryRun") is not None else app.get("mode") == "dry_run")
    mode = str(app.get("mode") or "").strip().lower()
    if mode == "submit":
        dry_run = False
    elif mode == "dry_run":
        dry_run = True

    return application_id, apply_url, adapter, cover_letter, dry_run, job, fields


def _status_style(status: str) -> str:
    """ANSI color from Landed application state / finish outcome."""
    key = (status or "").strip().lower()
    if key in {"submitted", "verified", "success"}:
        return Fore.GREEN
    if key in {"dry_run_complete", "dry_run", "unverified", "cancelled"}:
        return Fore.CYAN
    if key in {"failed_retryable", "needs_human"}:
        return Fore.YELLOW
    if key in {"failed_permanent", "cancelled", "blocked"}:
        return Fore.RED
    if key in {"finish_error", "finish_rejected", "error"}:
        return Fore.LIGHTRED_EX
    return Fore.WHITE


def _ack_landed_status(ack: Any, *, requested_outcome: str) -> tuple[str, bool]:
    """Return (landed_state, accepted) from a FinishAck dict."""
    if not isinstance(ack, dict):
        return requested_outcome, True
    state = str(ack.get("state") or ack.get("status") or "").strip()
    accepted = ack.get("accepted")
    if accepted is None:
        accepted = True
    if not state:
        state = requested_outcome
    if not accepted:
        # Landed kept/returned a different state (e.g. already cancelled).
        return state or "finish_rejected", False
    return state, True


def _applier_meta(worker_cfg: WorkerConfig) -> dict[str, Any]:
    """Metadata identifying which autofill service handled the application."""
    return {
        "workerService": worker_cfg.worker_id or APPLIER_SERVICE,
        "applier": APPLIER_SERVICE,
        "applierRuntime": APPLIER_RUNTIME,
        # Distinct from Landed Node worker instances (browser-worker-*).
        "applierKind": "apply-agents",
    }


def _post_fill_steps(
    client: LandedClient,
    application_id: str,
    outcomes: list[dict[str, Any]],
    *,
    worker_cfg: WorkerConfig,
) -> int:
    """POST Landed timeline fill step(s) so UI Questions & answers shows fills."""
    if not outcomes:
        return 0
    applier = {
        "service": APPLIER_SERVICE,
        "runtime": APPLIER_RUNTIME,
        "workerId": worker_cfg.worker_id or APPLIER_SERVICE,
    }
    posted = 0
    for page_i, chunk in enumerate(chunk_outcomes(outcomes), start=1):
        detail = fill_step_detail(chunk, page=page_i, applier=applier)
        try:
            client.step(
                application_id,
                name="fill",
                status="ok",
                detail=detail,
            )
            posted += len(chunk)
        except LandedApiError as exc:
            print(
                f"fill step failed for {application_id} (page={page_i}): {exc}",
                file=sys.stderr,
                flush=True,
            )
    if posted:
        print(
            f"Posted {posted} filled field(s) to Landed Q&A "
            f"(source={APPLIER_SERVICE}).",
            flush=True,
        )
    return posted


def _finish_safe(
    client: LandedClient,
    application_id: str,
    *,
    outcome: str,
    reason_code: str,
    details: dict[str, Any],
    worker_cfg: WorkerConfig | None = None,
    confirmation: dict[str, Any] | None = None,
) -> str:
    """Finish on Landed; color + return the *confirmed* application status."""
    merged = dict(details or {})
    if worker_cfg is not None:
        merged.update(_applier_meta(worker_cfg))
    else:
        merged.setdefault("applier", APPLIER_SERVICE)
        merged.setdefault("applierKind", "apply-agents")
    try:
        ack = client.finish(
            application_id,
            outcome=outcome,
            reason_code=reason_code,
            details=merged,
            confirmation=confirmation,
        )
        status, accepted = _ack_landed_status(ack, requested_outcome=outcome)
        if not accepted:
            status_label = f"finish_rejected→{status}"
            color = _status_style("finish_rejected")
        else:
            status_label = status
            color = _status_style(status)
        print(
            f"{color}{Style.BRIGHT}"
            f"Landed status: {status_label.upper()}"
            f"{Style.NORMAL}"
            f"  (requested={outcome}, accepted={accepted}, id={application_id})"
            f"{Style.RESET_ALL}",
            flush=True,
        )
        if ack is not None:
            print(f"  finish ack: {ack}", flush=True)
        return status_label
    except LandedApiError as exc:
        print(
            f"{Fore.RED}{Style.BRIGHT}"
            f"Landed status: FINISH_ERROR"
            f"{Style.NORMAL}"
            f"  (requested={outcome}, id={application_id}): {exc}"
            f"{Style.RESET_ALL}",
            file=sys.stderr,
            flush=True,
        )
        return "finish_error"


def _job_banner(title: str, *, color: str = Fore.WHITE) -> None:
    """Visual separator so consecutive job runs are easy to scan in the terminal."""
    line = "=" * 72
    print(
        f"\n{color}{Style.BRIGHT}{line}\n{title}\n{line}{Style.RESET_ALL}",
        flush=True,
    )


async def _run_one(
    *,
    client: LandedClient,
    worker_cfg: WorkerConfig,
    claim: dict[str, Any],
    model: str,
) -> str:
    """Run one claimed job. Returns Landed's confirmed application status."""
    application_id, apply_url, adapter, cover_letter, dry_run, job, fields = _claim_fields(
        claim
    )
    _job_banner(
        f"JOB START  id={application_id}  adapter={adapter or '?'}  "
        f"mode={'dry_run' if dry_run else 'submit'}\n"
        f"  url={apply_url}\n"
        f"  applier={APPLIER_SERVICE} (worker_id={worker_cfg.worker_id})",
        color=Fore.CYAN,
    )

    # Timeline + finish details: which autofill service owns this attempt.
    try:
        client.step(
            application_id,
            name="worker_claimed",
            status="ok",
            detail=_applier_meta(worker_cfg),
        )
    except LandedApiError as exc:
        print(f"worker_claimed step failed (continuing): {exc}", flush=True)

    blocked = worker_cfg.is_blocked(adapter=adapter, apply_url=apply_url)
    if blocked:
        print(f"{Fore.YELLOW}Blocked by config ({blocked}); skipping browser.{Style.RESET_ALL}", flush=True)
        return _finish_safe(
            client,
            application_id,
            outcome="failed_permanent",
            reason_code="adapter.unsupported",
            details={
                "summary": f"Blocked by worker blocklist/allowlist: {blocked}",
                "adapter": adapter,
                "applyUrl": apply_url,
            },
            worker_cfg=worker_cfg,
        )

    # Sites often show the uploaded filename; keep the human name with spaces.
    resume_path = worker_cfg.resume_dir / application_id / "Jared Stoddard Resume.pdf"
    try:
        client.download_resume(application_id, resume_path)
        print(f"Resume saved: {resume_path}", flush=True)
    except LandedApiError as exc:
        return _finish_safe(
            client,
            application_id,
            outcome="failed_retryable",
            reason_code="system.unhandled",
            details={"summary": f"Resume download failed: {exc}"},
            worker_cfg=worker_cfg,
        )

    # Worker submit override > Landed dry_run flag > apply.config / env
    if worker_cfg.submit is not None:
        submit = worker_cfg.submit
    else:
        submit = not dry_run

    try:
        config = load_apply_config_for_job(
            job_url=apply_url,
            resume_path=resume_path,
            cover_letter=cover_letter,
            submit=submit,
            path=worker_cfg.apply_config_path,
            notes=f"Landed application {application_id}",
            job=job,
            fields=fields,
        )
        salary = config.profile.get("salary_expectation_usd")
        salary_src = config.profile.get("salary_expectation_source")
        if salary is not None:
            print(
                f"Salary expectation: ${int(salary):,} "
                f"({salary_src or 'profile'})",
                flush=True,
            )
    except (ValueError, FileNotFoundError, OSError) as exc:
        return _finish_safe(
            client,
            application_id,
            outcome="failed_retryable",
            reason_code="system.unhandled",
            details={"summary": f"Config merge failed: {exc}"},
            worker_cfg=worker_cfg,
        )

    from .browser import run_local_apply

    # Filled by report_escape when Landed marks the escape URL as a duplicate.
    escape_dup: dict[str, Any] = {
        "abort": False,
        "duplicate": False,
        "cancelled": False,
        "reasonCode": None,
        "ack": None,
    }

    def report_escape(url: str, adapter_name: str, via: str) -> bool:
        """Post escape_aggregator; return True when the worker must abort (no submit)."""
        try:
            ack = client.step(
                application_id,
                name="escape_aggregator",
                status="ok",
                detail={
                    "url": clean_job_url(url) or url,
                    "adapter": adapter_name,
                    "via": via,
                },
            )
            print(f"Posted escape_aggregator for {application_id}: {ack}", flush=True)
        except LandedApiError as exc:
            print(
                f"escape_aggregator step failed for {application_id}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return False
        if not escape_step_should_abort(ack):
            return False
        duplicate = bool(ack.get("duplicate"))
        cancelled = bool(ack.get("cancelled"))
        escape_dup.update(
            abort=True,
            duplicate=duplicate,
            cancelled=cancelled,
            reasonCode=ack.get("reasonCode") or "eligibility.already_applied",
            ack=ack,
        )
        print(
            f"{Fore.YELLOW}Escape URL is a duplicate "
            f"(duplicate={duplicate}, cancelled={cancelled}, "
            f"reason={escape_dup['reasonCode']}) — aborting apply.{Style.RESET_ALL}",
            flush=True,
        )
        return True

    def upload_full_page(data: bytes, meta: dict[str, Any]) -> None:
        """Upload full-page JPEG to Landed artifacts + timeline step (like Node worker)."""
        filename = str(meta.get("filename") or "full-page.jpg")
        content_type = str(meta.get("content_type") or "image/jpeg")
        kind = str(meta.get("kind") or "screenshot")
        try:
            art = client.artifact(
                application_id,
                data=data,
                content_type=content_type,
                filename=filename,
                kind=kind,
            )
            artifact_id = art.get("id")
            print(
                f"Uploaded full-page artifact id={artifact_id} "
                f"size={art.get('sizeBytes') or len(data)} url={meta.get('url')!r}",
                flush=True,
            )
            step_name = (
                "pre_submit_screenshot"
                if meta.get("pre_submit")
                else "full_page_screenshot"
            )
            client.step(
                application_id,
                name=step_name,
                status="ok",
                detail={
                    "url": meta.get("url"),
                    "fullPage": True,
                    "bytes": len(data),
                    "filename": filename,
                    "preSubmit": bool(meta.get("pre_submit")),
                },
                artifact_id=artifact_id,
            )
        except LandedApiError as exc:
            print(
                f"Full-page artifact upload failed for {application_id}: {exc}",
                file=sys.stderr,
                flush=True,
            )

    page_evidence: dict[str, Any] = {}
    try:
        code = await run_local_apply(
            model=model,
            config=config,
            costs_path=worker_cfg.costs_path,
            profile_dir=worker_cfg.browser_profile,
            on_escape_aggregator=report_escape,
            on_full_page_screenshot=upload_full_page,
            page_evidence_out=page_evidence,
            landed_client=client,
            application_id=application_id,
            company=str(job.get("company") or "").strip() or None,
        )
    except Exception as exc:
        print(
            f"{Fore.YELLOW}Apply crashed: {type(exc).__name__}: {exc}{Style.RESET_ALL}",
            flush=True,
        )
        return _finish_safe(
            client,
            application_id,
            outcome="failed_retryable",
            reason_code="system.unhandled",
            details={
                "summary": f"Apply crashed: {type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-2000:],
            },
            worker_cfg=worker_cfg,
        )

    filled_fields = [
        row
        for row in (page_evidence.get("filledFields") or [])
        if isinstance(row, dict)
    ]
    _post_fill_steps(client, application_id, filled_fields, worker_cfg=worker_cfg)

    url_before = clean_job_url(page_evidence.get("urlBefore")) or page_evidence.get(
        "urlBefore"
    )
    page_url = clean_job_url(page_evidence.get("url")) or page_evidence.get("url")
    confirmation = None
    if page_evidence.get("pageText") or page_url or url_before:
        confirmation = {
            "pageText": page_evidence.get("pageText") or "",
            "url": page_url or url_before,
            "urlBefore": url_before or page_url,
            "validationMessages": page_evidence.get("validationMessages") or [],
            "invalidCount": int(page_evidence.get("invalidCount") or 0),
            "blocked": page_evidence.get("blocked"),
        }

    fill_meta = {
        "filledCount": len(filled_fields),
        "filledFields": filled_fields,
    }

    if code == EXIT_POSTING_UNAVAILABLE:
        return _finish_safe(
            client,
            application_id,
            outcome="failed_permanent",
            reason_code="adapter.posting_expired",
            details={
                "summary": (
                    "Posting unavailable: job is closed, expired, filled, or no "
                    "longer accepting applications. Not eligible for re-queue."
                ),
                "exitCode": code,
                **fill_meta,
            },
            worker_cfg=worker_cfg,
            confirmation=confirmation,
        )
    if code == EXIT_NEEDS_HUMAN:
        return _finish_safe(
            client,
            application_id,
            outcome="needs_human",
            reason_code="adapter.field_unresolved",
            details={
                "summary": (
                    "Autofill stopped: required field unanswered or application "
                    "was not submitted. Check form_knowledge.json / agent report."
                ),
                "exitCode": code,
                "kind": "other",
                **fill_meta,
            },
            worker_cfg=worker_cfg,
            confirmation=confirmation,
        )
    if code == EXIT_DUPLICATE or escape_dup.get("abort"):
        # Landed already cancelled on duplicate ack — do not call finish(submitted).
        if escape_dup.get("cancelled"):
            print(
                f"{Fore.CYAN}{Style.BRIGHT}"
                f"Landed status: CANCELLED"
                f"{Style.NORMAL}"
                f"  (escape URL duplicate, id={application_id})"
                f"{Style.RESET_ALL}",
                flush=True,
            )
            if escape_dup.get("ack") is not None:
                print(f"  escape ack: {escape_dup['ack']}", flush=True)
            return "cancelled"
        return _finish_safe(
            client,
            application_id,
            outcome="failed_permanent",
            reason_code=str(
                escape_dup.get("reasonCode") or "eligibility.already_applied"
            ),
            details={
                "summary": (
                    "Aborted: escape_aggregator URL matches a job this user already "
                    "applied to (or has live) on another catalog row."
                ),
                "exitCode": code,
                "escapeAck": escape_dup.get("ack"),
                **fill_meta,
            },
            worker_cfg=worker_cfg,
            confirmation=confirmation,
        )
    if code == 0:
        if submit:
            # Exit 0 in submit mode already means the agent reported
            # **Application submitted:** Yes — trust that; skip Landed page verification.
            trust_url = url_before or page_url or clean_job_url(config.job_url)
            trust_confirmation = {
                "pageText": "Application submitted (trusted agent report).",
                "url": trust_url,
                "urlBefore": url_before or trust_url,
                "validationMessages": [],
                "invalidCount": 0,
                "blocked": None,
            }
            print(
                "Trusting agent Application submitted: Yes — "
                "finishing with trustAgentReport (no page verification).",
                flush=True,
            )
            return _finish_safe(
                client,
                application_id,
                outcome="submitted",
                reason_code="application.submitted",
                details={
                    "summary": "Camoufox apply finished (submit mode; trusted agent report).",
                    "exitCode": code,
                    "trustAgentReport": True,
                    **fill_meta,
                },
                worker_cfg=worker_cfg,
                confirmation=trust_confirmation,
            )
        return _finish_safe(
            client,
            application_id,
            outcome="dry_run_complete",
            reason_code="application.dry_run",
            details={
                "summary": "Camoufox apply finished (dry run).",
                "exitCode": code,
                **fill_meta,
            },
            worker_cfg=worker_cfg,
            confirmation=confirmation,
        )
    return _finish_safe(
        client,
        application_id,
        outcome="failed_retryable",
        reason_code="system.unhandled",
        details={
            "summary": f"Apply exited with code {code}",
            "exitCode": code,
            **fill_meta,
        },
        worker_cfg=worker_cfg,
        confirmation=confirmation,
    )


async def _run_forever_async(
    *, worker_cfg: WorkerConfig, model: str, once: bool = False
) -> int:
    """Single event loop for the whole worker lifetime.

    Calling ``asyncio.run`` per job closes the loop while the Agents SDK / OpenAI
    async HTTP client still holds connections → next job fails with
    ``RuntimeError: Event loop is closed`` (logged only as ``Error getting response``).
    """
    api_base, token, landed_env_src = load_landed_connection()
    # worker.config.json can still override the host; token always from env/Landed .env
    api_base = worker_cfg.landed_api_base or api_base
    if not token:
        raise ValueError(
            "LANDED_WORKER_TOKEN not found. Set it in ../landed/.env "
            "(or LANDED_WORKER_TOKEN in this project's .env)."
        )
    client = LandedClient(
        api_base=api_base,
        worker_token=token,
        worker_id=worker_cfg.worker_id,
    )
    src = f" (token from {landed_env_src})" if landed_env_src else ""
    max_apps = 1 if once else _max_applications_from_env()
    limit_label = "1 (--once)" if once else (
        "infinite" if max_apps is None else str(max_apps)
    )
    print(
        f"Worker {worker_cfg.worker_id} → {api_base}{src} "
        f"(blocklist={worker_cfg.blocklist}, allowlist={worker_cfg.allowlist or 'any'}, "
        f"max_applications={limit_label})",
        flush=True,
    )

    idle = 0
    apps_done = 0
    while True:
        try:
            # Sync urllib claim — keep it off the event loop thread.
            claim = await asyncio.to_thread(client.claim, worker_cfg.claim_adapters())
        except LandedApiError as exc:
            print(f"Claim error: {exc}", file=sys.stderr, flush=True)
            if once:
                return 1
            await asyncio.sleep(worker_cfg.poll_interval_seconds)
            continue

        if claim is None:
            idle += 1
            if once:
                print("No jobs ready.", flush=True)
                return 0
            wait = worker_cfg.poll_interval_seconds
            # First idle + every ~60s so a quiet terminal still looks alive.
            if idle == 1 or idle % max(1, int(round(60 / wait))) == 0:
                print(
                    f"No jobs ready (poll #{idle}); sleeping {wait:g}s…",
                    flush=True,
                )
            await asyncio.sleep(wait)
            continue

        idle = 0
        landed_status = await _run_one(
            client=client, worker_cfg=worker_cfg, claim=claim, model=model
        )
        apps_done += 1
        if max_apps is not None and apps_done >= max_apps:
            reason = "--once" if once else f"WORKER_MAX_APPLICATIONS={max_apps}"
            _job_banner(
                f"JOB END  Landed status={landed_status.upper()} — "
                f"stopping after {apps_done} application(s) ({reason})",
                color=_status_style(landed_status),
            )
            return 0
        _job_banner(
            f"JOB END  Landed status={landed_status.upper()} — idle until next claim",
            color=_status_style(landed_status),
        )


def run_forever(*, worker_cfg: WorkerConfig, model: str, once: bool = False) -> int:
    colorama_init(autoreset=False)
    return asyncio.run(
        _run_forever_async(worker_cfg=worker_cfg, model=model, once=once)
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    colorama_init(autoreset=False)
    parser = argparse.ArgumentParser(
        description="Poll Landed for queued applications and apply with Camoufox"
    )
    parser.add_argument(
        "--config",
        default=os.getenv("WORKER_CONFIG", str(DEFAULT_WORKER_CONFIG_PATH)),
        help="Path to worker.config.json",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Claim at most one job (or exit if none), then stop",
    )
    args = parser.parse_args(argv)

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is required in .env", file=sys.stderr)
        return 2

    try:
        model = _resolve_model(args.model)
        worker_cfg = load_worker_config(Path(args.config))
        return run_forever(worker_cfg=worker_cfg, model=model, once=args.once)
    except (ValueError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
