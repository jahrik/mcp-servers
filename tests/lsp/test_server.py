from __future__ import annotations

import pytest

from mcp_servers.lsp.server import main, server_lifespan


@pytest.mark.asyncio
async def test_server_lifespan(mocker):
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.start = mocker.AsyncMock()
    mock_client.initialize = mocker.AsyncMock()
    mock_client.stop = mocker.AsyncMock()

    mock_server = mocker.MagicMock()
    async with server_lifespan(mock_server):
        mock_client.start.assert_called_once()
        mock_client.initialize.assert_called_once()

    mock_client.stop.assert_called_once()


def test_main(mocker):
    mock_run = mocker.patch("mcp_servers.lsp.server.mcp.run")
    main()
    mock_run.assert_called_once()
