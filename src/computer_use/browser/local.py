"""Local headed Camoufox computer-use with reusable browser login cookies."""

from __future__ import annotations

import asyncio
import base64
import os
import re
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from agents import (
    Agent,
    AsyncComputer,
    Button,
    ComputerTool,
    ModelSettings,
    Runner,
)
from openai.types.shared.reasoning import Reasoning
from playwright.async_api import BrowserContext, Frame, Page

from ..captcha.nopecha import (
    nopecha_enabled,
    nopecha_solve_timeout_ms,
    prepare_nopecha_addon,
)
from ..captcha.nonecap import (
    EXTRACT_HCAPTCHA_JS,
    build_inject_token_script,
    nonecap_enabled,
    solve_hcaptcha,
)
from ..config import ApplyConfig
from ..costs import record_run_cost
from ..features import ApplyRunContext, compose
from ..features.verification_code import utc_now_iso
from ..landed.aggregator import adapter_for_url, is_aggregator_host
from ..landed.client import LandedClient
from ..landed.urls import (
    clean_job_url,
    evidence_job_url,
    is_post_apply_noise_url,
)
from ..prompts import build_prompt, build_system_instructions
from .agent_log import ApplyRunHooks, make_apply_run_hooks
from .camoufox_setup import apply_camoufox_install_dir
from .fill_log import (
    FILL_SOURCE,
    FOCUS_META_JS,
    PASSWORD_REDACTED,
    SCRAPE_FILLED_JS,
    merge_fill_outcomes,
)

# (url, adapter, via) → True to abort apply (Landed duplicate/cancelled ack).
EscapeAggregatorCallback = Callable[[str, str, str], bool | None]


class EscapeDuplicateAbort(RuntimeError):
    """Raised when escape_aggregator lands on a URL already applied (or live) elsewhere."""
# (jpeg_bytes, meta) — worker uploads full-page screenshot to Landed artifacts.
FullPageScreenshotCallback = Callable[[bytes, dict[str, Any]], None]

# Landed WorkerGateway.MAX_ARTIFACT_BYTES = 15 MiB
_MAX_ARTIFACT_BYTES = 15 * 1024 * 1024

# Must run before Camoufox resolves its browser binary (shared AppData conflicts).
apply_camoufox_install_dir()
from camoufox.async_api import AsyncCamoufox  # noqa: E402

CUA_KEY_TO_PLAYWRIGHT_KEY = {
    "/": "Divide",
    "\\": "Backslash",
    "alt": "Alt",
    "arrowdown": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "arrowright": "ArrowRight",
    "arrowup": "ArrowUp",
    "backspace": "Backspace",
    "capslock": "CapsLock",
    "cmd": "Meta",
    "ctrl": "Control",
    "delete": "Delete",
    "end": "End",
    "enter": "Enter",
    "esc": "Escape",
    "home": "Home",
    "insert": "Insert",
    "option": "Alt",
    "pagedown": "PageDown",
    "pageup": "PageUp",
    "shift": "Shift",
    "space": " ",
    "super": "Meta",
    "tab": "Tab",
    "win": "Meta",
}

DEFAULT_PROFILE_DIR = Path(".camoufox-profile")
DEFAULT_STORAGE_STATE = Path("browser-auth.json")

# Apply / auth flows often open in a new tab. Prefer these over search/listing pages.
_APPLY_URL_HINTS = (
    "/apply",
    "/smartapply",
    "/application",
    "/form/questions",
    "/questions/",
    "applystart",
    "boards.greenhouse.io",
    "jobs.lever.co",
    "myworkdayjobs.com",
    "ashbyhq.com",
)


def _is_apply_like_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(hint in lowered for hint in _APPLY_URL_HINTS)


def _is_blank_url(url: str) -> bool:
    lowered = (url or "").strip().lower()
    return not lowered or lowered in {"about:blank", "about:newtab", "chrome://newtab/"}


def resume_preview_enabled() -> bool:
    """OPEN_RESUME_PREVIEW — default off. Set 1/true/yes/on to open the PDF in another window."""
    raw = os.getenv("OPEN_RESUME_PREVIEW")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def open_resume_preview(resume_path: Path | str | None) -> bool:
    """Open the apply resume in the OS default PDF viewer (separate window).

    Returns True if a viewer was launched. Does not open a browser tab so the
    agent never adopts the preview as the active apply page.
    """
    if not resume_preview_enabled():
        return False
    if resume_path is None:
        return False
    path = Path(resume_path)
    if not path.is_file():
        print(f"Resume preview skipped — file not found: {path}", flush=True)
        return False
    resolved = path.resolve()
    try:
        if sys.platform == "win32":
            os.startfile(str(resolved))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(resolved)], close_fds=True)
        else:
            subprocess.Popen(["xdg-open", str(resolved)], close_fds=True)
    except Exception as exc:
        print(f"Resume preview failed to open: {exc}", flush=True)
        return False
    print(f"Resume preview opened: {resolved}", flush=True)
    return True


# Firefox permissions.default.* : 0=ask, 1=allow, 2=deny (no prompt).
_DENY_PERMISSION_PROMPTS: dict[str, Any] = {
    "geo.enabled": False,
    "permissions.default.geo": 2,
    "permissions.default.desktop-notification": 2,
    "permissions.default.camera": 2,
    "permissions.default.microphone": 2,
}


def _camoufox_kwargs(
    profile_dir: Path,
    *,
    addons: list[str] | None = None,
) -> dict[str, Any]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    opts: dict[str, Any] = {
        # Visible local window — watch the apply flow / Cloudflare live.
        "headless": False,
        "persistent_context": True,
        "user_data_dir": str(profile_dir.resolve()),
        # Needed so Cloudflare Turnstile / NopeCHA widgets in cross-origin iframes work.
        "disable_coop": True,
        "i_know_what_im_doing": True,
        "humanize": True,
        "os": "windows",
        "locale": "en-US",
        "enable_cache": True,
        # Needed so NoneCap token injection can fire hCaptcha data-callback in page JS.
        "main_world_eval": True,
        # Let NopeCHA open its own helper tabs if needed.
        "allow_addon_new_tab": True,
        # Deny geo/notifications/camera/mic so sites cannot block headed runs
        # with permission doorhangers (or trip a Windows location OS prompt).
        "firefox_user_prefs": dict(_DENY_PERMISSION_PROMPTS),
    }
    if addons:
        opts["addons"] = list(addons)
    return opts


def _resolve_nopecha_addons() -> list[str]:
    """Prepare NopeCHA Firefox addon path(s) for Camoufox, or [] when disabled."""
    if not nopecha_enabled():
        print("NopeCHA captcha solver disabled (NOPECHA_ENABLED=0).", flush=True)
        return []
    try:
        addon = prepare_nopecha_addon()
    except Exception as exc:
        print(f"NopeCHA addon prepare failed (continuing without solver): {exc}", flush=True)
        return []
    if addon is None:
        return []
    print(f"NopeCHA captcha solver loaded: {addon}", flush=True)
    return [str(addon)]


