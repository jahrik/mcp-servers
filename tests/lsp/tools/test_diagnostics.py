from __future__ import annotations

import pytest

from mcp_servers.lsp.models.schemas import FilePathArgs
from mcp_servers.lsp.tools import lsp_diagnostics


@pytest.mark.asyncio
async def test_lsp_diagnostics_with_items(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.get_diagnostics = mocker.MagicMock(return_value=[{"message": "err"}])

    args = FilePathArgs(filepath=str(f))
    res = await lsp_diagnostics(args, ctx)
    assert "err" in res


@pytest.mark.asyncio
async def test_lsp_diagnostics_empty(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.get_diagnostics = mocker.MagicMock(return_value=[])

    args = FilePathArgs(filepath=str(f))
    res = await lsp_diagnostics(args, ctx)
    assert "error-free" in res


@pytest.mark.asyncio
async def test_lsp_diagnostics_success(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.get_diagnostics = mocker.MagicMock(return_value=[{"message": "error"}])

    args = FilePathArgs(filepath=str(f))
    res = await lsp_diagnostics(args, ctx)
    assert "error" in res
