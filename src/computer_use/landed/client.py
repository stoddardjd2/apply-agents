"""Minimal Landed worker API client (claim / resume / finish / artifacts)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from urllib.parse import urljoin

# Match Landed WorkerGateway.MAX_ARTIFACT_BYTES
MAX_ARTIFACT_BYTES = 15 * 1024 * 1024


class LandedApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class LandedClient:
    def __init__(
        self,
        *,
        api_base: str,
        worker_token: str,
        worker_id: str = "apply-agents",
        timeout_s: float = 60.0,
    ):
        if not api_base.strip():
            raise ValueError("LANDED_API_BASE is required")
        if not worker_token.strip():
            raise ValueError("LANDED_WORKER_TOKEN is required")
        self.api_base = api_base.rstrip("/") + "/"
        self.worker_token = worker_token.strip()
        self.worker_id = worker_id.strip() or "apply-agents"
        self.timeout_s = timeout_s

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.worker_token}",
            "X-Landed-Worker": self.worker_id,
            "Accept": "application/json",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _url(self, path: str) -> str:
        return urljoin(self.api_base, path.lstrip("/"))

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
        raw: bool = False,
    ) -> Any:
        data: bytes | None = None
        headers = self._headers(json_body=payload is not None and body is None)
        if body is not None:
            data = body
            if content_type:
                headers["Content-Type"] = content_type
        elif payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path),
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                if resp.status == 204:
                    return None
                resp_body = resp.read()
                if raw:
                    return resp_body
                if not resp_body:
                    return None
                return json.loads(resp_body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(text) if text else None
            except json.JSONDecodeError:
                parsed = text
            raise LandedApiError(
                f"{method} {path} failed: HTTP {exc.code} {parsed}",
                status=exc.code,
                body=parsed,
            ) from exc
        except urllib.error.URLError as exc:
            raise LandedApiError(f"{method} {path} failed: {exc.reason}") from exc

    def claim(self, adapters: list[str] | None = None) -> dict[str, Any] | None:
        """Claim next application.run job, or None when queue is empty (HTTP 204)."""
        body: dict[str, Any] = {"adapters": list(adapters or [])}
        return self._request("POST", "/api/workers/applications/claim", payload=body)

    def download_resume(self, application_id: str, dest_path: str | Any) -> Any:
        """Download tailored resume PDF bytes for a claimed application."""
        from pathlib import Path

        path = Path(dest_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Prefer claim-relative download URL when present; fall back to standard path.
        bytes_ = self._request(
            "GET",
            f"/api/workers/applications/{application_id}/resume",
            raw=True,
        )
        if not isinstance(bytes_, (bytes, bytearray)) or not bytes_:
            raise LandedApiError(f"Empty resume for application {application_id}")
        path.write_bytes(bytes_)
        return path

    def artifact(
        self,
        application_id: str,
        *,
        data: bytes,
        content_type: str = "image/jpeg",
        filename: str = "screenshot.jpg",
        kind: str = "screenshot",
    ) -> dict[str, Any]:
        """Upload a screenshot/HTML artifact (raw body; supports large full-page images)."""
        if not data:
            raise LandedApiError("artifact is empty")
        if len(data) > MAX_ARTIFACT_BYTES:
            raise LandedApiError(
                f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes ({len(data)} bytes)"
            )
        qs = urllib.parse.urlencode({"kind": kind, "filename": filename})
        path = f"/api/workers/applications/{application_id}/artifacts?{qs}"
        result = self._request(
            "POST",
            path,
            body=data,
            content_type=content_type,
        )
        if not isinstance(result, dict):
            raise LandedApiError(f"Unexpected artifact response: {result!r}")
        return result

    def step(
        self,
        application_id: str,
        *,
        name: str,
        status: str,
        detail: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        artifact_id: int | str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any] | None:
        """POST an application timeline step (e.g. escape_aggregator).

        For escape_aggregator, the ack may include ``duplicate`` / ``cancelled`` /
        ``reasonCode`` when the destination URL matches a prior or live application.
        """
        payload: dict[str, Any] = {
            "name": name,
            "status": status,
            "detail": detail or {},
            "artifactId": artifact_id,
            "durationMs": duration_ms,
            "traceId": trace_id,
        }
        return self._request(
            "POST",
            f"/api/workers/applications/{application_id}/steps",
            payload=payload,
        )

    def finish(
        self,
        application_id: str,
        *,
        outcome: str,
        reason_code: str | None = None,
        details: dict[str, Any] | None = None,
        confirmation: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "outcome": outcome,
            "reasonCode": reason_code,
            "details": details or {},
            "confirmation": confirmation,
        }
        return self._request(
            "POST",
            f"/api/workers/applications/{application_id}/finish",
            payload=payload,
        )

    def verification_code(
        self,
        application_id: str,
        *,
        since: str | None = None,
        company: str | None = None,
    ) -> dict[str, Any] | None:
        """Poll Gmail for an apply-time security / OTP code.

        Returns ``{code, subject, from, receivedAt, messageId}`` on hit,
        ``None`` when no matching mail yet (HTTP 204). Raises ``LandedApiError``
        on 409 (Gmail not configured) or other failures.
        """
        payload: dict[str, Any] = {}
        if since:
            payload["since"] = since
        if company:
            payload["company"] = company
        result = self._request(
            "POST",
            f"/api/workers/applications/{application_id}/verification-code",
            payload=payload,
        )
        if result is None:
            return None
        if not isinstance(result, dict) or not str(result.get("code") or "").strip():
            return None
        return result

    def verification_link(
        self,
        application_id: str,
        *,
        since: str | None = None,
        company: str | None = None,
    ) -> dict[str, Any] | None:
        """Poll Gmail for an apply-time click-to-verify URL.

        Returns ``{url, subject, from, receivedAt, messageId}`` on hit,
        ``None`` when no matching mail yet (HTTP 204). Raises ``LandedApiError``
        on 409 (Gmail not configured) or other failures.
        """
        payload: dict[str, Any] = {}
        if since:
            payload["since"] = since
        if company:
            payload["company"] = company
        result = self._request(
            "POST",
            f"/api/workers/applications/{application_id}/verification-link",
            payload=payload,
        )
        if result is None:
            return None
        if not isinstance(result, dict) or not str(result.get("url") or "").strip():
            return None
        return result