class LocalCamoufoxComputer(AsyncComputer):
    """Visible Camoufox window driven by the Agents SDK ComputerTool."""

    def __init__(
        self,
        start_url: str,
        *,
        profile_dir: Path | None = None,
        resume_path: Path | None = None,
        on_escape_aggregator: EscapeAggregatorCallback | None = None,
        on_full_page_screenshot: FullPageScreenshotCallback | None = None,
    ):
        self._camoufox: Any = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._start_url = start_url
        self._resume_path = resume_path
        self._resume_attached = False
        self._nopecha_addons = _resolve_nopecha_addons()
        self._captcha_armed = False  # only wait for solver after submit-ready click
        self._captcha_wait_exhausted = False
        self._profile_dir = profile_dir or Path(
            os.getenv("BROWSER_PROFILE", str(DEFAULT_PROFILE_DIR))
        )
        self._on_escape_aggregator = on_escape_aggregator
        self._on_full_page_screenshot = on_full_page_screenshot
        self._pre_submit_screenshot_taken = False
        self._started_on_aggregator = is_aggregator_host(start_url)
        self._escape_reported = False
        self._escape_duplicate = False
        # URL before the last Submit-like click — Landed submission verifier uses urlBefore.
        self._url_before_submit: str | None = None
        # Form fill ledger for Landed Q&A (typed log + end-of-run DOM scrape).
        self._last_focus_meta: dict[str, Any] | None = None
        self._typed_fills: dict[str, dict[str, Any]] = {}

    async def __aenter__(self):
        self._camoufox = AsyncCamoufox(
            **_camoufox_kwargs(self._profile_dir, addons=self._nopecha_addons)
        )
        self._context = await self._camoufox.__aenter__()
        assert self._context is not None
        self._context.on("page", self._on_new_page)
        if self._resume_path is not None:
            # Backup path: some sites open a real file picker. Prefer direct
            # input[type=file] attachment in _try_attach_resume (more reliable
            # on headed Firefox/Camoufox, where native dialogs often block).
            self._context.on(
                "filechooser",
                lambda chooser: asyncio.create_task(self._on_file_chooser(chooser)),
            )
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        self._attach_page_guards(self._page)
        for extra in self._context.pages[1:]:
            self._attach_page_guards(extra)
        await self._page.goto(self._start_url, wait_until="domcontentloaded")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._context is not None:
            try:
                await self._context.storage_state(path=str(DEFAULT_STORAGE_STATE))
            except Exception:
                pass
        if self._camoufox is not None:
            await self._camoufox.__aexit__(exc_type, exc_val, exc_tb)
        return None

    def _on_new_page(self, page: Page) -> None:
        """Playwright fires this when Apply opens in a new tab."""
        self._attach_page_guards(page)
        asyncio.create_task(self._adopt_new_page(page))

    def _attach_page_guards(self, page: Page) -> None:
        """Auto-dismiss JS alert/confirm/prompt so they cannot block the agent."""
        page.on(
            "dialog",
            lambda dialog: asyncio.create_task(self._dismiss_js_dialog(dialog)),
        )

    async def _dismiss_js_dialog(self, dialog: Any) -> None:
        kind = getattr(dialog, "type", "dialog")
        message = str(getattr(dialog, "message", "") or "")
        preview = message.replace("\n", " ")[:80]
        try:
            await dialog.dismiss()
            print(f"Auto-dismissed {kind} dialog: {preview!r}", flush=True)
        except Exception as exc:
            print(f"Failed to dismiss {kind} dialog: {exc}", flush=True)

    async def _on_file_chooser(self, chooser: Any) -> None:
        """Auto-attach the resume PDF, or re-select it to CLOSE a leftover OS picker.

        Ignoring the chooser when already attached leaves the native dialog open and
        blocks the headed window while the agent keeps clicking the form.
        """
        if self._resume_path is None or not self._resume_path.is_file():
            print("File chooser opened but no resume_path is configured.", flush=True)
            try:
                await chooser.set_files([])
            except Exception:
                await self._dismiss_file_dialog()
            return
        path = str(self._resume_path.resolve())
        try:
            await chooser.set_files(path)
            if self._resume_attached:
                print(
                    f"File chooser closed with same resume (already attached): "
                    f"{self._resume_path.name}",
                    flush=True,
                )
            else:
                self._resume_attached = True
                print(
                    f"Attached resume PDF via file chooser: {self._resume_path.name}",
                    flush=True,
                )
        except Exception as exc:
            print(f"File chooser resume attach failed: {exc}", flush=True)
            await self._dismiss_file_dialog()

    async def _dismiss_file_dialog(self) -> None:
        """Best-effort close of a stuck native file picker (Escape)."""
        page = self._page
        if page is None or page.is_closed():
            return
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.15)
            await page.keyboard.press("Escape")
            print("Sent Escape to dismiss possible file dialog.", flush=True)
        except Exception:
            pass

    async def _try_attach_resume(self) -> bool:
        """Set the resume on an empty file input at most once per run.

        Headed Camoufox often fails to surface a Playwright filechooser event
        when the agent clicks Upload — the OS dialog blocks instead. Setting
        files on the hidden <input type=file> avoids that entirely.

        Indeed Smart Apply remounts empty file inputs after upload; without a
        one-shot guard this would re-upload forever.
        """
        if self._resume_attached:
            return True
        if self._resume_path is None or not self._resume_path.is_file():
            return False
        if self._page is None or self._page.is_closed():
            return False

        path = str(self._resume_path.resolve())
        attached = False

        for frame in self._page.frames:
            try:
                inputs = frame.locator("input[type='file']")
                count = await inputs.count()
            except Exception:
                continue

            best_idx = -1
            best_score = -1
            for i in range(count):
                loc = inputs.nth(i)
                try:
                    meta = await loc.evaluate(
                        """(el) => ({
                            filled: !!(el.files && el.files.length),
                            blob: (
                              (el.name || '') + ' ' +
                              (el.id || '') + ' ' +
                              (el.className || '') + ' ' +
                              (el.getAttribute('aria-label') || '') + ' ' +
                              (el.accept || '')
                            ).toLowerCase(),
                            accept: (el.accept || '').toLowerCase()
                        })"""
                    )
                except Exception:
                    continue
                if meta.get("filled"):
                    self._resume_attached = True
                    attached = True
                    continue
                blob = str(meta.get("blob") or "")
                if any(k in blob for k in ("photo", "avatar", "headshot", "image")) and "pdf" not in blob:
                    continue
                score = 0
                if any(k in blob for k in ("resume", "cv", "curriculum", "attachment")):
                    score += 10
                if "cover" in blob:
                    score -= 5
                if "pdf" in str(meta.get("accept") or "") or not meta.get("accept"):
                    score += 2
                if score > best_score:
                    best_score = score
                    best_idx = i

            if best_idx < 0:
                continue
            loc = inputs.nth(best_idx)
            try:
                await loc.set_input_files(path)
                self._resume_attached = True
                attached = True
                print(
                    f"Attached resume PDF via file input: {self._resume_path.name}",
                    flush=True,
                )
            except Exception as exc:
                print(f"Resume file-input attach failed: {exc}", flush=True)

        return attached

    async def _adopt_new_page(self, page: Page) -> None:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=20_000)
        except Exception:
            pass
        # Popups often start as about:blank then navigate — wait briefly for a real URL.
        for _ in range(20):
            if page.is_closed():
                return
            if not _is_blank_url(page.url):
                break
            await asyncio.sleep(0.25)
        if page.is_closed() or _is_blank_url(page.url):
            print(f"Ignoring blank/closed popup tab: {getattr(page, 'url', '?')}", flush=True)
            return
        # Indeed/Glassdoor open "similar jobs" after submit — never make that active.
        if is_post_apply_noise_url(page.url):
            print(
                f"Ignoring post-apply alt-jobs tab (not the applied job): {page.url}",
                flush=True,
            )
            try:
                await page.close()
            except Exception:
                pass
            return
        await self._focus_page(page, reason="new tab opened")

    def _raise_if_escape_duplicate(self) -> None:
        if self._escape_duplicate:
            raise EscapeDuplicateAbort(
                "escape_aggregator URL matches a prior/live application — aborting apply"
            )

    def _maybe_report_escape(self, url: str, *, via: str) -> None:
        """Once: if we left Glassdoor/Indeed, notify Landed (jobs.apply_url / careers queue)."""
        if self._escape_reported or not self._started_on_aggregator:
            return
        if not self._on_escape_aggregator:
            return
        if not url or _is_blank_url(url):
            return
        if not url.lower().startswith(("http://", "https://")):
            return
        if is_aggregator_host(url):
            return
        adapter = adapter_for_url(url)
        self._escape_reported = True
        print(
            f"escape_aggregator: left aggregator → {url} (adapter={adapter}, via={via})",
            flush=True,
        )
        try:
            abort = self._on_escape_aggregator(url, adapter, via)
        except EscapeDuplicateAbort:
            self._escape_duplicate = True
            raise
        except Exception as exc:
            print(f"escape_aggregator callback failed: {exc}", flush=True)
            return
        if abort:
            self._escape_duplicate = True
            print(
                "escape_aggregator: Landed marked duplicate — aborting apply (no submit).",
                flush=True,
            )
            raise EscapeDuplicateAbort(
                f"Duplicate apply URL after escape: {url}"
            )

    async def _focus_page(self, page: Page, *, reason: str) -> None:
        if page.is_closed():
            return
        previous = self._page.url if self._page is not None and not self._page.is_closed() else None
        self._page = page
        try:
            await page.bring_to_front()
        except Exception:
            pass
        print(f"Switched active tab ({reason}): {page.url}", flush=True)
        if previous and previous != page.url:
            print(f"  previous tab was: {previous}", flush=True)
        via = "openForm_redirect" if "new tab" in reason.lower() else "employer_site"
        self._maybe_report_escape(page.url, via=via)

    async def _sync_active_page(self) -> Page:
        """Prefer an Apply/auth tab if one exists; otherwise use the newest real tab."""
        assert self._context is not None
        pages = [p for p in self._context.pages if not p.is_closed()]
        # Drop Indeed/Glassdoor post-apply "similar jobs" tabs (wrong listing).
        for p in list(pages):
            if p.is_closed():
                continue
            if is_post_apply_noise_url(p.url):
                print(
                    f"Closing post-apply alt-jobs tab: {clean_job_url(p.url) or p.url}",
                    flush=True,
                )
                try:
                    await p.close()
                except Exception:
                    pass
        pages = [p for p in self._context.pages if not p.is_closed()]
        usable = [
            p
            for p in pages
            if not _is_blank_url(p.url) and not is_post_apply_noise_url(p.url)
        ]
        if not usable:
            if self._page is not None and not self._page.is_closed():
                self._maybe_report_escape(self._page.url, via="employer_site")
                return self._page
            if pages:
                return pages[-1]
            raise RuntimeError("Browser has no open pages")

        apply_pages = [p for p in usable if _is_apply_like_url(p.url)]
        chosen = apply_pages[-1] if apply_pages else usable[-1]
        if self._page is None or self._page.is_closed() or chosen != self._page:
            reason = "apply/auth tab detected" if apply_pages else "newest open tab"
            await self._focus_page(chosen, reason=reason)
        else:
            # Same tab may have navigated off Glassdoor/Indeed without a focus change.
            self._maybe_report_escape(chosen.url, via="employer_site")
        assert self._page is not None
        return self._page

    async def _with_live_page(self, action_name: str, fn: Any) -> Any:
        """Run a mouse/keyboard action; recover once if the tab closed mid-action."""
        self._raise_if_escape_duplicate()
        page = await self._sync_active_page()
        try:
            return await fn(page)
        except EscapeDuplicateAbort:
            raise
        except Exception as exc:
            if "TargetClosed" not in exc.__class__.__name__ and "Target closed" not in str(exc):
                raise
            print(f"{action_name}: tab closed mid-action; switching to another tab", flush=True)
            page = await self._sync_active_page()
            return await fn(page)

    @property
    def page(self) -> Page:
        assert self._page is not None
        return self._page

    @property
    def dimensions(self) -> tuple[int, int]:
        return (1280, 800)

    async def screenshot(self) -> str:
        self._raise_if_escape_duplicate()
        page = await self._sync_active_page()
        # Do not wait for captcha here — invisible widgets exist early on many ATS
        # pages and would stall the whole fill flow. Solver wait is armed after Submit.
        await self._try_attach_resume()
        # Viewport only for the model — full-page evidence is captured separately for Landed.
        png_bytes = await page.screenshot(full_page=False)
        return base64.b64encode(png_bytes).decode("utf-8")

    async def capture_full_page_jpeg(self) -> tuple[bytes, str] | None:
        """Full document screenshot (scroll height), JPEG, sized for Landed artifacts."""
        try:
            page = await self._sync_active_page()
        except Exception:
            return None
        if page.is_closed():
            return None
        url = page.url or ""
        # Scroll to top so the stitch starts at the document head.
        try:
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.2)
        except Exception:
            pass
        for quality in (80, 65, 50, 35):
            try:
                data = await page.screenshot(
                    full_page=True,
                    type="jpeg",
                    quality=quality,
                    timeout=30_000,
                )
            except Exception as exc:
                print(f"Full-page screenshot failed (q={quality}): {exc}", flush=True)
                continue
            if not data:
                continue
            if len(data) <= _MAX_ARTIFACT_BYTES:
                print(
                    f"Full-page screenshot: {len(data)} bytes (jpeg q={quality})",
                    flush=True,
                )
                return data, url
            print(
                f"Full-page screenshot {len(data)} bytes exceeds Landed limit; "
                f"retrying lower quality (was q={quality})",
                flush=True,
            )
        print("Full-page screenshot could not fit under Landed 15MB limit.", flush=True)
        return None

    async def capture_page_evidence(self) -> dict[str, Any]:
        """Page text + URLs for Landed SubmissionVerifier (finish confirmation)."""
        out: dict[str, Any] = {
            "pageText": "",
            "url": None,
            "urlBefore": clean_job_url(self._url_before_submit),
            "validationMessages": [],
            "invalidCount": 0,
            "blocked": None,
        }
        try:
            page = await self._sync_active_page()
        except Exception:
            out["url"] = evidence_job_url(
                current_url=None,
                start_url=self._start_url,
                url_before_submit=self._url_before_submit,
            )
            return out
        if page.is_closed():
            out["url"] = evidence_job_url(
                current_url=None,
                start_url=self._start_url,
                url_before_submit=self._url_before_submit,
            )
            return out

        current = ""
        try:
            current = page.url or ""
        except Exception:
            current = ""

        # If the active tab drifted to a different/alt job, prefer an apply tab for text.
        if is_post_apply_noise_url(current) or (
            evidence_job_url(
                current_url=current,
                start_url=self._start_url,
                url_before_submit=self._url_before_submit,
            )
            != clean_job_url(current)
        ):
            better = self._best_evidence_page()
            if better is not None and better != page and not better.is_closed():
                page = better
                try:
                    current = page.url or current
                except Exception:
                    pass

        out["url"] = evidence_job_url(
            current_url=current,
            start_url=self._start_url,
            url_before_submit=self._url_before_submit,
        )
        try:
            text = await page.evaluate(
                """() => {
                  const t = (document.body && document.body.innerText) || '';
                  return t.replace(/\\s+/g, ' ').trim().slice(0, 12000);
                }"""
            )
            if isinstance(text, str):
                out["pageText"] = text
        except Exception as exc:
            print(f"Page evidence text capture failed: {exc}", flush=True)
        return out

    def _best_evidence_page(self) -> Page | None:
        """Prefer apply/form tabs over listing pages for confirmation text."""
        if self._context is None:
            return None
        pages = [
            p
            for p in self._context.pages
            if not p.is_closed()
            and not _is_blank_url(p.url)
            and not is_post_apply_noise_url(p.url)
        ]
        if not pages:
            return None
        apply_pages = [p for p in pages if _is_apply_like_url(p.url)]
        if apply_pages:
            return apply_pages[-1]
        if self._page is not None and not self._page.is_closed():
            if not is_post_apply_noise_url(self._page.url):
                return self._page
        return pages[-1]

    async def _remember_focus_meta(self, page: Page) -> None:
        try:
            meta = await page.evaluate(FOCUS_META_JS)
        except Exception:
            return
        if isinstance(meta, dict) and str(meta.get("label") or "").strip():
            self._last_focus_meta = meta

    def _record_typed_text(self, text: str) -> None:
        raw = str(text or "")
        if not raw.strip():
            return
        meta = self._last_focus_meta or {}
        label = str(meta.get("label") or "field").strip() or "field"
        field_type = str(meta.get("fieldType") or "text").strip().lower() or "text"
        name = str(meta.get("name") or "").strip() or None
        selector = str(meta.get("selector") or "").strip() or None
        key = (name or label).lower()
        if field_type == "password":
            value = PASSWORD_REDACTED
        else:
            prev = self._typed_fills.get(key) or {}
            prev_text = str(prev.get("text") or "")
            if prev_text == PASSWORD_REDACTED:
                value = PASSWORD_REDACTED
            else:
                value = (prev_text + raw)[:2000]
        self._typed_fills[key] = {
            "label": label,
            "text": value,
            "fieldType": field_type,
            "name": name,
            "selector": selector,
        }

    async def scrape_filled_controls(self) -> list[dict[str, Any]]:
        """DOM scrape of non-empty form controls (authoritative fill snapshot)."""
        try:
            page = await self._sync_active_page()
        except Exception:
            return []
        if page.is_closed():
            return []
        try:
            rows = await page.evaluate(SCRAPE_FILLED_JS)
        except Exception as exc:
            print(f"Fill scrape failed: {exc}", flush=True)
            return []
        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict)]

    async def get_fill_outcomes(self) -> list[dict[str, Any]]:
        """Merge typed log + DOM scrape into Landed fill outcomes."""
        scraped = await self.scrape_filled_controls()
        typed = list(self._typed_fills.values())
        outcomes = merge_fill_outcomes(scraped, typed, source=FILL_SOURCE)
        return outcomes

    def _normalize_keys(self, keys: list[str] | None) -> list[str]:
        if not keys:
            return []
        return [CUA_KEY_TO_PLAYWRIGHT_KEY.get(key.lower(), key) for key in keys]

    @asynccontextmanager
    async def _hold_keys(self, keys: list[str] | None) -> AsyncIterator[None]:
        mapped_keys = self._normalize_keys(keys)
        page = self.page
        try:
            for key in mapped_keys:
                await page.keyboard.down(key)
            yield
        finally:
            for key in reversed(mapped_keys):
                await page.keyboard.up(key)

    async def click(
        self, x: int, y: int, button: Button = "left", *, keys: list[str] | None = None
    ) -> None:
        playwright_button: Literal["left", "middle", "right"] = "left"
        if button in ("left", "right", "middle"):
            playwright_button = button  # type: ignore[assignment]

        async def _do(page: Page) -> None:
            # Attach via hidden <input type=file> before the click when possible so
            # a native OS dialog never opens and blocks headed Camoufox.
            await self._try_attach_resume()
            submit_like = await self._click_looks_like_submit(page, x, y)
            final_submit = await self._click_looks_like_final_submit(page, x, y)
            upload_like = await self._click_looks_like_upload(page, x, y)
            if submit_like:
                try:
                    self._url_before_submit = page.url
                except Exception:
                    self._url_before_submit = None
            # Evidence for Landed: capture the filled form BEFORE Submit (post-submit
            # pages often redirect to unrelated "similar jobs" listings).
            if final_submit:
                await self._capture_pre_submit_screenshot()

            async with self._hold_keys(keys):
                await page.mouse.click(x, y, button=playwright_button)

            await asyncio.sleep(0.35)
            page = await self._sync_active_page()
            await self._remember_focus_meta(page)
            await self._try_attach_resume()
            # Re-clicking Upload after attach often opens a native picker that
            # Playwright cannot always auto-close — Escape only for upload clicks.
            if self._resume_attached and upload_like:
                await self._dismiss_file_dialog()
            # Only arm on Submit/Continue clicks. Many ATS pages (JazzHR) keep a
            # visible reCAPTCHA on the form the whole time — arming on presence
            # blocks the agent for 90s before fields are filled.
            if submit_like:
                self._captcha_armed = True
                self._captcha_wait_exhausted = False
                await self._resolve_captcha_if_needed(page)

        await self._with_live_page("click", _do)

    async def double_click(self, x: int, y: int, *, keys: list[str] | None = None) -> None:
        async def _do(page: Page) -> None:
            await self._try_attach_resume()
            async with self._hold_keys(keys):
                await page.mouse.dblclick(x, y)
            await self._try_attach_resume()

        await self._with_live_page("double_click", _do)

    async def scroll(
        self,
        x: int,
        y: int,
        scroll_x: int,
        scroll_y: int,
        *,
        keys: list[str] | None = None,
    ) -> None:
        async def _do(page: Page) -> None:
            async with self._hold_keys(keys):
                await page.mouse.move(x, y)
                await page.evaluate(f"window.scrollBy({scroll_x}, {scroll_y})")

        await self._with_live_page("scroll", _do)

    async def type(self, text: str) -> None:
        async def _do(page: Page) -> None:
            await self._remember_focus_meta(page)
            await page.keyboard.type(text)
            self._record_typed_text(text)

        await self._with_live_page("type", _do)

    async def _click_looks_like_submit(self, page: Page, x: int, y: int) -> bool:
        """True when the click target is Submit / Apply / Continue (captcha often follows)."""
        try:
            return bool(
                await page.evaluate(
                    """([x, y]) => {
                      const el = document.elementFromPoint(x, y);
                      if (!el) return false;
                      const chain = [];
                      let n = el;
                      for (let i = 0; i < 5 && n; i++, n = n.parentElement) chain.push(n);
                      const blob = chain.map((node) => [
                        node.innerText || '',
                        node.value || '',
                        node.getAttribute?.('aria-label') || '',
                        node.getAttribute?.('name') || '',
                        node.id || '',
                        node.type || '',
                      ].join(' ')).join(' ').toLowerCase();
                      if (/\\b(submit|apply now|submit application|send application|finish|complete application|continue|next|verify)\\b/.test(blob)) {
                        return true;
                      }
                      return chain.some((node) => (node.type || '').toLowerCase() === 'submit');
                    }""",
                    [x, y],
                )
            )
        except Exception:
            return False

    async def _click_looks_like_final_submit(self, page: Page, x: int, y: int) -> bool:
        """True for Submit/Apply (not Continue/Next) — used for pre-submit screenshots."""
        try:
            return bool(
                await page.evaluate(
                    """([x, y]) => {
                      const el = document.elementFromPoint(x, y);
                      if (!el) return false;
                      const chain = [];
                      let n = el;
                      for (let i = 0; i < 5 && n; i++, n = n.parentElement) chain.push(n);
                      const blob = chain.map((node) => [
                        node.innerText || '',
                        node.value || '',
                        node.getAttribute?.('aria-label') || '',
                        node.getAttribute?.('name') || '',
                        node.id || '',
                        node.type || '',
                      ].join(' ')).join(' ').toLowerCase();
                      if (/\\b(submit application|send application|complete application|apply now|submit)\\b/.test(blob)) {
                        return true;
                      }
                      return chain.some((node) => (node.type || '').toLowerCase() === 'submit');
                    }""",
                    [x, y],
                )
            )
        except Exception:
            return False

    async def _capture_pre_submit_screenshot(self) -> None:
        """Upload a full-page JPEG of the filled form once, before Submit is clicked."""
        if self._pre_submit_screenshot_taken or self._on_full_page_screenshot is None:
            return
        captured = await self.capture_full_page_jpeg()
        if not captured:
            return
        data, url = captured
        meta: dict[str, Any] = {
            "url": clean_job_url(url) or url,
            "content_type": "image/jpeg",
            "filename": f"pre-submit-{int(time.time())}.jpg",
            "kind": "screenshot",
            "bytes": len(data),
            "full_page": True,
            "pre_submit": True,
        }
        try:
            self._on_full_page_screenshot(data, meta)
            self._pre_submit_screenshot_taken = True
            print("Captured full-page screenshot before Submit.", flush=True)
        except Exception as exc:
            print(f"Pre-submit screenshot callback failed: {exc}", flush=True)

    async def _click_looks_like_upload(self, page: Page, x: int, y: int) -> bool:
        """True when the click target is Upload / Attach / Choose file (opens OS picker)."""
        try:
            return bool(
                await page.evaluate(
                    """([x, y]) => {
                      const el = document.elementFromPoint(x, y);
                      if (!el) return false;
                      const chain = [];
                      let n = el;
                      for (let i = 0; i < 5 && n; i++, n = n.parentElement) chain.push(n);
                      const blob = chain.map((node) => [
                        node.innerText || '',
                        node.value || '',
                        node.getAttribute?.('aria-label') || '',
                        node.getAttribute?.('name') || '',
                        node.id || '',
                        node.className || '',
                        node.type || '',
                        node.tagName || '',
                      ].join(' ')).join(' ').toLowerCase();
                      if (/\\b(upload|attach|choose file|browse|select file|drop.*(resume|cv|file)|resume.*upload)\\b/.test(blob)) {
                        return true;
                      }
                      return chain.some((node) => (node.type || '').toLowerCase() === 'file');
                    }""",
                    [x, y],
                )
            )
        except Exception:
            return False

    _DETECT_CAPTCHA_JS = """() => {
      const visible = (el) => {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        if (r.width < 20 || r.height < 20) return false;
        const st = window.getComputedStyle(el);
        return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
      };
      const src = (el) => (el.getAttribute('src') || '').toLowerCase();
      for (const f of document.querySelectorAll('iframe')) {
        if (!visible(f)) continue;
        if (f.closest('.grecaptcha-badge')) continue;
        const s = src(f);
        const hasCaptchaToken = () => [...document.querySelectorAll(
          'textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]'
        )].some((el) => (el.value || '').length > 40);
        // Checkbox / bframe challenge — not the tiny corner badge.
        // Token filled (NopeCHA) ⇒ treated as clear even though the anchor iframe stays.
        if (s.includes('recaptcha') && (s.includes('/anchor') || s.includes('/bframe') || f.offsetWidth >= 100)) {
          if (hasCaptchaToken()) continue;
          return 'RECAPTCHA';
        }
        if (s.includes('hcaptcha') && f.offsetWidth >= 100) {
          if (hasCaptchaToken()) continue;
          return 'HCAPTCHA';
        }
        if ((s.includes('challenges.cloudflare.com') || s.includes('turnstile')) && f.offsetWidth >= 100) {
          // Token filled (NopeCHA / checkbox click) ⇒ clear even if iframe stays.
          const hasTurnstileToken = () => [...document.querySelectorAll(
            'input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'
          )].some((el) => (el.value || '').length > 20);
          if (hasTurnstileToken()) continue;
          return 'TURNSTILE';
        }
        if (s.includes('captcha-delivery.com')) return 'DATADOME';
      }
      // Full-page Cloudflare interstitial (not a buried footer phrase).
      const body = (document.body && document.body.innerText || '').trim();
      if (body.length < 800) {
        const lower = body.toLowerCase();
        if (lower.includes('verify you are human') || lower.includes('just a moment')) {
          return 'CLOUDFLARE_INTERSTITIAL';
        }
        if (lower.includes('checking your browser before accessing')) {
          return 'CLOUDFLARE_INTERSTITIAL';
        }
      }
      return null;
    }"""

    async def _iter_frames(self, page: Page) -> list[Frame]:
        """Main page first, then child frames (iCIMS/Glassdoor nest the form)."""
        frames: list[Frame] = []
        try:
            frames.append(page.main_frame)
        except Exception:
            pass
        for frame in page.frames:
            if frame not in frames:
                frames.append(frame)
        return frames

    async def _detect_interactive_captcha(self, page: Page) -> str | None:
        """Visible interactive challenge only — ignore badges / invisible widgets / early sitekeys.

        Checks every frame: ATS hosts (iCIMS, etc.) often put hCaptcha inside a nested iframe
        the top document cannot see with querySelectorAll.
        """
        found: str | None = None
        for frame in await self._iter_frames(page):
            try:
                kind = await frame.evaluate(self._DETECT_CAPTCHA_JS)
            except Exception:
                continue
            if isinstance(kind, str) and kind:
                found = kind
                break
        # Token may live on a different frame than the widget iframe (JazzHR/reCAPTCHA).
        if found in {"RECAPTCHA", "HCAPTCHA"} and await self._captcha_token_present_any(page):
            return None
        return found

    async def _hcaptcha_token_present(self, target: Page | Frame) -> bool:
        try:
            return bool(
                await target.evaluate(
                    """() => [...document.querySelectorAll(
                      'textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]'
                    )].some((el) => (el.value || '').length > 40)"""
                )
            )
        except Exception:
            return False

    async def _captcha_token_present_any(self, page: Page) -> bool:
        for frame in await self._iter_frames(page):
            if await self._hcaptcha_token_present(frame):
                return True
        return False

    async def _click_submit_again(self, page: Page) -> bool:
        """Re-click Submit/Apply after token inject (Lever often needs a second submit)."""
        script = """() => {
          const nodes = [...document.querySelectorAll(
            'button, input[type="submit"], [role="button"], a'
          )];
          const match = nodes.find((el) => {
            const t = (
              (el.innerText || el.value || el.getAttribute('aria-label') || '')
            ).toLowerCase();
            return /submit application|submit|apply now|send application|continue|next/.test(t)
              && !el.disabled;
          });
          if (!match) return false;
          match.click();
          return true;
        }"""
        for frame in await self._iter_frames(page):
            try:
                if await frame.evaluate(script):
                    return True
            except Exception:
                continue
        return False

    async def _find_hcaptcha_context(
        self, page: Page
    ) -> tuple[Frame, dict[str, Any]] | None:
        """Frame that hosts the widget + extracted sitekey metadata."""
        for frame in await self._iter_frames(page):
            try:
                meta = await frame.evaluate(EXTRACT_HCAPTCHA_JS)
            except Exception:
                continue
            if isinstance(meta, dict) and meta.get("sitekey"):
                return frame, meta
        return None

    async def _solve_hcaptcha_with_nonecap(self, page: Page) -> bool:
        """Mint a P1_ token via NoneCap and inject it into the form. Returns True on success."""
        if not nonecap_enabled():
            return False
        found = await self._find_hcaptcha_context(page)
        if not found:
            print("NoneCap: no hCaptcha sitekey on page (checked all frames).", flush=True)
            return False
        frame, meta = found

        sitekey = str(meta["sitekey"])
        rqdata = meta.get("rqdata") or None
        user_agent = str(meta.get("userAgent") or "") or None
        # Prefer the frame URL (iCIMS embed) so the token matches the host that loads the widget.
        solve_url = frame.url or page.url
        print(
            f"NoneCap: solving hCaptcha sitekey={sitekey[:8]}… "
            f"({'enterprise' if rqdata else 'standard'}; ua=browser; frame={solve_url[:80]})",
            flush=True,
        )
        try:
            # urllib is sync — run off the event loop so the UI stays responsive.
            solve = await asyncio.to_thread(
                solve_hcaptcha,
                sitekey=sitekey,
                url=solve_url,
                rqdata=str(rqdata) if rqdata else None,
                user_agent=user_agent,
            )
        except Exception as exc:
            print(f"NoneCap solve failed: {exc}", flush=True)
            return False

        token = str(solve.get("token") or "")
        resp_key = solve.get("resp_key") or None
        if not token:
            print("NoneCap: empty token in response.", flush=True)
            return False

        # Camoufox: ``mw:`` scripts must be self-contained IIFEs — Playwright args
        # are not passed through the main-world bridge (that caused filled=False).
        script = build_inject_token_script(token, str(resp_key) if resp_key else None)
        inject_result: Any = None
        try:
            inject_result = await frame.evaluate("mw:" + script)
        except Exception as mw_exc:
            print(f"NoneCap: main-world inject failed ({mw_exc}); trying page world…", flush=True)
            try:
                inject_result = await frame.evaluate(script)
            except Exception as exc:
                print(f"NoneCap: token inject failed: {exc}", flush=True)
                return False

        filled = bool(
            (isinstance(inject_result, dict) and inject_result.get("filled"))
            or await self._hcaptcha_token_present(frame)
        )
        print(
            f"NoneCap: injected hCaptcha token (solve_id={solve.get('id')}, "
            f"filled={filled}, resp_key={'yes' if resp_key else 'no'}, "
            f"result={inject_result!r}).",
            flush=True,
        )
        if not filled:
            print(
                "NoneCap: token fields still empty after inject — page may block writes.",
                flush=True,
            )
            return False

        # Lever shows the image puzzle until submit is retried with the token present.
        await asyncio.sleep(0.5)
        if await self._click_submit_again(page):
            print("NoneCap: re-clicked Submit after token inject.", flush=True)
            await asyncio.sleep(1.5)
        return True

    async def _click_recaptcha_checkbox(self, page: Page) -> bool:
        """Open the reCAPTCHA challenge so NopeCHA (auto_solve, not auto_open) can run.

        Called only after Submit/Continue arms the solver — avoids early tokens that expire.
        """
        if await self._captcha_token_present_any(page):
            return True
        # Prefer the anchor iframe checkbox (standard v2).
        for frame in page.frames:
            try:
                url = (frame.url or "").lower()
            except Exception:
                continue
            if "recaptcha" not in url or "anchor" not in url:
                continue
            for sel in ("#recaptcha-anchor", ".recaptcha-checkbox-border", ".recaptcha-checkbox"):
                try:
                    loc = frame.locator(sel).first
                    if await loc.count() == 0:
                        continue
                    await loc.click(timeout=3000)
                    print("Opened reCAPTCHA checkbox for NopeCHA (post-submit).", flush=True)
                    await asyncio.sleep(0.8)
                    return True
                except Exception:
                    continue
        # Fallback: click the visible recaptcha iframe from the parent document.
        try:
            clicked = await page.evaluate(
                """() => {
                  const frames = [...document.querySelectorAll('iframe')].filter((f) => {
                    const s = (f.getAttribute('src') || '').toLowerCase();
                    return s.includes('recaptcha') && s.includes('/anchor') && f.offsetWidth >= 100;
                  });
                  const f = frames[0];
                  if (!f) return false;
                  f.scrollIntoView({block: 'center'});
                  const r = f.getBoundingClientRect();
                  const x = r.left + Math.min(28, r.width / 2);
                  const y = r.top + r.height / 2;
                  const el = document.elementFromPoint(x, y) || f;
                  el.dispatchEvent(new MouseEvent('click', {bubbles: true, clientX: x, clientY: y}));
                  return true;
                }"""
            )
            if clicked:
                print("Clicked reCAPTCHA iframe (fallback) for NopeCHA.", flush=True)
                await asyncio.sleep(0.8)
                return True
        except Exception:
            pass
        return False

    async def _turnstile_token_present(self, target: Page | Frame) -> bool:
        try:
            return bool(
                await target.evaluate(
                    """() => [...document.querySelectorAll(
                      'input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'
                    )].some((el) => (el.value || '').length > 20)"""
                )
            )
        except Exception:
            return False

    async def _turnstile_token_present_any(self, page: Page) -> bool:
        for frame in await self._iter_frames(page):
            if await self._turnstile_token_present(frame):
                return True
        return False

    async def _click_cloudflare_checkbox(self, page: Page) -> bool:
        """Click the Cloudflare Turnstile / interstitial 'Verify you are human' checkbox.

        NopeCHA solves the follow-up when needed; Camoufox still needs a real mouse
        click on the widget (closed shadow DOM blocks DOM .click() alone).
        """
        if await self._turnstile_token_present_any(page):
            return True

        # Try accessibility / light-DOM checkbox inside the Turnstile iframe.
        for frame in page.frames:
            try:
                url = (frame.url or "").lower()
            except Exception:
                continue
            if "challenges.cloudflare.com" not in url and "turnstile" not in url:
                continue
            for sel in (
                '[role="checkbox"]',
                'input[type="checkbox"]',
                ".ctp-checkbox-label",
                "#challenge-stage",
                "label",
            ):
                try:
                    loc = frame.locator(sel).first
                    if await loc.count() == 0:
                        continue
                    if not await loc.is_visible():
                        continue
                    await loc.click(timeout=3000, force=True)
                    print("Clicked Cloudflare Turnstile checkbox (frame).", flush=True)
                    await asyncio.sleep(0.8)
                    return True
                except Exception:
                    continue

        # Trusted mouse click on the checkbox (left side of the visible iframe).
        try:
            box = await page.evaluate(
                """() => {
                  const frames = [...document.querySelectorAll('iframe')].filter((f) => {
                    const s = (f.getAttribute('src') || '').toLowerCase();
                    const r = f.getBoundingClientRect();
                    return (s.includes('challenges.cloudflare.com') || s.includes('turnstile'))
                      && r.width >= 100 && r.height >= 20
                      && window.getComputedStyle(f).visibility !== 'hidden';
                  });
                  const f = frames[0];
                  if (!f) return null;
                  f.scrollIntoView({block: 'center'});
                  const r = f.getBoundingClientRect();
                  return {
                    x: r.left + Math.min(28, Math.max(12, r.width * 0.12)),
                    y: r.top + r.height / 2,
                  };
                }"""
            )
            if isinstance(box, dict) and "x" in box and "y" in box:
                x, y = float(box["x"]), float(box["y"])
                await page.mouse.click(x, y)
                print(
                    f"Clicked Cloudflare Turnstile iframe at ({int(x)}, {int(y)}).",
                    flush=True,
                )
                await asyncio.sleep(0.8)
                return True
        except Exception:
            pass

        # Interstitial: click any visible "Verify you are human" control on the page.
        try:
            for sel in (
                'text="Verify you are human"',
                'role=checkbox[name=/verify you are human/i]',
                'label:has-text("Verify you are human")',
            ):
                try:
                    loc = page.locator(sel).first
                    if await loc.count() == 0:
                        continue
                    if not await loc.is_visible():
                        continue
                    await loc.click(timeout=3000)
                    print("Clicked Cloudflare interstitial verify control.", flush=True)
                    await asyncio.sleep(0.8)
                    return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    async def _wait_for_nopecha_if_needed(self, page: Page, *, kind: str) -> bool:
        """Poll until NopeCHA clears the challenge. Returns True if cleared."""
        cloudflare = kind in {"TURNSTILE", "CLOUDFLARE_INTERSTITIAL"}
        # Cloudflare managed mode often clears from a checkbox click alone;
        # still attempt that when NopeCHA is disabled.
        if not self._nopecha_addons and not cloudflare:
            return False
        if kind == "RECAPTCHA":
            await self._click_recaptcha_checkbox(page)
        elif cloudflare:
            await self._click_cloudflare_checkbox(page)
        timeout_ms = nopecha_solve_timeout_ms()
        solver = "NopeCHA" if self._nopecha_addons else "checkbox click"
        print(
            f"Captcha after submit ({kind}) — waiting up to {timeout_ms // 1000}s for {solver} "
            "(agent must not solve it).",
            flush=True,
        )
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        last: str | None = kind
        opened_again = False
        started = time.monotonic()
        while time.monotonic() < deadline:
            if page.is_closed():
                return False
            await asyncio.sleep(1.0)
            # Prefer token presence — reCAPTCHA/hCaptcha iframes often stay mounted after solve.
            if kind in {"RECAPTCHA", "HCAPTCHA"} and await self._captcha_token_present_any(page):
                print("Captcha cleared.", flush=True)
                return True
            if kind in {"TURNSTILE", "CLOUDFLARE_INTERSTITIAL"} and (
                await self._turnstile_token_present_any(page)
            ):
                print("Captcha cleared.", flush=True)
                return True
            last = await self._detect_interactive_captcha(page)
            if not last:
                print("Captcha cleared.", flush=True)
                return True
            # If still stuck on checkbox-only, try opening once more ~15s in.
            if (
                kind in {"RECAPTCHA", "TURNSTILE", "CLOUDFLARE_INTERSTITIAL"}
                and not opened_again
                and (time.monotonic() - started) >= 15
            ):
                opened_again = True
                if kind == "RECAPTCHA":
                    await self._click_recaptcha_checkbox(page)
                else:
                    await self._click_cloudflare_checkbox(page)
        print(
            f"NopeCHA did not clear {last or kind} within {timeout_ms // 1000}s. "
            "Check NOPECHA_API_KEY / credits, or solve it yourself in the window.",
            flush=True,
        )
        return False

    async def _resolve_captcha_if_needed(self, page: Page) -> None:
        """After submit-ready: NoneCap for hCaptcha, else NopeCHA wait for other kinds."""
        if not self._captcha_armed or self._captcha_wait_exhausted:
            return
        kind = await self._detect_interactive_captcha(page)
        if not kind:
            return

        if kind == "HCAPTCHA":
            # hCaptcha is NoneCap-only — NopeCHA no longer solves it (same as landed).
            ok = await self._solve_hcaptcha_with_nonecap(page)
            if ok:
                self._captcha_armed = False
            else:
                self._captcha_wait_exhausted = True
                if not nonecap_enabled():
                    print(
                        "hCaptcha detected but NONECAP_KEY is not set. "
                        "Add NONECAP_KEY=nc_live_… to .env (https://dashboard.nonecap.com).",
                        flush=True,
                    )
                else:
                    print(
                        "NoneCap could not clear hCaptcha. "
                        "Check credits at https://dashboard.nonecap.com or solve it in the window.",
                        flush=True,
                    )
            return

        cleared = await self._wait_for_nopecha_if_needed(page, kind=kind)
        if cleared:
            self._captcha_armed = False
            # JazzHR etc. need the token present before Submit succeeds — retry click.
            if await self._click_submit_again(page):
                print("Re-clicked Submit after NopeCHA cleared captcha.", flush=True)
                await asyncio.sleep(1.0)
        else:
            self._captcha_wait_exhausted = True

    async def wait(self) -> None:
        page = await self._sync_active_page()
        # Mid-flow gates only (iCIMS hCaptcha, Cloudflare wall). Do NOT arm always-on
        # form reCAPTCHA here — those expire if solved before the form is complete.
        kind = await self._detect_interactive_captcha(page)
        gate_kinds = {"HCAPTCHA", "TURNSTILE", "CLOUDFLARE_INTERSTITIAL", "DATADOME"}
        if kind in gate_kinds and not self._captcha_wait_exhausted:
            if not self._captcha_armed:
                print(f"Captcha gate during wait ({kind}) — arming solver.", flush=True)
            self._captcha_armed = True
            await self._resolve_captcha_if_needed(page)
        elif self._captcha_armed:
            await self._resolve_captcha_if_needed(page)
        await asyncio.sleep(1)
        await self._try_attach_resume()

    async def move(self, x: int, y: int, *, keys: list[str] | None = None) -> None:
        page = await self._sync_active_page()
        async with self._hold_keys(keys):
            await page.mouse.move(x, y)

    async def keypress(self, keys: list[str]) -> None:
        page = await self._sync_active_page()
        mapped_keys = self._normalize_keys(keys)
        for key in mapped_keys:
            await page.keyboard.down(key)
        for key in reversed(mapped_keys):
            await page.keyboard.up(key)

    async def drag(self, path: list[tuple[int, int]], *, keys: list[str] | None = None) -> None:
        if not path:
            return
        page = await self._sync_active_page()
        async with self._hold_keys(keys):
            await page.mouse.move(path[0][0], path[0][1])
            await page.mouse.down()
            for px, py in path[1:]:
                await page.mouse.move(px, py)
            await page.mouse.up()


