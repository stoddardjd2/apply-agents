"""Handle computer-use origin access and browser authentication approvals."""

from __future__ import annotations

import os
from getpass import getpass
from typing import Any


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def allowed_origins() -> set[str]:
    raw = os.getenv("AUTO_APPROVE_ORIGINS", "")
    return {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}


def _normalize_origin(origin: str | None) -> str:
    if not origin:
        return ""
    return origin.strip().rstrip("/")


def _field_value_from_env(field: Any) -> str | None:
    field_id = str(_attr(field, "id", "")).lower()
    label = str(_attr(field, "label", "")).lower()
    field_type = str(_attr(field, "type", "")).lower()

    email = os.getenv("INDEED_EMAIL", "").strip()
    password = os.getenv("INDEED_PASSWORD", "").strip()

    if email and (
        "email" in field_id
        or "email" in label
        or field_type in {"email", "text"}
        and ("user" in field_id or "login" in field_id)
    ):
        if "pass" not in field_id and "pass" not in label:
            return email

    if password and ("pass" in field_id or "pass" in label or field_type == "password"):
        return password

    return None


def read_authentication_response(request: Any) -> dict[str, Any]:
    """Build a browser_authentication response from env vars or interactive input."""
    cancel = {"type": "browser_authentication", "action": "cancel"}
    reason = _attr(request, "reason") or "The agent needs you to sign in."
    credential_origin = _attr(request, "credential_origin")
    print(reason)
    print("Credential origin:", credential_origin or "Not supplied")

    options = list(_attr(request, "options") or [])
    fields = list(_attr(request, "fields") or [])

    selected_option = None
    active_fields = fields

    if options:
        # Prefer password login when available for Indeed automation.
        password_option = next(
            (
                option
                for option in options
                if "pass" in str(_attr(option, "label", "")).lower()
                or "pass" in str(_attr(option, "id", "")).lower()
            ),
            None,
        )
        if password_option is not None and os.getenv("INDEED_PASSWORD"):
            selected_option = _attr(password_option, "id")
            fields_by_id = {_attr(field, "id"): field for field in fields}
            active_fields = [
                fields_by_id[field_id]
                for field_id in (_attr(password_option, "field_ids") or [])
                if field_id in fields_by_id
            ]
        else:
            for index, option in enumerate(options, start=1):
                print(f"{index}. {_attr(option, 'label')}")
            while True:
                choice = input("Choose a sign-in method, or enter cancel: ").strip().lower()
                if choice == "cancel":
                    return cancel
                if choice.isdigit() and 1 <= int(choice) <= len(options):
                    option = options[int(choice) - 1]
                    break
                print("Enter a method number from the list, or cancel.")
            selected_option = _attr(option, "id")
            fields_by_id = {_attr(field, "id"): field for field in fields}
            active_fields = [
                fields_by_id[field_id]
                for field_id in (_attr(option, "field_ids") or [])
                if field_id in fields_by_id
            ]

    values: list[dict[str, str]] = []
    missing_required = False
    for field in active_fields:
        env_value = _field_value_from_env(field)
        if env_value:
            values.append({"field_id": _attr(field, "id"), "value": env_value})
            continue

        required = bool(_attr(field, "required"))
        label = _attr(field, "label") if required else f"{_attr(field, 'label')} (optional)"
        value = getpass(f"{label}: ")
        if value:
            values.append({"field_id": _attr(field, "id"), "value": value})
        elif required:
            missing_required = True

    if missing_required and not values:
        print("Required sign-in fields were not provided; cancelling.")
        return cancel

    if selected_option is None and active_fields and not values:
        print("No sign-in values provided; cancelling.")
        return cancel

    response: dict[str, Any] = {
        "type": "browser_authentication",
        "action": "submit",
        "fields": values,
    }
    if selected_option is not None:
        response["selected_option"] = selected_option
    return response


def respond_to_computer_use_approval(client: Any, session_id: str, approval: Any) -> None:
    request = _attr(approval, "request")
    request_type = _attr(request, "type")
    request_id = _attr(approval, "request_id")
    approval_client = client

    if request_type == "browser_origin_access":
        origin = _normalize_origin(_attr(request, "origin"))
        reason = _attr(request, "reason") or "The browser needs access to an origin."
        print(reason)
        print("Origin:", origin or "Not supplied")

        if origin in allowed_origins():
            decision = "approve"
            print(f"Auto-approving origin {origin}")
        else:
            while True:
                decision = (
                    input("Allow this origin? [approve/deny/cancel; default: deny] ")
                    .strip()
                    .lower()
                    or "deny"
                )
                if decision in {"approve", "deny", "cancel"}:
                    break
                print("Enter approve, deny, or cancel.")
        response = {"type": "browser_origin_access", "decision": decision}
    elif request_type == "browser_authentication":
        response = read_authentication_response(request)
        approval_client = client.with_options(max_retries=0)
    else:
        raise RuntimeError(f"Unsupported computer-use approval: {request_type}")

    approval_client.beta.agents.sessions.events.create(
        session_id,
        events=[
            {
                "type": "agent.session.input.computer_use_approval_request_result",
                "request_id": request_id,
                "response": response,
            }
        ],
    )
