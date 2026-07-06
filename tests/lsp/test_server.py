from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from mcp_servers.lsp.server import (
    lsp_definition,
    lsp_diagnostics,
    lsp_document_symbols,
    lsp_hover,
    lsp_references,
    lsp_workspace_symbols,
    main,
    server_lifespan,
)


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

        mock_server = MagicMock()
        async with server_lifespan(mock_server):
            mock_client.start.assert_called_once()
            mock_client.initialize.assert_called_once()

        mock_client.stop.assert_called_once()


@pytest.mark.asyncio
async def test_lsp_hover_not_absolute():
    # Context initialization
    ctx = MagicMock()
    res = await lsp_hover("relative/path.py", 1, 1, ctx)
    assert "Filepath must be within the workspace root" in res or "File not found" in res


@pytest.mark.asyncio
async def test_lsp_hover_not_found():
    ctx = MagicMock()
    res = await lsp_hover("/absolute/not/found.py", 1, 1, ctx)
    assert res.startswith("Error: File not found")


@pytest.mark.asyncio
async def test_lsp_hover_line_too_small():
    ctx = MagicMock()
    with patch("pathlib.Path.exists", return_value=True):
        res = await lsp_hover("/tmp/file.py", 0, 1, ctx)
        assert "line must be >= 1 and char must be >= 0" in res


@pytest.mark.asyncio
async def test_lsp_hover_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value={"contents": {"value": "docstring"}})

        res = await lsp_hover("/path/to/file.py", 1, 0, ctx)
        assert res == "docstring"

        # Test go / rust language deduction
        await lsp_hover("/path/to/file.go", 1, 0, ctx)
        mock_client.sync_file.assert_called_with("file:///path/to/file.go", "go", "def foo(): pass")

        await lsp_hover("/path/to/file.rs", 1, 0, ctx)
        mock_client.sync_file.assert_called_with(
            "file:///path/to/file.rs", "rust", "def foo(): pass"
        )

        await lsp_hover("/path/to/file.ts", 1, 0, ctx)
        mock_client.sync_file.assert_called_with(
            "file:///path/to/file.ts", "typescript", "def foo(): pass"
        )

        await lsp_hover("/path/to/file.js", 1, 0, ctx)
        mock_client.sync_file.assert_called_with(
            "file:///path/to/file.js", "javascript", "def foo(): pass"
        )


@pytest.mark.asyncio
async def test_lsp_hover_empty_response():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value=None)

        res = await lsp_hover("/path/to/file.py", 1, 0, ctx)
        assert res == "No hover information found at this position."


@pytest.mark.asyncio
async def test_lsp_hover_list_response():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(
            return_value={"contents": [{"value": "def foo()"}, "string_content"]}
        )

        res = await lsp_hover("/path/to/file.py", 1, 0, ctx)
        assert res == "def foo()\n\nstring_content"


@pytest.mark.asyncio
async def test_lsp_hover_string_response():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value={"contents": "just a string"})

        res = await lsp_hover("/path/to/file.py", 1, 0, ctx)
        assert res == "just a string"


@pytest.mark.asyncio
async def test_lsp_hover_error():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock(side_effect=Exception("mock error"))

        res = await lsp_hover("/path/to/file.py", 1, 0, ctx)
        assert res == "Error querying LSP: mock error"


@pytest.mark.asyncio
async def test_lsp_hover_cancelled():
    import asyncio

    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await lsp_hover("/path/to/file.py", 1, 0, ctx)


@pytest.mark.asyncio
async def test_lsp_hover_outside_workspace():
    ctx = MagicMock()
    with patch("mcp_servers.lsp.server.WORKSPACE_ROOT", "/var/lib"):
        res = await lsp_hover("/tmp/foo.py", 1, 1, ctx)
        assert "must be within the workspace root" in res