# Exit codes from run_local_apply (worker maps these to Landed finish outcomes).
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_LOGIN = 2
EXIT_NEEDS_HUMAN = 3
EXIT_DUPLICATE = 4
# Job posting closed / expired / removed — Landed failed_permanent + adapter.posting_expired
EXIT_POSTING_UNAVAILABLE = 5

# Match Landed browser-worker looksExpired (services/browser-worker/.../blockers.js).
_POSTING_UNAVAILABLE_RE = re.compile(
    r"no longer (accepting applications|available|open)|"
    r"this (job|position|posting) (is|has been) (closed|filled|removed)|"
    r"job (not found|has expired)|"
    r"page (not found|you requested could not be found)|"
    r"(that|this) (page|job|posting) (is|has) gone|"
    r"position has been filled|"
    r"no longer accepting|"
    r"posting (is )?(closed|expired|unavailable)",
    flags=re.IGNORECASE,
)


def looks_posting_unavailable(text: str | None) -> bool:
    """True when page/agent text says the listing is closed, expired, or gone."""
    return bool(_POSTING_UNAVAILABLE_RE.search(str(text or "")))


def _agent_reported_posting_unavailable(text: str) -> bool:
    """True when the final report marks the posting as unavailable/closed/expired."""
    t = text or ""
    if re.search(
        r"\*\*Posting status:\*\*\s*(unavailable|closed|expired|filled|removed|gone)\b",
        t,
        flags=re.IGNORECASE,
    ):
        return True
    if looks_posting_unavailable(t) and re.search(
        r"\*\*Application submitted:\*\*\s*No\b",
        t,
        flags=re.IGNORECASE,
    ):
        return True
    return False


