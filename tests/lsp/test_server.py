from unittest.mock import AsyncMock, mock_open, patch

import pytest

from mcp_servers.lsp.server import lsp_hover, main, server_lifespan


@pytest.fixture(autouse=True)
def mock_workspace_root():
    with patch("mcp_servers.lsp.server.WORKSPACE_ROOT", "/"):
        yield


@pytest.mark.asyncio
async def test_server_lifespan():
    with patch("mcp_servers.lsp.server.lsp_client") as mock_client:
        mock_client.start = AsyncMock()
        mock_client.initialize = AsyncMock()
        mock_client.stop = AsyncMock()

        from unittest.mock import MagicMock

        mock_server = MagicMock()
        async with server_lifespan(mock_server):
            mock_client.start.assert_called_once()
            mock_client.initialize.assert_called_once()

        mock_client.stop.assert_called_once()


@pytest.mark.asyncio
async def test_lsp_hover_not_absolute():
    # Context initialization
    ctx = patch("mcp.server.fastmcp.Context").start()
    res = await lsp_hover("relative/path.py", 1, 1, ctx)
    assert "Filepath must be within the workspace root" in res or "File not found" in res


@pytest.mark.asyncio
async def test_lsp_hover_not_found():
    ctx = patch("mcp.server.fastmcp.Context").start()
    res = await lsp_hover("/absolute/not/found.py", 1, 1, ctx)
    assert res.startswith("Error: File not found")


@pytest.mark.asyncio
async def test_lsp_hover_success():
    ctx = patch("mcp.server.fastmcp.Context").start()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.open_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value={"contents": {"value": "docstring"}})

        res = await lsp_hover("/path/to/file.py", 1, 0, ctx)
        assert res == "docstring"

        # Test go / rust language deduction
        await lsp_hover("/path/to/file.go", 1, 0, ctx)
        mock_client.open_file.assert_called_with("file:///path/to/file.go", "go", "def foo(): pass")

        await lsp_hover("/path/to/file.rs", 1, 0, ctx)
        mock_client.open_file.assert_called_with(
            "file:///path/to/file.rs", "rust", "def foo(): pass"
        )


@pytest.mark.asyncio
async def test_lsp_hover_empty_response():
    ctx = patch("mcp.server.fastmcp.Context").start()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.open_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value=None)

        res = await lsp_hover("/path/to/file.py", 1, 0, ctx)
        assert res == "No hover information found at this position."


@pytest.mark.asyncio
async def test_lsp_hover_list_response():
    ctx = patch("mcp.server.fastmcp.Context").start()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.open_file = AsyncMock()
        mock_client.send_request = AsyncMock(
            return_value={"contents": [{"value": "def foo()"}, "string_content"]}
        )

        res = await lsp_hover("/path/to/file.py", 1, 0, ctx)
        assert res == "def foo()\n\nstring_content"


@pytest.mark.asyncio
async def test_lsp_hover_string_response():
    ctx = patch("mcp.server.fastmcp.Context").start()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.open_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value={"contents": "just a string"})

        res = await lsp_hover("/path/to/file.py", 1, 0, ctx)
        assert res == "just a string"


@pytest.mark.asyncio
async def test_lsp_hover_error():
    ctx = patch("mcp.server.fastmcp.Context").start()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.open_file = AsyncMock(side_effect=Exception("mock error"))

        res = await lsp_hover("/path/to/file.py", 1, 0, ctx)
        assert res == "Error querying LSP: mock error"


@pytest.mark.asyncio
async def test_lsp_hover_cancelled():
    import asyncio

    ctx = patch("mcp.server.fastmcp.Context").start()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.open_file = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await lsp_hover("/path/to/file.py", 1, 0, ctx)


@pytest.mark.asyncio
async def test_lsp_hover_outside_workspace():
    ctx = patch("mcp.server.fastmcp.Context").start()
    with patch("mcp_servers.lsp.server.WORKSPACE_ROOT", "/var/lib"):
        res = await lsp_hover("/tmp/foo.py", 1, 1, ctx)
        assert "must be within the workspace root" in res


def test_main():
    with patch("mcp_servers.lsp.server.mcp.run") as mock_run:
        main()
        mock_run.assert_called_once()
