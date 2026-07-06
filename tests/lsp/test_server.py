from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from mcp_servers.lsp.server import (
    lsp_call_hierarchy,
    lsp_definition,
    lsp_diagnostics,
    lsp_document_highlight,
    lsp_document_symbols,
    lsp_hover,
    lsp_implementation,
    lsp_references,
    lsp_type_definition,
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
        assert "/path" in res


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
        assert "/path" in res


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


def test_format_location():
    from mcp_servers.lsp.server import _format_location

    # Test LocationLink
    assert (
        _format_location(
            {
                "targetUri": "file:///path/link",
                "targetSelectionRange": {"start": {"line": 1, "character": 5}},
            }
        )
        == "/path/link:2:5"
    )

    # Test Location with no file://
    assert (
        _format_location(
            {"uri": "/path/no-scheme", "range": {"start": {"line": 2, "character": 0}}}
        )
        == "/path/no-scheme:3:0"
    )

    # Test single dictionary return from definition
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from mcp_servers.lsp.server import lsp_definition

    async def _test():
        ctx = MagicMock()
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="def foo(): pass")),
            patch("mcp_servers.lsp.server.lsp_client") as mock_client,
        ):
            mock_client.sync_file = AsyncMock()
            mock_client.send_request = AsyncMock(return_value={"uri": "file:///path", "range": {}})
            res = await lsp_definition("/path/to/file.py", 1, 0, ctx)
            assert "/path" in res

    asyncio.run(_test())


def test_lsp_definition_string_fallback():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from mcp_servers.lsp.server import lsp_definition

    async def _test():
        ctx = MagicMock()
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="def foo(): pass")),
            patch("mcp_servers.lsp.server.lsp_client") as mock_client,
        ):
            mock_client.sync_file = AsyncMock()
            mock_client.send_request = AsyncMock(return_value="some string")
            res = await lsp_definition("/path/to/file.py", 1, 0, ctx)
            assert res == "some string"

    asyncio.run(_test())


def test_lsp_references_string_fallback():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from mcp_servers.lsp.server import lsp_references

    async def _test():
        ctx = MagicMock()
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="def foo(): pass")),
            patch("mcp_servers.lsp.server.lsp_client") as mock_client,
        ):
            mock_client.sync_file = AsyncMock()
            mock_client.send_request = AsyncMock(return_value="some string")
            res = await lsp_references("/path/to/file.py", 1, 0, ctx)
            assert res == "some string"

    asyncio.run(_test())


@pytest.mark.asyncio
async def test_lsp_diagnostics_with_items():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.get_diagnostics = MagicMock(return_value=[{"message": "err"}])

        res = await lsp_diagnostics("/path/to/file.py", ctx)
        assert "err" in res


@pytest.mark.asyncio
async def test_lsp_diagnostics_empty():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.get_diagnostics = MagicMock(return_value=[])

        res = await lsp_diagnostics("/path/to/file.py", ctx)
        assert "error-free" in res


@pytest.mark.asyncio
async def test_lsp_workspace_symbols_success():
    ctx = MagicMock()
    with patch("mcp_servers.lsp.server.lsp_client") as mock_client:
        mock_client.sessions = {"python": MagicMock()}
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
        (lsp_type_definition, ("/absolute/not/found.py", 1, 0)),
        (lsp_implementation, ("/absolute/not/found.py", 1, 0)),
        (lsp_document_highlight, ("/absolute/not/found.py", 1, 0)),
        (lsp_call_hierarchy, ("/absolute/not/found.py", 1, 0, "incoming")),
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
        (lsp_type_definition, ("/path/to/file.py", 1, 0)),
        (lsp_implementation, ("/path/to/file.py", 1, 0)),
        (lsp_document_highlight, ("/path/to/file.py", 1, 0)),
        (lsp_call_hierarchy, ("/path/to/file.py", 1, 0, "incoming")),
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
        mock_client.sessions = {"python": MagicMock()}
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
        (lsp_type_definition, ("/path/to/file.py", 1, 0)),
        (lsp_implementation, ("/path/to/file.py", 1, 0)),
        (lsp_document_highlight, ("/path/to/file.py", 1, 0)),
        (lsp_call_hierarchy, ("/path/to/file.py", 1, 0, "incoming")),
    ],
)
async def test_lsp_tools_exception(tool_func, args):
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sessions = {"python": MagicMock()}
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
        lsp_type_definition,
        lsp_implementation,
        lsp_document_highlight,
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
        (lsp_type_definition, ("/path/to/file.py", 1, 0)),
        (lsp_implementation, ("/path/to/file.py", 1, 0)),
        (lsp_document_highlight, ("/path/to/file.py", 1, 0)),
        (lsp_call_hierarchy, ("/path/to/file.py", 1, 0, "incoming")),
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