def _agent_reported_not_submitted(text: str) -> bool:
    """True when the final report indicates the form was not submitted / needs a human."""
    t = text or ""
    if _agent_reported_posting_unavailable(t):
        return False
    if re.search(r"\*\*Application submitted:\*\*\s*No\b", t, flags=re.IGNORECASE):
        return True
    if re.search(r"\*\*Blocked:\*\*", t, flags=re.IGNORECASE):
        return True
    if re.search(
        r"\b(did not submit|was not submitted|left (it|the field) unanswered|"
        r"recorded as pending|needs? (your|human|user) (help|answer)|"
        r"cannot be completed safely|stop and report)\b",
        t,
        flags=re.IGNORECASE,
    ):
        return True
    return False


async def save_browser_login(
    *,
    profile_dir: Path | None = None,
    storage_state: Path | None = None,
    start_url: str | None = None,
) -> Path:
    """Open Camoufox once so you can sign in; cookies are saved for later apply runs."""
    profile = profile_dir or Path(os.getenv("BROWSER_PROFILE", str(DEFAULT_PROFILE_DIR)))
    state_path = storage_state or DEFAULT_STORAGE_STATE
    url = (start_url or os.getenv("LOGIN_START_URL") or "https://accounts.google.com").strip()

    addons = _resolve_nopecha_addons()
    print(f"Opening Camoufox profile at: {profile.resolve()}", flush=True)
    print(f"Start URL: {url}", flush=True)
    print("1) If a captcha appears, wait for NopeCHA (do not solve it yourself)", flush=True)
    print("2) Sign in to Google and any job boards you need for applications", flush=True)
    print("3) When done, press Enter here to save cookies", flush=True)

    async with AsyncCamoufox(**_camoufox_kwargs(profile, addons=addons)) as context:
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.to_thread(
            input, "Press Enter after Cloudflare + sign-in is complete..."
        )
        await context.storage_state(path=str(state_path))

    print(f"Saved login cookies to {state_path.resolve()}", flush=True)
    print(f"Persistent Camoufox profile kept at {profile.resolve()}", flush=True)
    return state_path


