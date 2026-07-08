from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from mcp_servers.lsp.models.schemas import (
    CodeActionsArgs,
    ExecuteCodeActionArgs,
    FilePathArgs,
    RenameArgs,
)
from mcp_servers.lsp.tools.mutations import (
    apply_workspace_edit,
    lsp_code_actions,
    lsp_execute_code_action,
    lsp_format,
    lsp_rename,
)


def test_apply_workspace_edit_changes(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "test.py"
    test_file.write_text("foo()\n")

    edit = {
        "changes": {
            test_file.as_uri(): [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 3},
                    },
                    "newText": "bar",
                }
            ]
        }
    }

    res = apply_workspace_edit(edit)
    assert f"Updated {test_file.resolve()}" in res
    assert test_file.read_text() == "bar()\n"


def test_apply_workspace_edit_document_changes(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "test.py"
    test_file.write_text("line1\nline2\nline3\n")

    edit = {
        "documentChanges": [
            {
                "textDocument": {"uri": test_file.as_uri()},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 1, "character": 0},
                            "end": {"line": 2, "character": 0},
                        },
                        "newText": "",
                    }
                ],
            }
        ]
    }

    res = apply_workspace_edit(edit)
    assert f"Updated {test_file.resolve()}" in res
    assert test_file.read_text() == "line1\nline3\n"


def test_apply_workspace_edit_empty():
    assert apply_workspace_edit({}) == "No changes to apply."


def test_apply_workspace_edit_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    missing_file = tmp_path / "missing.py"
    edit = {
        "changes": {
            "http://example.com/test.py": [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 3},
                    },
                    "newText": "bar",
                }
            ],
            missing_file.as_uri(): [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 3},
                    },
                    "newText": "bar",
                }
            ],
        }
    }

    res = apply_workspace_edit(edit)
    assert f"Skipped {missing_file.resolve()}" in res


@pytest.mark.asyncio
async def test_lsp_rename_success(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "file.py"
    test_file.write_text("foo\n")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(
        return_value={
            "changes": {
                test_file.as_uri(): [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 3},
                        },
                        "newText": "bar",
                    }
                ]
            }
        }
    )

    ctx = mocker.MagicMock()
    args = RenameArgs(filepath=str(test_file), line=1, character=0, new_name="bar")
    res = await lsp_rename(args, ctx)
    assert f"Updated {test_file.resolve()}" in res
    assert test_file.read_text() == "bar\n"


