from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def mock_token(monkeypatch):
    import mcp_servers.github.client

    async def get_token():
        return "mock-token"

    monkeypatch.setattr(mcp_servers.github.client, "get_installation_token", get_token)
