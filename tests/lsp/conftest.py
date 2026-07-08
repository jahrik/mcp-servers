from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def mock_workspace_root(monkeypatch, tmp_path):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