def _usage_from_result(result: Any) -> dict[str, int]:
    usage = {
        "input_tokens": 0,
        "cached_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }
    context = getattr(result, "context_wrapper", None) or getattr(result, "context", None)
    raw = getattr(context, "usage", None) if context is not None else None
    if raw is None:
        raw = getattr(result, "usage", None)
    if raw is None:
        return usage
    usage["input_tokens"] = int(getattr(raw, "input_tokens", 0) or 0)
    usage["output_tokens"] = int(getattr(raw, "output_tokens", 0) or 0)
    usage["total_tokens"] = int(
        getattr(raw, "total_tokens", 0) or usage["input_tokens"] + usage["output_tokens"]
    )
    details = getattr(raw, "input_tokens_details", None)
    if details is not None:
        usage["cached_tokens"] = int(getattr(details, "cached_tokens", 0) or 0)
    return usage


async def run_local_apply(
    *,
    model: str,
    config: ApplyConfig,
    costs_path: str = "costs.json",
    profile_dir: str | None = None,
    on_escape_aggregator: EscapeAggregatorCallback | None = None,
    on_full_page_screenshot: FullPageScreenshotCallback | None = None,
    page_evidence_out: dict[str, Any] | None = None,
    landed_client: LandedClient | None = None,
    application_id: str | None = None,
    company: str | None = None,
) -> int:
    profile = Path(profile_dir or os.getenv("BROWSER_PROFILE", str(DEFAULT_PROFILE_DIR)))
    has_login = DEFAULT_STORAGE_STATE.exists() or (profile.exists() and any(profile.iterdir()))

    if not has_login:
        print(
            "No saved browser login found.\n"
            "Run once with: python -m computer_use.apply --login",
            flush=True,
        )
        return 2

    max_turns = int(os.getenv("MAX_TURNS", "80"))
    print(f"Job URL: {config.job_url}", flush=True)
    print(f"Resume:  {config.resume_path}", flush=True)
    print(f"Submit:  {config.submit}", flush=True)
    open_resume_preview(config.resume_path)
    print("Opening headed Camoufox (live window)...", flush=True)
    print(f"Max agent turns: {max_turns}", flush=True)

    app_id = str(application_id or "").strip()
    company_name = str(company or "").strip() or None
    verification_since: str | None = None
    on_verification_step = None
    if landed_client is not None and app_id:
        verification_since = utc_now_iso()
        print(
            f"Verification codes: Gmail poll enabled "
            f"(application={app_id}, since={verification_since}"
            f"{f', company={company_name}' if company_name else ''})",
            flush=True,
        )

        def _verification_step(status: str, detail: dict[str, Any]) -> None:
            try:
                landed_client.step(
                    app_id,
                    name="verification_code",
                    status=status,
                    detail=detail,
                )
            except Exception as exc:
                print(f"verification_code step failed (continuing): {exc}", flush=True)

        on_verification_step = _verification_step

    feature_ctx = ApplyRunContext(
        job_url=config.job_url,
        profile=config.profile or {},
        company=company_name,
        account_signup=config.account_signup,
        submit=config.submit,
        resume_path=str(config.resume_path),
        landed_client=landed_client,
        application_id=app_id or None,
        verification_since=verification_since,
        on_verification_step=on_verification_step,
    )
    composed = compose(feature_ctx)
    if composed.names:
        print(f"Features: {', '.join(composed.names)}", flush=True)

    prompt = build_prompt(
        job_url=config.job_url,
        resume_path=str(config.resume_path),
        submit_application=config.submit,
        profile=config.profile,
        feature_user_blocks=composed.user_blocks,
    )
    instructions = build_system_instructions(
        feature_system=composed.system_instructions
    )

    exit_code = 0
    result: Any = None
    run_hooks = make_apply_run_hooks(
        job_url=config.job_url,
        company=company_name,
    )
    async with LocalCamoufoxComputer(
        start_url=config.job_url,
        profile_dir=profile,
        resume_path=config.resume_path,
        on_escape_aggregator=on_escape_aggregator,
        on_full_page_screenshot=on_full_page_screenshot,
    ) as computer:
        agent = Agent(
            name="Job Apply",
            instructions=instructions,
            tools=[
                *composed.tools,
                ComputerTool(computer=computer),
            ],
            model=model,
            # Ask for a concise reasoning summary each turn (logged as think:).
            model_settings=ModelSettings(
                tool_choice="auto",
                reasoning=Reasoning(summary="concise"),
            ),
        )
        try:
            # Print reasoning / say / computer / tool steps each turn (terminal visibility).
            result = await Runner.run(
                agent,
                prompt,
                max_turns=max_turns,
                hooks=run_hooks,
            )
        except EscapeDuplicateAbort as exc:
            print(f"Stopped: {exc}", flush=True)
            exit_code = EXIT_DUPLICATE
        except Exception as exc:
            if exc.__class__.__name__ == "MaxTurnsExceeded":
                print(
                    f"Stopped after {max_turns} turns. "
                    "Raise MAX_TURNS in .env if the flow needs more steps.",
                    flush=True,
                )
                exit_code = 1
                if isinstance(run_hooks, ApplyRunHooks):
                    run_hooks.maybe_record_hard_run(
                        final_report=f"MaxTurnsExceeded after {max_turns} turns"
                    )
            else:
                # Still try full-page evidence before re-raising / closing browser.
                if on_full_page_screenshot:
                    await _emit_full_page_screenshot(computer, on_full_page_screenshot)
                raise
        else:
            final_output = result.final_output or ""
            print(final_output, flush=True)
            if _agent_reported_posting_unavailable(final_output):
                print(
                    "Agent reported posting unavailable/closed/expired — "
                    "Landed will be marked failed_permanent (adapter.posting_expired).",
                    flush=True,
                )
                exit_code = EXIT_POSTING_UNAVAILABLE
            elif config.submit:
                if _agent_reported_not_submitted(final_output):
                    print(
                        "Agent reported application was not submitted / needs human — "
                        "Landed will be marked needs_human (not submitted).",
                        flush=True,
                    )
                    exit_code = EXIT_NEEDS_HUMAN
                elif not re.search(
                    r"\*\*Application submitted:\*\*\s*Yes\b",
                    final_output or "",
                    flags=re.IGNORECASE,
                ):
                    # Submit mode but no clear Yes — do not claim success.
                    print(
                        "Submit mode but agent did not confirm Application submitted: Yes — "
                        "treating as needs_human.",
                        flush=True,
                    )
                    exit_code = EXIT_NEEDS_HUMAN
            if isinstance(run_hooks, ApplyRunHooks):
                run_hooks.maybe_record_hard_run(final_report=final_output)

        # Prefer the pre-submit form screenshot. Post-submit pages often redirect to
        # unrelated listings (Indeed/Glassdoor), which is useless as evidence.
        if on_full_page_screenshot and not computer._pre_submit_screenshot_taken:
            await _emit_full_page_screenshot(computer, on_full_page_screenshot)

        # Capture filledFields for Applications → Questions & answers (+ urlBefore).
        if page_evidence_out is not None:
            try:
                page_evidence_out.clear()
                page_evidence_out.update(await computer.capture_page_evidence())
                snippet = str(page_evidence_out.get("pageText") or "")[:120]
                print(
                    f"Page evidence for Landed: url={page_evidence_out.get('url')!r} "
                    f"text={snippet!r}…",
                    flush=True,
                )
            except Exception as exc:
                print(f"Page evidence capture failed: {exc}", flush=True)
            try:
                outcomes = await computer.get_fill_outcomes()
                page_evidence_out["filledFields"] = outcomes
                print(
                    f"Recorded {len(outcomes)} filled field(s) for Landed Q&A "
                    f"(source={FILL_SOURCE}).",
                    flush=True,
                )
            except Exception as exc:
                print(f"Fill outcomes capture failed: {exc}", flush=True)
                page_evidence_out.setdefault("filledFields", [])

        # Page copy can prove the listing is gone even if the agent didn't say so.
        if exit_code not in {EXIT_DUPLICATE, EXIT_POSTING_UNAVAILABLE}:
            evidence_text = ""
            if page_evidence_out:
                evidence_text = " ".join(
                    str(page_evidence_out.get(k) or "")
                    for k in ("pageText", "url", "blocked")
                )
            if looks_posting_unavailable(evidence_text):
                print(
                    "Page evidence shows posting unavailable/closed/expired — "
                    "Landed will be marked failed_permanent (adapter.posting_expired).",
                    flush=True,
                )
                exit_code = EXIT_POSTING_UNAVAILABLE

    if result is not None and exit_code == 0:
        usage = _usage_from_result(result)
        entry = record_run_cost(
            costs_path=Path(costs_path),
            session_id="local-camoufox",
            model=model,
            mode="local-camoufox",
            usage_bundle={"totals": usage, "turns": []},
            completed=True,
            notes=f"Apply to {config.job_url} with {config.resume_path.name}",
        )
        cost = entry.get("estimated_cost_usd")
        print(
            f"Estimated cost: ${cost if cost is not None else 'unknown'} (see {costs_path})",
            flush=True,
        )
    return exit_code


async def _emit_full_page_screenshot(
    computer: LocalCamoufoxComputer,
    callback: FullPageScreenshotCallback,
) -> None:
    captured = await computer.capture_full_page_jpeg()
    if not captured:
        print("No full-page screenshot to upload.", flush=True)
        return
    data, url = captured
    meta: dict[str, Any] = {
        "url": clean_job_url(url) or url,
        "content_type": "image/jpeg",
        "filename": f"full-page-{int(time.time())}.jpg",
        "kind": "screenshot",
        "bytes": len(data),
        "full_page": True,
    }
    try:
        callback(data, meta)
    except Exception as exc:
        print(f"Full-page screenshot callback failed: {exc}", flush=True)
