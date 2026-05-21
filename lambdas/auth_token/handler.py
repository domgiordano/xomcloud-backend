"""SoundCloud OAuth token-exchange proxy.

Exposes two operations behind a single Lambda:

- POST /auth/token   -- exchange an authorization_code (+ PKCE code_verifier) for tokens
- POST /auth/refresh -- exchange a refresh_token for a fresh access_token

Why this exists
---------------
Public clients (web SPA + iOS) MUST NOT see the SoundCloud client_secret.
This Lambda holds the secret server-side, forwards the request to
SoundCloud, and returns the response straight through.

This Lambda is intentionally public-callable -- it is the auth bootstrap,
so the API Gateway route must be wired WITHOUT the authorizer attached.
"""
from __future__ import annotations

import json
from typing import Any

import requests

from lambdas.common import (
    ValidationError,
    get_logger,
    parse_body,
    soundcloud_client_id,
    soundcloud_client_secret,
)
from lambdas.common.response import CORS_HEADERS

log = get_logger(__name__)

SOUNDCLOUD_TOKEN_URL = "https://secure.soundcloud.com/oauth/token"
UPSTREAM_TIMEOUT_SECONDS = 10

# Operation routing -- selected by the API Gateway path or an explicit
# `operation` field in the body (useful for local invocation / tests).
OP_TOKEN = "token"
OP_REFRESH = "refresh"


def _resolve_operation(event: dict) -> str:
    """Determine which operation to perform from the incoming event.

    Resolution order:
      1. Explicit `operation` field in the parsed body (test / direct invoke).
      2. API Gateway path -- `/auth/refresh` -> refresh, anything else -> token.
    """
    # Path-based routing (API Gateway proxy integration)
    path = (
        event.get("path")
        or event.get("rawPath")
        or (event.get("requestContext", {}) or {}).get("path", "")
        or ""
    )
    if path.endswith("/refresh"):
        return OP_REFRESH
    return OP_TOKEN


def _proxy_response(status: int, body: dict[str, Any]) -> dict:
    """Build an API Gateway proxy response with the standard CORS headers.

    We deliberately do NOT use the success/error helpers from common.response
    here because we want to return the upstream JSON shape verbatim (SoundCloud
    returns `{ access_token, refresh_token, expires_in, ... }` at the top level
    and clients expect that shape unchanged).
    """
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def _bad_request(message: str) -> dict:
    """Convenience helper for 400 responses with a consistent error shape."""
    return _proxy_response(
        400,
        {"error": {"code": "VALIDATION_ERROR", "message": message}},
    )


def _require(body: dict, field: str) -> str:
    """Return body[field] as a non-empty string, else raise ValidationError."""
    value = body.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"Missing required field: {field}")
    if not isinstance(value, str):
        raise ValidationError(f"Field '{field}' must be a string")
    return value.strip()


def _sanitize_upstream_body(text: str) -> dict[str, Any]:
    """Parse an upstream response body and strip anything we should never echo.

    SoundCloud's error bodies are typically `{ "error": "...", "error_description": "..." }`.
    On non-JSON responses we wrap the raw text in a generic shape. In either
    case we never include the client_secret -- it is only ever in the request
    body we send, not in upstream responses, but we filter defensively.
    """
    try:
        parsed = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {"error": {"code": "UPSTREAM_ERROR", "message": "SoundCloud returned a non-JSON response"}}

    if not isinstance(parsed, dict):
        return {"error": {"code": "UPSTREAM_ERROR", "message": "Unexpected upstream response shape"}}

    # Defensive: never echo a secret back to the caller, even if upstream
    # somehow includes it.
    parsed.pop("client_secret", None)
    return parsed


def _exchange(form: dict[str, str]) -> dict:
    """POST the form-encoded payload to SoundCloud and return the proxy response.

    Logs upstream status + error reason on failure, but never logs the
    client_secret or any other secret value.
    """
    # Defensive copy so we never accidentally log the secret if a future
    # caller mutates `form`.
    safe_form_keys = sorted(k for k in form.keys() if k != "client_secret")
    log.info("Forwarding token request to SoundCloud (fields=%s)", safe_form_keys)

    try:
        resp = requests.post(
            SOUNDCLOUD_TOKEN_URL,
            data=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            timeout=UPSTREAM_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        log.error("SoundCloud token endpoint timed out after %ss", UPSTREAM_TIMEOUT_SECONDS)
        return _proxy_response(
            504,
            {"error": {"code": "UPSTREAM_TIMEOUT", "message": "SoundCloud did not respond in time"}},
        )
    except requests.RequestException as e:
        # Log the exception type, not the message, in case requests ever
        # surfaces secret-bearing details from the request.
        log.error("SoundCloud token request failed: %s", type(e).__name__)
        return _proxy_response(
            502,
            {"error": {"code": "UPSTREAM_ERROR", "message": "Failed to reach SoundCloud"}},
        )

    body = _sanitize_upstream_body(resp.text)

    if resp.status_code >= 400:
        # Log the upstream status + the `error` field if present, never the secret.
        upstream_err = body.get("error") if isinstance(body, dict) else None
        log.warning(
            "SoundCloud returned %s (error=%s)",
            resp.status_code,
            upstream_err if isinstance(upstream_err, str) else "non-string",
        )

    return _proxy_response(resp.status_code, body)


def _handle_token_exchange(body: dict) -> dict:
    """Validate body and perform the authorization_code -> token exchange."""
    code = _require(body, "code")
    code_verifier = _require(body, "code_verifier")
    redirect_uri = _require(body, "redirect_uri")

    form = {
        "grant_type": "authorization_code",
        "client_id": soundcloud_client_id(),
        "client_secret": soundcloud_client_secret(),
        "code": code,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
    }
    return _exchange(form)


def _handle_refresh(body: dict) -> dict:
    """Validate body and perform the refresh_token -> access_token exchange."""
    refresh_token = _require(body, "refresh_token")

    form = {
        "grant_type": "refresh_token",
        "client_id": soundcloud_client_id(),
        "client_secret": soundcloud_client_secret(),
        "refresh_token": refresh_token,
    }
    return _exchange(form)


def handler(event: dict, context) -> dict:
    """Lambda entry point for the SoundCloud OAuth token-exchange proxy."""
    try:
        # CORS preflight -- API Gateway typically handles this, but make sure
        # a direct OPTIONS call still works for browser callers.
        http_method = (
            event.get("httpMethod")
            or (event.get("requestContext", {}) or {}).get("http", {}).get("method", "")
            or ""
        ).upper()
        if http_method == "OPTIONS":
            return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

        operation = _resolve_operation(event)

        try:
            body = parse_body(event) or {}
        except ValidationError as e:
            log.warning("Body parse error: %s", e)
            return _bad_request(str(e))

        # Allow body-driven operation override (handy for tests / direct invoke).
        body_op = body.get("operation")
        if body_op in (OP_TOKEN, OP_REFRESH):
            operation = body_op

        if operation == OP_REFRESH:
            return _handle_refresh(body)
        return _handle_token_exchange(body)

    except ValidationError as e:
        log.warning("Validation error: %s", e)
        return _bad_request(str(e))
    except ValueError as e:
        # Raised when SSM-backed config is missing (e.g. unconfigured client_id).
        log.error("Configuration error: %s", e)
        return _proxy_response(
            500,
            {"error": {"code": "CONFIG_ERROR", "message": "Auth proxy is not configured"}},
        )
    except Exception:
        log.error("Unexpected error in auth_token handler", exc_info=True)
        return _proxy_response(
            500,
            {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}},
        )
