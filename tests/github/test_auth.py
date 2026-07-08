from __future__ import annotations

import pytest

from mcp_servers.github.auth import get_jwt


def test_get_jwt(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "dummy")
    import jwt

    def mock_encode(payload, key, algorithm):
        return "mock-jwt"

    monkeypatch.setattr(jwt, "encode", mock_encode)
    assert get_jwt() == "mock-jwt"


def test_get_jwt_missing_env(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    with pytest.raises(RuntimeError):
        get_jwt()


def test_get_jwt_normalizes_escaped_newlines(monkeypatch):
    """Secrets managers commonly flatten a PEM into literal `\\n` escapes."""
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "-----BEGIN KEY-----\\nabc\\n-----END KEY-----")
    import jwt

    seen_key = {}

    def mock_encode(payload, key, algorithm):
        seen_key["key"] = key
        return "mock-jwt"

    monkeypatch.setattr(jwt, "encode", mock_encode)
    assert get_jwt() == "mock-jwt"
    assert "\\n" not in seen_key["key"]
    assert "\n" in seen_key["key"]