@pytest.mark.asyncio
async def test_lsp_call_hierarchy_invalid_direction():
    ctx = MagicMock()
    res = await lsp_call_hierarchy("/path/to/file.py", 1, 0, "invalid", ctx)
    assert "direction must be" in res


@pytest.mark.asyncio
async def test_lsp_call_hierarchy_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(
            side_effect=[
                [{"name": "foo"}],  # prepareCallHierarchy response
                [{"from": {"name": "bar"}}],  # incomingCalls response
            ]
        )

        res = await lsp_call_hierarchy("/path/to/file.py", 1, 0, "incoming", ctx)
        assert "bar" in res


@pytest.mark.asyncio
async def test_lsp_call_hierarchy_no_calls():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(
            side_effect=[
                [{"name": "foo"}],  # prepareCallHierarchy response
                None,  # incomingCalls response (no calls)
            ]
        )

        res = await lsp_call_hierarchy("/path/to/file.py", 1, 0, "incoming", ctx)
        assert "No incoming calls found" in res


@pytest.mark.asyncio
async def test_lsp_call_hierarchy_no_items():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value=None)

        res = await lsp_call_hierarchy("/path/to/file.py", 1, 0, "incoming", ctx)
        assert "No call hierarchy items found" in res


@pytest.mark.asyncio
async def test_lsp_type_definition_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value={"uri": "file:///path", "range": {}})

        res = await lsp_type_definition("/path/to/file.py", 1, 0, ctx)
        assert "/path" in res


@pytest.mark.asyncio
async def test_lsp_type_definition_list_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(
            return_value=[
                {"uri": "file:///path1", "range": {}},
                {"uri": "file:///path2", "range": {}},
            ]
        )

        res = await lsp_type_definition("/path/to/file.py", 1, 0, ctx)
        assert "/path1" in res
        assert "/path2" in res


@pytest.mark.asyncio
async def test_lsp_implementation_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value={"uri": "file:///path", "range": {}})

        res = await lsp_implementation("/path/to/file.py", 1, 0, ctx)
        assert "/path" in res


@pytest.mark.asyncio
async def test_lsp_implementation_list_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value=[{"uri": "file:///path1", "range": {}}])

        res = await lsp_implementation("/path/to/file.py", 1, 0, ctx)
        assert "/path1" in res


@pytest.mark.asyncio
async def test_lsp_document_highlight_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value=[{"range": {}}])

        res = await lsp_document_highlight("/path/to/file.py", 1, 0, ctx)
        assert "range" in res


@pytest.mark.asyncio
async def test_lsp_type_definition_string_fallback():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value="some string")
        res = await lsp_type_definition("/path/to/file.py", 1, 0, ctx)
        assert res == "some string"


@pytest.mark.asyncio
async def test_lsp_implementation_string_fallback():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="def foo(): pass")),
        patch("mcp_servers.lsp.server.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value="some string")
        res = await lsp_implementation("/path/to/file.py", 1, 0, ctx)
        assert res == "some string"


@pytest.mark.asyncio
async def test_lsp_call_hierarchy_invalid_line_char():
    ctx = MagicMock()
    with patch("pathlib.Path.exists", return_value=True):
        res = await lsp_call_hierarchy("/path/to/file.py", 0, 0, "incoming", ctx)
        assert "line must be >= 1" in res


@pytest.mark.asyncio
async def test_lsp_workspace_symbols_all_fail():
    from mcp_servers.lsp.server import lsp_workspace_symbols

    ctx = MagicMock()
    with patch("mcp_servers.lsp.server.lsp_client") as mock_client:
        mock_client.sessions = {"python": MagicMock(), "go": MagicMock()}
        mock_client.send_request = AsyncMock(side_effect=Exception("mock err"))

        res = await lsp_workspace_symbols("query", ctx)
        assert "No workspace symbols found" in res


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_lsp_workspace_symbols_outer_exception():
    from unittest.mock import PropertyMock

    from mcp_servers.lsp.server import lsp_workspace_symbols

    ctx = MagicMock()
    with patch("mcp_servers.lsp.server.lsp_client") as mock_client:
        type(mock_client).sessions = PropertyMock(side_effect=Exception("mock err"))
        res = await lsp_workspace_symbols("query", ctx)
        assert "Error querying LSP" in res


@pytest.mark.asyncio
async def test_lsp_workspace_symbols_outer_cancelled():
    import asyncio
    from unittest.mock import PropertyMock

    from mcp_servers.lsp.server import lsp_workspace_symbols

    ctx = MagicMock()
    with patch("mcp_servers.lsp.server.lsp_client") as mock_client:
        type(mock_client).sessions = PropertyMock(side_effect=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await lsp_workspace_symbols("query", ctx)
