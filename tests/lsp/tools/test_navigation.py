from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from mcp_servers.lsp import utils
from mcp_servers.lsp.models.schemas import (
    CallHierarchyArgs,
    DocumentSymbolsArgs,
    FilePathArgs,
    PositionArgs,
    WorkspaceSymbolsArgs,
)
from mcp_servers.lsp.tools import (
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
)


@pytest.fixture(autouse=True)
def clear_mtimes():
    utils._file_mtimes.clear()
    return


@pytest.mark.asyncio
async def test_lsp_hover_not_absolute(mocker):
    # Context initialization
    ctx = mocker.MagicMock()
    args = PositionArgs(filepath="relative/path.py", line=1, char=1)
    res = await lsp_hover(args, ctx)
    assert "must be within the workspace root" in res or "File not found" in res


@pytest.mark.asyncio
async def test_lsp_hover_not_found(mocker, tmp_path):
    ctx = mocker.MagicMock()
    args = PositionArgs(filepath=str(tmp_path / "not_found.py"), line=1, char=1)
    res = await lsp_hover(args, ctx)
    assert res.startswith("Error: File not found")


@pytest.mark.asyncio
async def test_lsp_hover_line_too_small():
    with pytest.raises(ValidationError):
        PositionArgs(filepath="/tmp/file.py", line=0, char=1)


@pytest.mark.asyncio
async def test_lsp_hover_success(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value={"contents": {"value": "docstring"}})

    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_hover(args, ctx)
    assert res == "docstring"

    # Test go / rust language deduction
    go_f = tmp_path / "file.go"
    go_f.write_text("def foo(): pass")
    args_go = PositionArgs(filepath=str(go_f), line=1, char=0)
    await lsp_hover(args_go, ctx)
    mock_client.sync_file.assert_called_with(go_f.as_uri(), "go", "def foo(): pass")

    rs_f = tmp_path / "file.rs"
    rs_f.write_text("def foo(): pass")
    args_rs = PositionArgs(filepath=str(rs_f), line=1, char=0)
    await lsp_hover(args_rs, ctx)
    mock_client.sync_file.assert_called_with(rs_f.as_uri(), "rust", "def foo(): pass")

    ts_f = tmp_path / "file.ts"
    ts_f.write_text("def foo(): pass")
    args_ts = PositionArgs(filepath=str(ts_f), line=1, char=0)
    await lsp_hover(args_ts, ctx)
    mock_client.sync_file.assert_called_with(ts_f.as_uri(), "typescript", "def foo(): pass")

    js_f = tmp_path / "file.js"
    js_f.write_text("def foo(): pass")
    args_js = PositionArgs(filepath=str(js_f), line=1, char=0)
    await lsp_hover(args_js, ctx)
    mock_client.sync_file.assert_called_with(js_f.as_uri(), "javascript", "def foo(): pass")


@pytest.mark.asyncio
async def test_lsp_hover_empty_response(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value=None)

    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_hover(args, ctx)
    assert res == "No hover information found at this position."


@pytest.mark.asyncio
async def test_lsp_hover_list_response(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(
        return_value={"contents": [{"value": "def foo()"}, "string_content"]}
    )

    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_hover(args, ctx)
    assert res == "def foo()\n\nstring_content"


@pytest.mark.asyncio
async def test_lsp_hover_string_response(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value={"contents": "just a string"})

    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_hover(args, ctx)
    assert res == "just a string"


@pytest.mark.asyncio
async def test_lsp_hover_error(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock(side_effect=Exception("mock error"))

    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_hover(args, ctx)
    assert res == "Error querying LSP: mock error"


@pytest.mark.asyncio
async def test_lsp_hover_cancelled(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock(side_effect=asyncio.CancelledError())

    args = PositionArgs(filepath=str(f), line=1, char=0)
    with pytest.raises(asyncio.CancelledError):
        await lsp_hover(args, ctx)


@pytest.mark.asyncio
async def test_lsp_hover_outside_workspace(mocker, monkeypatch):
    ctx = mocker.MagicMock()
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", "/var/lib")
    args = PositionArgs(filepath="/tmp/foo.py", line=1, char=1)
    res = await lsp_hover(args, ctx)
    assert "must be within the workspace root" in res


@pytest.mark.asyncio
async def test_lsp_definition_success(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value=[{"uri": "file:///path", "range": {}}])

    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_definition(args, ctx)
    assert "/path" in res


@pytest.mark.asyncio
async def test_lsp_references_success(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value=[{"uri": "file:///path", "range": {}}])

    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_references(args, ctx)
    assert "/path" in res


@pytest.mark.asyncio
async def test_lsp_call_hierarchy_invalid_detail():
    with pytest.raises(ValidationError):
        CallHierarchyArgs(
            filepath="/path/to/file.py",
            line=1,
            char=0,
            direction="incoming",
            detail="bogus",  # type: ignore
        )


def test_format_location():
    from mcp_servers.lsp.utils import _format_location

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


@pytest.mark.asyncio
async def test_format_location_single_dict(tmp_path, mocker):
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value={"uri": "file:///path", "range": {}})

    ctx = mocker.MagicMock()
    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_definition(args, ctx)
    assert "/path" in res


@pytest.mark.asyncio
async def test_lsp_definition_string_fallback(tmp_path, mocker):
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value="some string")

    ctx = mocker.MagicMock()
    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_definition(args, ctx)
    assert res == "some string"


@pytest.mark.asyncio
async def test_lsp_references_string_fallback(tmp_path, mocker):
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value="some string")

    ctx = mocker.MagicMock()
    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_references(args, ctx)
    assert res == "some string"