def test_main():
    with patch("mcp_servers.lsp.server.mcp.run") as mock_run:
        main()
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_lsp_definition_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value=[{"uri": "file:///path", "range": {}}])

        res = await lsp_definition("/path/to/file.py", 1, 0, ctx)
        assert "file:///path" in res


@pytest.mark.asyncio
async def test_lsp_references_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value=[{"uri": "file:///path", "range": {}}])

        res = await lsp_references("/path/to/file.py", 1, 0, ctx)
        assert "file:///path" in res


@pytest.mark.asyncio
async def test_lsp_document_symbols_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value=[{"name": "foo", "kind": 12}])

        res = await lsp_document_symbols("/path/to/file.py", ctx)
        assert "foo" in res


@pytest.mark.asyncio
async def test_lsp_workspace_symbols_success():
    ctx = MagicMock()
    with patch("mcp_servers.lsp.server.lsp_client") as mock_client:
        mock_client.send_request = AsyncMock(return_value=[{"name": "foo", "kind": 12}])

        res = await lsp_workspace_symbols("foo", ctx)
        assert "foo" in res


@pytest.mark.asyncio
async def test_lsp_diagnostics_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.get_diagnostics = MagicMock(return_value=[{"message": "error"}])

        res = await lsp_diagnostics("/path/to/file.py", ctx)
        assert "error" in res


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_func", "args"),
    [
        (lsp_definition, ("/absolute/not/found.py", 1, 0)),
        (lsp_references, ("/absolute/not/found.py", 1, 0)),
        (lsp_document_symbols, ("/absolute/not/found.py",)),
        (lsp_diagnostics, ("/absolute/not/found.py",)),
    ],
)
async def test_lsp_tools_file_not_found(tool_func, args):
    ctx = MagicMock()
    res = await tool_func(*args, ctx)
    assert res.startswith("Error: File not found")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_func", "args"),
    [
        (lsp_definition, ("/path/to/file.py", 1, 0)),
        (lsp_references, ("/path/to/file.py", 1, 0)),
        (lsp_document_symbols, ("/path/to/file.py",)),
        (lsp_diagnostics, ("/path/to/file.py",)),
        (lsp_workspace_symbols, ("query",)),
    ],
)
async def test_lsp_tools_cancelled(tool_func, args):
    import asyncio

    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock(side_effect=asyncio.CancelledError())
        mock_client.send_request = AsyncMock(side_effect=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await tool_func(*args, ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_func", "args"),
    [
        (lsp_definition, ("/path/to/file.py", 1, 0)),
        (lsp_references, ("/path/to/file.py", 1, 0)),
        (lsp_document_symbols, ("/path/to/file.py",)),
        (lsp_diagnostics, ("/path/to/file.py",)),
        (lsp_workspace_symbols, ("query",)),
    ],
)
async def test_lsp_tools_exception(tool_func, args):
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock(side_effect=Exception("mock error"))
        mock_client.send_request = AsyncMock(side_effect=Exception("mock error"))
        res = await tool_func(*args, ctx)
        assert "Error querying LSP" in res


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_func",
    [
        lsp_definition,
        lsp_references,
    ],
)
async def test_lsp_tools_invalid_line_char(tool_func):
    ctx = MagicMock()
    with patch("pathlib.Path.exists", return_value=True):
        res = await tool_func("/path/to/file.py", 0, 0, ctx)
        assert "line must be >= 1" in res


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_func", "args"),
    [
        (lsp_definition, ("/path/to/file.py", 1, 0)),
        (lsp_references, ("/path/to/file.py", 1, 0)),
        (lsp_document_symbols, ("/path/to/file.py",)),
        (lsp_workspace_symbols, ("query",)),
        (lsp_diagnostics, ("/path/to/file.py",)),
    ],
)
async def test_lsp_tools_no_response(tool_func, args):
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value=None)
        mock_client.get_diagnostics = MagicMock(return_value=None)
        res = await tool_func(*args, ctx)
        assert "No" in res