@pytest.mark.asyncio
async def test_lsp_rename_not_found(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    missing_file = tmp_path / "file.py"
    ctx = mocker.MagicMock()
    args = RenameArgs(filepath=str(missing_file), line=1, character=0, new_name="bar")
    res = await lsp_rename(args, ctx)
    assert "Error: File not found" in res


@pytest.mark.asyncio
async def test_lsp_rename_no_edits(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "file.py"
    test_file.write_text("foo\n")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value=None)

    ctx = mocker.MagicMock()
    args = RenameArgs(filepath=str(test_file), line=1, character=0, new_name="bar")
    res = await lsp_rename(args, ctx)
    assert "No rename edits returned." in res


@pytest.mark.asyncio
async def test_cancelled_errors(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "test.py"
    test_file.write_text("foo\n")

    mocker.patch("mcp_servers.lsp.utils._sync_file_with_lsp", side_effect=asyncio.CancelledError())

    ctx = mocker.MagicMock()
    with pytest.raises(asyncio.CancelledError):
        await lsp_rename(
            RenameArgs(filepath=str(test_file), line=1, character=0, new_name="bar"), ctx
        )
    with pytest.raises(asyncio.CancelledError):
        await lsp_code_actions(CodeActionsArgs(filepath=str(test_file), line=1, character=0), ctx)

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.send_request = mocker.AsyncMock(side_effect=asyncio.CancelledError())
    import mcp_servers.lsp.tools.mutations as m

    m._last_code_actions = {"actions": [{"command": "foo"}], "language_id": "python"}
    with pytest.raises(asyncio.CancelledError):
        await lsp_execute_code_action(ExecuteCodeActionArgs(index=0), ctx)


def test_apply_workspace_edit_value_error(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    mocker.patch("pathlib.Path.is_relative_to", side_effect=ValueError("outside"))
    edit = {"changes": {"file:///outside/test.py": []}}
    res = apply_workspace_edit(edit)
    assert "Skipped /outside/test.py (outside workspace root)" in res


def test_apply_workspace_edit_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "test.py"
    edit = {"changes": {test_file.as_uri(): []}}
    res = apply_workspace_edit(edit)
    assert f"Skipped {test_file.resolve()} (does not exist)" in res


def test_apply_workspace_edit_append(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "test.py"
    test_file.write_text("foo\n")
    edit = {
        "changes": {
            test_file.as_uri(): [
                {
                    "range": {
                        "start": {"line": 1, "character": 0},
                        "end": {"line": 1, "character": 0},
                    },
                    "newText": "bar\n",
                }
            ]
        }
    }
    res = apply_workspace_edit(edit)
    assert f"Updated {test_file.resolve()}" in res
    assert test_file.read_text() == "foo\nbar\n"


def test_apply_workspace_edit_multiline_out_of_bounds(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "test.py"
    test_file.write_text("foo\n")
    edit = {
        "changes": {
            test_file.as_uri(): [
                {
                    "range": {
                        "start": {"line": 5, "character": 0},
                        "end": {"line": 6, "character": 0},
                    },
                    "newText": "appended\n",
                }
            ]
        }
    }
    res = apply_workspace_edit(edit)
    assert f"Updated {test_file.resolve()}" in res
    assert test_file.read_text() == "foo\nappended\n"


@pytest.mark.asyncio
async def test_lsp_rename_error(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "file.py"
    test_file.write_text("foo\n")
    mocker.patch("mcp_servers.lsp.utils._sync_file_with_lsp", side_effect=Exception("mock err"))
    ctx = mocker.MagicMock()
    res = await lsp_rename(
        RenameArgs(filepath=str(test_file), line=1, character=0, new_name="bar"), ctx
    )
    assert "Error querying LSP for rename: mock err" in res


@pytest.mark.asyncio
async def test_lsp_code_actions_success(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "file.py"
    test_file.write_text("foo\n")
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(
        return_value=[{"title": "Fix it", "kind": "quickfix", "edit": {}}]
    )
    ctx = mocker.MagicMock()
    res = await lsp_code_actions(CodeActionsArgs(filepath=str(test_file), line=1, character=0), ctx)
    assert "Available code actions:" in res
    assert "[0] Fix it" in res


@pytest.mark.asyncio
async def test_lsp_code_actions_not_found(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    missing_file = tmp_path / "file.py"
    ctx = mocker.MagicMock()
    res = await lsp_code_actions(
        CodeActionsArgs(filepath=str(missing_file), line=1, character=0), ctx
    )
    assert "Error: File not found" in res


@pytest.mark.asyncio
async def test_lsp_code_actions_none(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "file.py"
    test_file.write_text("foo\n")
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value=[])
    ctx = mocker.MagicMock()
    res = await lsp_code_actions(CodeActionsArgs(filepath=str(test_file), line=1, character=0), ctx)
    assert "No code actions available." in res


@pytest.mark.asyncio
async def test_lsp_code_actions_error(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "file.py"
    test_file.write_text("foo\n")
    mocker.patch("mcp_servers.lsp.utils._sync_file_with_lsp", side_effect=Exception("mock err"))
    ctx = mocker.MagicMock()
    res = await lsp_code_actions(CodeActionsArgs(filepath=str(test_file), line=1, character=0), ctx)
    assert "Error querying LSP for code actions: mock err" in res


@pytest.mark.asyncio
async def test_lsp_execute_code_action(mocker):
    from mcp_servers.lsp.tools import mutations

    mutations._last_code_actions = {
        "language_id": "python",
        "actions": [
            {
                "title": "Action with command",
                "command": {"command": "test.cmd", "arguments": ["arg1"]},
            },
            {"title": "Action with edit", "edit": {"changes": {}}},
            {"title": "Action with string command", "command": "test.string.cmd"},
        ],
    }
    ctx = mocker.MagicMock()
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.send_request = mocker.AsyncMock(return_value="cmd success")

    res = await lsp_execute_code_action(ExecuteCodeActionArgs(index=0), ctx)
    assert "Command 'test.cmd' executed." in res

    res = await lsp_execute_code_action(ExecuteCodeActionArgs(index=1), ctx)
    assert "No changes to apply." in res

    res = await lsp_execute_code_action(ExecuteCodeActionArgs(index=2), ctx)
    assert "Command 'test.string.cmd' executed." in res

    res = await lsp_execute_code_action(ExecuteCodeActionArgs(index=99), ctx)
    assert "Error: Invalid index" in res


@pytest.mark.asyncio
async def test_lsp_code_actions_invalid_bounds():
    with pytest.raises(ValidationError):
        CodeActionsArgs(filepath="/path/to/file.py", line=0, character=0)


@pytest.mark.asyncio
async def test_lsp_rename_invalid_bounds():
    with pytest.raises(ValidationError):
        RenameArgs(filepath="/path/to/file.py", line=1, character=-1, new_name="bar")


@pytest.mark.asyncio
async def test_lsp_execute_code_action_returns_edit(mocker):
    from mcp_servers.lsp.tools import mutations

    mutations._last_code_actions = {
        "language_id": "python",
        "actions": [{"title": "Action with command returning edit", "command": "test.cmd"}],
    }
    ctx = mocker.MagicMock()
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.send_request = mocker.AsyncMock(return_value={"changes": {}})

    res = await lsp_execute_code_action(ExecuteCodeActionArgs(index=0), ctx)
    assert "Applying workspace edit from command:" in res
    assert "No changes to apply." in res


@pytest.mark.asyncio
async def test_lsp_execute_code_action_error(mocker):
    from mcp_servers.lsp.tools import mutations

    mutations._last_code_actions = {"language_id": "python", "actions": [{"command": "test.cmd"}]}
    ctx = mocker.MagicMock()
    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.send_request = mocker.AsyncMock(side_effect=Exception("cmd err"))

    res = await lsp_execute_code_action(ExecuteCodeActionArgs(index=0), ctx)
    assert "Error executing command: cmd err" in res


@pytest.mark.asyncio
async def test_lsp_execute_code_action_no_edit_or_command(mocker):
    from mcp_servers.lsp.tools import mutations

    mutations._last_code_actions = {"language_id": "python", "actions": [{"title": "Empty action"}]}
    ctx = mocker.MagicMock()

    res = await lsp_execute_code_action(ExecuteCodeActionArgs(index=0), ctx)
    assert "executed but no edits or commands were found" in res


@pytest.mark.asyncio
async def test_lsp_format_success(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "test.py"
    test_file.write_text("foo()\n")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(
        return_value=[
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 3},
                },
                "newText": "formatted",
            }
        ]
    )

    ctx = mocker.MagicMock()
    res = await lsp_format(FilePathArgs(filepath=str(test_file)), ctx)
    assert f"Updated {test_file.resolve()}" in res
    assert test_file.read_text() == "formatted()\n"


@pytest.mark.asyncio
async def test_lsp_format_invalid_file(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    ctx = mocker.MagicMock()
    res = await lsp_format(FilePathArgs(filepath=str(tmp_path / "nope.py")), ctx)
    assert "Error: File not found" in res


@pytest.mark.asyncio
async def test_lsp_format_no_changes(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "test.py"
    test_file.write_text("foo()\n")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(return_value=[])

    ctx = mocker.MagicMock()
    res = await lsp_format(FilePathArgs(filepath=str(test_file)), ctx)
    assert res == "No formatting changes returned."


@pytest.mark.asyncio
async def test_lsp_format_exception(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "test.py"
    test_file.write_text("foo()\n")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(side_effect=Exception("formatting error"))

    ctx = mocker.MagicMock()
    res = await lsp_format(FilePathArgs(filepath=str(test_file)), ctx)
    assert "Error formatting file: formatting error" in res


@pytest.mark.asyncio
async def test_lsp_format_cancelled(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    test_file = tmp_path / "test.py"
    test_file.write_text("foo()\n")

    mock_client = mocker.patch("mcp_servers.lsp.utils.lsp_client")
    mock_client.sync_file = mocker.AsyncMock()
    mock_client.send_request = mocker.AsyncMock(side_effect=asyncio.CancelledError())

    ctx = mocker.MagicMock()
    with pytest.raises(asyncio.CancelledError):
        await lsp_format(FilePathArgs(filepath=str(test_file)), ctx)