@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_func", "model_args"),
    [
        (lsp_definition, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_references, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_document_symbols, lambda p: DocumentSymbolsArgs(filepath=p)),
        (lsp_diagnostics, lambda p: FilePathArgs(filepath=p)),
        (lsp_type_definition, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_implementation, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_document_highlight, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (
            lsp_call_hierarchy,
            lambda p: CallHierarchyArgs(filepath=p, line=1, char=0, direction="incoming"),
        ),
    ],
)
async def test_lsp_tools_file_not_found(tool_func, model_args, mocker, tmp_path):
    ctx = mocker.MagicMock()
    p = str(tmp_path / "not_found.py")
    res = await tool_func(model_args(p), ctx)
    assert res.startswith("Error: File not found")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_func", "model_args"),
    [
        (lsp_definition, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_references, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_document_symbols, lambda p: DocumentSymbolsArgs(filepath=p)),
        (lsp_diagnostics, lambda p: FilePathArgs(filepath=p)),
        (lsp_workspace_symbols, lambda p: WorkspaceSymbolsArgs(query="query")),
        (lsp_type_definition, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_implementation, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_document_highlight, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (
            lsp_call_hierarchy,
            lambda p: CallHierarchyArgs(filepath=p, line=1, char=0, direction="incoming"),
        ),
    ],
)
async def test_lsp_tools_cancelled(tool_func, model_args, mocker, tmp_path):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sessions = {"python": mocker.MagicMock()}
    mock_client.sync_file = mocker.AsyncMock(side_effect=asyncio.CancelledError())
    mock_client.send_request = mocker.AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await tool_func(model_args(str(f)), ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_func", "model_args"),
    [
        (lsp_definition, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_references, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_document_symbols, lambda p: DocumentSymbolsArgs(filepath=p)),
        (lsp_diagnostics, lambda p: FilePathArgs(filepath=p)),
        (lsp_type_definition, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_implementation, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_document_highlight, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (
            lsp_call_hierarchy,
            lambda p: CallHierarchyArgs(filepath=p, line=1, char=0, direction="incoming"),
        ),
    ],
)
async def test_lsp_tools_exception(tool_func, model_args, mocker, tmp_path):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sessions = {"python": mocker.MagicMock()}
    mock_client.sync_file = mocker.AsyncMock(side_effect=Exception("mock error"))
    mock_client.send_request = mocker.AsyncMock(side_effect=Exception("mock error"))

    res = await tool_func(model_args(str(f)), ctx)
    assert "Error querying LSP" in res


@pytest.mark.asyncio
async def test_lsp_tools_invalid_line_char():
    with pytest.raises(ValidationError):
        PositionArgs(filepath="/path/to/file.py", line=0, char=0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_func", "model_args"),
    [
        (lsp_definition, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_references, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_document_symbols, lambda p: DocumentSymbolsArgs(filepath=p)),
        (lsp_workspace_symbols, lambda p: WorkspaceSymbolsArgs(query="query")),
        (lsp_diagnostics, lambda p: FilePathArgs(filepath=p)),
        (lsp_type_definition, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_implementation, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (lsp_document_highlight, lambda p: PositionArgs(filepath=p, line=1, char=0)),
        (
            lsp_call_hierarchy,
            lambda p: CallHierarchyArgs(filepath=p, line=1, char=0, direction="incoming"),
        ),
    ],
)
async def test_lsp_tools_no_response(tool_func, model_args, mocker, tmp_path):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value=None)
    mock_client.get_diagnostics = mocker.MagicMock(return_value=None)

    res = await tool_func(model_args(str(f)), ctx)
    assert "No" in res


@pytest.mark.asyncio
async def test_lsp_call_hierarchy_invalid_direction():
    from mcp_servers.lsp.models.schemas import CallHierarchyArgs

    with pytest.raises(ValidationError):
        CallHierarchyArgs(filepath="/path/to/file.py", line=1, char=0, direction="invalid")  # type: ignore


@pytest.mark.asyncio
async def test_lsp_call_hierarchy_success(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(
        side_effect=[
            [{"name": "foo"}],  # prepareCallHierarchy response
            [{"from": {"name": "bar"}}],  # incomingCalls response
        ]
    )

    args = CallHierarchyArgs(filepath=str(f), line=1, char=0, direction="incoming")
    res = await lsp_call_hierarchy(args, ctx)
    assert "bar" in res


@pytest.mark.asyncio
async def test_lsp_call_hierarchy_full_detail(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(
        side_effect=[
            [{"name": "foo"}],
            [{"from": {"name": "bar"}}],
        ]
    )

    args = CallHierarchyArgs(filepath=str(f), line=1, char=0, direction="incoming", detail="full")
    res = await lsp_call_hierarchy(args, ctx)
    assert '"from"' in res


@pytest.mark.asyncio
async def test_lsp_call_hierarchy_no_calls(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(
        side_effect=[
            [{"name": "foo"}],  # prepareCallHierarchy response
            None,  # incomingCalls response (no calls)
        ]
    )

    args = CallHierarchyArgs(filepath=str(f), line=1, char=0, direction="incoming")
    res = await lsp_call_hierarchy(args, ctx)
    assert "No incoming calls found" in res


@pytest.mark.asyncio
async def test_lsp_call_hierarchy_no_items(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value=None)

    args = CallHierarchyArgs(filepath=str(f), line=1, char=0, direction="incoming")
    res = await lsp_call_hierarchy(args, ctx)
    assert "No call hierarchy items found" in res


@pytest.mark.asyncio
async def test_lsp_type_definition_success(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value={"uri": "file:///path", "range": {}})

    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_type_definition(args, ctx)
    assert "/path" in res


@pytest.mark.asyncio
async def test_lsp_type_definition_list_success(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(
        return_value=[
            {"uri": "file:///path1", "range": {}},
            {"uri": "file:///path2", "range": {}},
        ]
    )

    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_type_definition(args, ctx)
    assert "/path1" in res
    assert "/path2" in res


@pytest.mark.asyncio
async def test_lsp_implementation_success(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value={"uri": "file:///path", "range": {}})

    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_implementation(args, ctx)
    assert "/path" in res


@pytest.mark.asyncio
async def test_lsp_implementation_list_success(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(
        return_value=[{"uri": "file:///path1", "range": {}}]
    )

    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_implementation(args, ctx)
    assert "/path1" in res


@pytest.mark.asyncio
async def test_lsp_document_highlight_success(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value=[{"range": {}}])

    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_document_highlight(args, ctx)
    assert "range" in res


@pytest.mark.asyncio
async def test_lsp_type_definition_string_fallback(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value="some string")
    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_type_definition(args, ctx)
    assert res == "some string"


@pytest.mark.asyncio
async def test_lsp_implementation_string_fallback(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("def foo(): pass")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value="some string")
    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_implementation(args, ctx)
    assert res == "some string"


@pytest.mark.asyncio
async def test_lsp_call_hierarchy_invalid_line_char():
    with pytest.raises(ValidationError):
        CallHierarchyArgs(filepath="/path/to/file.py", line=0, char=0, direction="incoming")


@pytest.mark.asyncio
async def test_lsp_references_capping(tmp_path, mocker):
    ctx = mocker.MagicMock()
    f = tmp_path / "file.py"
    f.write_text("")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    # Mock 105 references to trigger capping (> 100)
    refs = [
        {
            "uri": "file:///path/to/file.py",
            "range": {"start": {"line": i, "character": 0}},
        }
        for i in range(105)
    ]
    mock_client.send_request = mocker.AsyncMock(return_value=refs)

    mock_cap = mocker.patch(
        "mcp_servers.lsp.utils._cap_and_spill", side_effect=utils._cap_and_spill
    )
    args = PositionArgs(filepath=str(f), line=1, char=0)
    res = await lsp_references(args, ctx)
    mock_cap.assert_called_once()
    assert "... 5 more" in res
    assert "[Spilled full results to: " in res
