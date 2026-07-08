from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from mcp_servers.lsp.models.schemas import (
    DocumentSymbolsArgs,
    WorkspaceSymbolsArgs,
)
from mcp_servers.lsp.tools import (
    lsp_document_symbols,
    lsp_workspace_symbols,
)


@pytest.mark.asyncio
async def test_lsp_document_symbols_success(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value=[{"name": "foo", "kind": 12}])

    args = DocumentSymbolsArgs(filepath=str(f))
    res = await lsp_document_symbols(args, ctx)
    assert "foo" in res


@pytest.mark.asyncio
async def test_lsp_document_symbols_full_detail(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value=[{"name": "foo", "kind": 12}])

    args = DocumentSymbolsArgs(filepath=str(f), detail="full")
    res = await lsp_document_symbols(args, ctx)
    assert '"kind": 12' in res


@pytest.mark.asyncio
async def test_lsp_document_symbols_invalid_detail():
    with pytest.raises(ValidationError):
        DocumentSymbolsArgs(filepath="/path/to/file.py", detail="bogus")  # type: ignore


@pytest.mark.asyncio
async def test_lsp_workspace_symbols_invalid_detail():
    with pytest.raises(ValidationError):
        WorkspaceSymbolsArgs(query="foo", detail="bogus")  # type: ignore


@pytest.mark.asyncio
async def test_lsp_workspace_symbols_success(mocker):
    ctx = mocker.MagicMock()
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sessions = {"python": mocker.MagicMock()}
    mock_client.send_request = mocker.AsyncMock(return_value=[{"name": "foo", "kind": 12}])

    args = WorkspaceSymbolsArgs(query="foo")
    res = await lsp_workspace_symbols(args, ctx)
    assert "foo" in res


@pytest.mark.asyncio
async def test_lsp_workspace_symbols_full_detail(mocker):
    ctx = mocker.MagicMock()
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sessions = {"python": mocker.MagicMock()}
    mock_client.send_request = mocker.AsyncMock(return_value=[{"name": "foo", "kind": 12}])

    args = WorkspaceSymbolsArgs(query="foo", detail="full")
    res = await lsp_workspace_symbols(args, ctx)
    assert '"kind": 12' in res


@pytest.mark.asyncio
async def test_lsp_workspace_symbols_all_fail(mocker):
    ctx = mocker.MagicMock()
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sessions = {"python": mocker.MagicMock(), "go": mocker.MagicMock()}
    mock_client.send_request = mocker.AsyncMock(side_effect=Exception("mock err"))

    args = WorkspaceSymbolsArgs(query="query")
    res = await lsp_workspace_symbols(args, ctx)
    assert "No workspace symbols found" in res


@pytest.mark.asyncio
async def test_lsp_workspace_symbols_outer_exception(mocker):
    ctx = mocker.MagicMock()
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    type(mock_client).sessions = mocker.PropertyMock(side_effect=Exception("mock err"))
    args = WorkspaceSymbolsArgs(query="query")
    res = await lsp_workspace_symbols(args, ctx)
    assert "Error querying LSP" in res


@pytest.mark.asyncio
async def test_lsp_workspace_symbols_outer_cancelled(mocker):
    ctx = mocker.MagicMock()
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    type(mock_client).sessions = mocker.PropertyMock(side_effect=asyncio.CancelledError())
    args = WorkspaceSymbolsArgs(query="query")
    with pytest.raises(asyncio.CancelledError):
        await lsp_workspace_symbols(args, ctx)


@pytest.mark.asyncio
async def test_lsp_document_symbols_with_filter(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(
        return_value=[
            {
                "name": "Widget",
                "kind": 5,  # Class
                "selectionRange": {"start": {"line": 0, "character": 6}},
                "children": [
                    {
                        "name": "render",
                        "kind": 6,  # Method
                        "selectionRange": {"start": {"line": 1, "character": 8}},
                    }
                ],
            }
        ]
    )

    # Compact with Method filter
    args_filter = DocumentSymbolsArgs(filepath=str(f), kinds=["Method"])
    res = await lsp_document_symbols(args_filter, ctx)
    assert "render" in res
    # Class Widget is kept as parent container
    assert "Widget" in res

    # Test top_level filter
    args_top = DocumentSymbolsArgs(filepath=str(f), top_level=True)
    res_top = await lsp_document_symbols(args_top, ctx)
    assert "Widget" in res_top
    assert "render" not in res_top


@pytest.mark.asyncio
async def test_lsp_workspace_symbols_with_filter(mocker):
    ctx = mocker.MagicMock()
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sessions = {"python": mocker.MagicMock()}
    mock_client.send_request = mocker.AsyncMock(
        return_value=[
            {
                "name": "Widget",
                "kind": 5,  # Class
                "location": {
                    "uri": "file:///path/to/file.py",
                    "range": {"start": {"line": 0, "character": 6}},
                },
            },
            {
                "name": "helper",
                "kind": 12,  # Function
                "location": {
                    "uri": "file:///path/to/file.py",
                    "range": {"start": {"line": 10, "character": 0}},
                },
            },
        ]
    )

    args = WorkspaceSymbolsArgs(query="Widget", kinds=["Function"])
    res = await lsp_workspace_symbols(args, ctx)
    assert "helper" in res
    assert "Widget" not in res


@pytest.mark.asyncio
async def test_lsp_document_symbols_filter_no_match(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(
        return_value=[
            {
                "name": "Widget",
                "kind": 5,  # Class
                "selectionRange": {"start": {"line": 0, "character": 6}},
            }
        ]
    )
    args = DocumentSymbolsArgs(filepath=str(f), kinds=["Method"])
    res = await lsp_document_symbols(args, ctx)
    assert res == "No matching symbols found in this document."


@pytest.mark.asyncio
async def test_lsp_workspace_symbols_filter_no_match(mocker):
    ctx = mocker.MagicMock()
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sessions = {"python": mocker.MagicMock()}
    mock_client.send_request = mocker.AsyncMock(
        return_value=[
            {
                "name": "Widget",
                "kind": 5,  # Class
                "location": {
                    "uri": "file:///path/to/file.py",
                    "range": {"start": {"line": 0, "character": 6}},
                },
            }
        ]
    )
    args = WorkspaceSymbolsArgs(query="Widget", kinds=["Method"])
    res = await lsp_workspace_symbols(args, ctx)
    assert "No workspace symbols found matching query" in res
