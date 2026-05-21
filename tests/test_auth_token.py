"""Tests for lambdas.auth_token.handler (SoundCloud OAuth proxy)."""
from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

# Import the module directly so we can patch its module-level names
_handler_mod = importlib.import_module("lambdas.auth_token.handler")
handler = _handler_mod.handler

TEST_CLIENT_ID = "test-client-id"
TEST_CLIENT_SECRET = "test-client-secret"


def _patch_creds():
    """Patch the SSM-backed credential helpers used inside the handler module."""
    return patch.multiple(
        _handler_mod,
        soundcloud_client_id=MagicMock(return_value=TEST_CLIENT_ID),
        soundcloud_client_secret=MagicMock(return_value=TEST_CLIENT_SECRET),
    )


def _event(path: str, body: dict) -> dict:
    """Build an API Gateway proxy event for the given path + JSON body."""
    return {
        "httpMethod": "POST",
        "path": path,
        "body": json.dumps(body),
    }


def _fake_response(status: int, payload: dict | str) -> MagicMock:
    """Build a fake requests.Response-like object."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    if isinstance(payload, dict):
        resp.text = json.dumps(payload)
    else:
        resp.text = payload
    return resp


class TestTokenExchange:
    def test_happy_path_returns_token_json(self) -> None:
        token_payload = {
            "access_token": "sc-access-123",
            "refresh_token": "sc-refresh-456",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "*",
        }

        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            mock_post.return_value = _fake_response(200, token_payload)

            result = handler(
                _event(
                    "/auth/token",
                    {
                        "code": "auth-code-abc",
                        "code_verifier": "pkce-verifier-xyz",
                        "redirect_uri": "https://xomcloud.xomware.com/callback",
                    },
                ),
                None,
            )

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body == token_payload

        # Confirm the upstream call used the right form fields and timeout.
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://secure.soundcloud.com/oauth/token"
        assert kwargs["timeout"] == 10
        sent = kwargs["data"]
        assert sent["grant_type"] == "authorization_code"
        assert sent["client_id"] == TEST_CLIENT_ID
        assert sent["client_secret"] == TEST_CLIENT_SECRET
        assert sent["code"] == "auth-code-abc"
        assert sent["code_verifier"] == "pkce-verifier-xyz"
        assert sent["redirect_uri"] == "https://xomcloud.xomware.com/callback"

    def test_missing_code_returns_400(self) -> None:
        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            result = handler(
                _event(
                    "/auth/token",
                    {
                        "code_verifier": "pkce-verifier-xyz",
                        "redirect_uri": "https://xomcloud.xomware.com/callback",
                    },
                ),
                None,
            )

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "code" in body["error"]["message"]
        # Must NOT call SoundCloud with an invalid request.
        mock_post.assert_not_called()

    def test_empty_code_returns_400(self) -> None:
        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            result = handler(
                _event(
                    "/auth/token",
                    {
                        "code": "   ",
                        "code_verifier": "pkce-verifier-xyz",
                        "redirect_uri": "https://xomcloud.xomware.com/callback",
                    },
                ),
                None,
            )

        assert result["statusCode"] == 400
        mock_post.assert_not_called()

    def test_missing_code_verifier_returns_400(self) -> None:
        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            result = handler(
                _event(
                    "/auth/token",
                    {
                        "code": "auth-code-abc",
                        "redirect_uri": "https://xomcloud.xomware.com/callback",
                    },
                ),
                None,
            )

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert "code_verifier" in body["error"]["message"]
        mock_post.assert_not_called()

    def test_missing_redirect_uri_returns_400(self) -> None:
        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            result = handler(
                _event(
                    "/auth/token",
                    {
                        "code": "auth-code-abc",
                        "code_verifier": "pkce-verifier-xyz",
                    },
                ),
                None,
            )

        assert result["statusCode"] == 400
        mock_post.assert_not_called()

    def test_soundcloud_401_is_proxied_without_secret(self) -> None:
        sc_error = {"error": "invalid_grant", "error_description": "Code expired"}

        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            mock_post.return_value = _fake_response(401, sc_error)

            result = handler(
                _event(
                    "/auth/token",
                    {
                        "code": "auth-code-abc",
                        "code_verifier": "pkce-verifier-xyz",
                        "redirect_uri": "https://xomcloud.xomware.com/callback",
                    },
                ),
                None,
            )

        # Upstream status proxied through.
        assert result["statusCode"] == 401

        # Sanitized body matches what SoundCloud sent (minus any secret).
        body = json.loads(result["body"])
        assert body == sc_error

        # Critically: the client_secret never appears in the response.
        raw_body = result["body"]
        assert TEST_CLIENT_SECRET not in raw_body
        assert "client_secret" not in raw_body

    def test_upstream_timeout_returns_504(self) -> None:
        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            mock_post.side_effect = requests.Timeout("boom")

            result = handler(
                _event(
                    "/auth/token",
                    {
                        "code": "auth-code-abc",
                        "code_verifier": "pkce-verifier-xyz",
                        "redirect_uri": "https://xomcloud.xomware.com/callback",
                    },
                ),
                None,
            )

        assert result["statusCode"] == 504
        body = json.loads(result["body"])
        assert body["error"]["code"] == "UPSTREAM_TIMEOUT"


class TestRefresh:
    def test_happy_path_returns_new_access_token(self) -> None:
        token_payload = {
            "access_token": "sc-new-access",
            "refresh_token": "sc-rotated-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            mock_post.return_value = _fake_response(200, token_payload)

            result = handler(
                _event("/auth/refresh", {"refresh_token": "old-refresh-token"}),
                None,
            )

        assert result["statusCode"] == 200
        assert json.loads(result["body"]) == token_payload

        mock_post.assert_called_once()
        sent = mock_post.call_args.kwargs["data"]
        assert sent["grant_type"] == "refresh_token"
        assert sent["client_id"] == TEST_CLIENT_ID
        assert sent["client_secret"] == TEST_CLIENT_SECRET
        assert sent["refresh_token"] == "old-refresh-token"
        # Refresh flow must NOT include code / code_verifier / redirect_uri.
        assert "code" not in sent
        assert "code_verifier" not in sent
        assert "redirect_uri" not in sent

    def test_missing_refresh_token_returns_400(self) -> None:
        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            result = handler(_event("/auth/refresh", {}), None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "refresh_token" in body["error"]["message"]
        mock_post.assert_not_called()

    def test_empty_refresh_token_returns_400(self) -> None:
        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            result = handler(_event("/auth/refresh", {"refresh_token": ""}), None)

        assert result["statusCode"] == 400
        mock_post.assert_not_called()


class TestRouting:
    def test_operation_override_in_body_forces_refresh(self) -> None:
        """Direct-invoke / test fallback: explicit operation field wins."""
        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            mock_post.return_value = _fake_response(200, {"access_token": "ok"})

            # Note path is /auth/token but operation=refresh in body
            result = handler(
                _event(
                    "/auth/token",
                    {"operation": "refresh", "refresh_token": "rt"},
                ),
                None,
            )

        assert result["statusCode"] == 200
        sent = mock_post.call_args.kwargs["data"]
        assert sent["grant_type"] == "refresh_token"

    def test_options_returns_204_with_cors(self) -> None:
        result = handler({"httpMethod": "OPTIONS", "path": "/auth/token"}, None)
        assert result["statusCode"] == 204
        assert result["headers"]["Access-Control-Allow-Origin"] == "https://xomcloud.xomware.com"


class TestCorsHeaders:
    def test_token_response_has_cors_header(self) -> None:
        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            mock_post.return_value = _fake_response(200, {"access_token": "x"})
            result = handler(
                _event(
                    "/auth/token",
                    {
                        "code": "c",
                        "code_verifier": "v",
                        "redirect_uri": "https://xomcloud.xomware.com/callback",
                    },
                ),
                None,
            )

        assert result["headers"]["Access-Control-Allow-Origin"] == "https://xomcloud.xomware.com"

    def test_error_response_has_cors_header(self) -> None:
        with _patch_creds():
            result = handler(_event("/auth/token", {}), None)
        assert result["statusCode"] == 400
        assert result["headers"]["Access-Control-Allow-Origin"] == "https://xomcloud.xomware.com"


class TestNoSecretLeak:
    def test_secret_not_in_logs_on_success(self, caplog: pytest.LogCaptureFixture) -> None:
        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            mock_post.return_value = _fake_response(200, {"access_token": "x"})
            with caplog.at_level("INFO"):
                handler(
                    _event(
                        "/auth/token",
                        {
                            "code": "c",
                            "code_verifier": "v",
                            "redirect_uri": "https://xomcloud.xomware.com/callback",
                        },
                    ),
                    None,
                )

        joined_logs = "\n".join(rec.getMessage() for rec in caplog.records)
        assert TEST_CLIENT_SECRET not in joined_logs

    def test_secret_not_in_logs_on_upstream_error(self, caplog: pytest.LogCaptureFixture) -> None:
        with _patch_creds(), patch.object(_handler_mod.requests, "post") as mock_post:
            mock_post.return_value = _fake_response(
                401, {"error": "invalid_client"}
            )
            with caplog.at_level("INFO"):
                handler(
                    _event(
                        "/auth/token",
                        {
                            "code": "c",
                            "code_verifier": "v",
                            "redirect_uri": "https://xomcloud.xomware.com/callback",
                        },
                    ),
                    None,
                )

        joined_logs = "\n".join(rec.getMessage() for rec in caplog.records)
        assert TEST_CLIENT_SECRET not in joined_logs
