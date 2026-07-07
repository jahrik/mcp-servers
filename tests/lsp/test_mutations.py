from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from mcp_servers.lsp.tools.mutations import (
    apply_workspace_edit,
    lsp_code_actions,
    lsp_execute_code_action,
    lsp_rename,
)


def test_apply_workspace_edit_changes():
    edit = {
        "changes": {
            "file:///test.py": [
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

    with (
        patch("mcp_servers.lsp.utils.lsp_client"),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("builtins.open", mock_open(read_data="foo()\n")) as m_open,
    ):
        res = apply_workspace_edit(edit)
        assert "Updated /test.py" in res
        m_open().write.assert_called_with("bar()\n")


def test_apply_workspace_edit_document_changes():
    edit = {
        "documentChanges": [
            {
                "textDocument": {"uri": "file:///test.py"},
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

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("builtins.open", mock_open(read_data="line1\nline2\nline3\n")) as m_open,
    ):
        res = apply_workspace_edit(edit)
        assert "Updated /test.py" in res
        m_open().write.assert_called_with("line1\nline3\n")


def test_apply_workspace_edit_empty():
    assert apply_workspace_edit({}) == "No changes to apply."


def test_apply_workspace_edit_skipped():
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
            "file:///missing.py": [
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

    with patch("pathlib.Path.exists", return_value=False):
        res = apply_workspace_edit(edit)
        assert "Skipped /missing.py" in res


@pytest.mark.asyncio
async def test_lsp_rename_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("builtins.open", mock_open(read_data="foo\n")) as m_open,
        patch("mcp_servers.lsp.utils.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(
            return_value={
                "changes": {
                    "file:///path/to/file.py": [
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

        res = await lsp_rename("/path/to/file.py", 1, 0, "bar", ctx)
        assert "Updated /path/to/file.py" in res
        m_open().write.assert_called_with("bar\n")


@pytest.mark.asyncio
async def test_lsp_rename_not_found():
    ctx = MagicMock()
    with patch("pathlib.Path.exists", return_value=False):
        res = await lsp_rename("/path/to/file.py", 1, 0, "bar", ctx)
        assert "Error: File not found" in res


@pytest.mark.asyncio
async def test_lsp_rename_no_edits():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("builtins.open", mock_open(read_data="foo\n")),
        patch("mcp_servers.lsp.utils.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value=None)

        res = await lsp_rename("/path/to/file.py", 1, 0, "bar", ctx)
        assert "No rename edits returned." in res


@pytest.mark.asyncio
async def test_cancelled_errors():
    import asyncio

    from mcp_servers.lsp.tools.mutations import (
        lsp_code_actions,
        lsp_execute_code_action,
        lsp_rename,
    )

    ctx = MagicMock()
    with (
        patch("mcp_servers.lsp.utils._sync_file_with_lsp", side_effect=asyncio.CancelledError()),
        patch("pathlib.Path.exists", return_value=True),
    ):
        with pytest.raises(asyncio.CancelledError):
            await lsp_rename("/test.py", 1, 0, "bar", ctx)
        with pytest.raises(asyncio.CancelledError):
            await lsp_code_actions("/test.py", 1, 0, ctx)

    with patch("mcp_servers.lsp.utils.lsp_client") as mock_client:
        mock_client.send_request = AsyncMock(side_effect=asyncio.CancelledError())
        import mcp_servers.lsp.tools.mutations as m

        m._last_code_actions = {"actions": [{"command": "foo"}], "language_id": "python"}
        with pytest.raises(asyncio.CancelledError):
            await lsp_execute_code_action(0, ctx)


def test_apply_workspace_edit_value_error():
    edit = {"changes": {"file:///outside/test.py": []}}
    with patch("pathlib.Path.is_relative_to", side_effect=ValueError("outside")):
        res = apply_workspace_edit(edit)
        assert "Skipped /outside/test.py (outside workspace root)" in res


def test_apply_workspace_edit_does_not_exist():
    edit = {"changes": {"file:///test.py": []}}
    with (
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("pathlib.Path.exists", return_value=False),
    ):
        res = apply_workspace_edit(edit)
        assert "Skipped /test.py (does not exist)" in res


def test_apply_workspace_edit_append():
    edit = {
        "changes": {
            "file:///test.py": [
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
    with (
        patch("mcp_servers.lsp.utils.lsp_client"),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("builtins.open", mock_open(read_data="foo\n")),
    ):
        res = apply_workspace_edit(edit)
        assert "Updated /test.py" in res


@pytest.mark.asyncio
async def test_lsp_rename_error():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("mcp_servers.lsp.utils._sync_file_with_lsp", side_effect=Exception("mock err")),
    ):
        res = await lsp_rename("/path/to/file.py", 1, 0, "bar", ctx)
        assert "Error querying LSP for rename: mock err" in res


@pytest.mark.asyncio
async def test_lsp_code_actions_success():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("builtins.open", mock_open(read_data="foo\n")),
        patch("mcp_servers.lsp.utils.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(
            return_value=[{"title": "Fix it", "kind": "quickfix", "edit": {}}]
        )

        res = await lsp_code_actions("/path/to/file.py", 1, 0, ctx)
        assert "Available code actions:" in res
        assert "[0] Fix it" in res


@pytest.mark.asyncio
async def test_lsp_code_actions_not_found():
    ctx = MagicMock()
    with patch("pathlib.Path.exists", return_value=False):
        res = await lsp_code_actions("/path/to/file.py", 1, 0, ctx)
        assert "Error: File not found" in res


@pytest.mark.asyncio
async def test_lsp_code_actions_none():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("builtins.open", mock_open(read_data="foo\n")),
        patch("mcp_servers.lsp.utils.lsp_client") as mock_client,
    ):
        mock_client.sync_file = AsyncMock()
        mock_client.send_request = AsyncMock(return_value=[])

        res = await lsp_code_actions("/path/to/file.py", 1, 0, ctx)
        assert "No code actions available." in res


@pytest.mark.asyncio
async def test_lsp_code_actions_error():
    ctx = MagicMock()
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_relative_to", return_value=True),
        patch("mcp_servers.lsp.utils._sync_file_with_lsp", side_effect=Exception("mock err")),
    ):
        res = await lsp_code_actions("/path/to/file.py", 1, 0, ctx)
        assert "Error querying LSP for code actions: mock err" in res


@pytest.mark.asyncio
async def test_lsp_execute_code_action():
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
    ctx = MagicMock()

    with patch("mcp_servers.lsp.utils.lsp_client") as mock_client:
        mock_client.send_request = AsyncMock(return_value="cmd success")

        res = await lsp_execute_code_action(0, ctx)
        assert "Command 'test.cmd' executed." in res

        res = await lsp_execute_code_action(1, ctx)
        assert "No changes to apply." in res

        res = await lsp_execute_code_action(2, ctx)
        assert "Command 'test.string.cmd' executed." in res

        res = await lsp_execute_code_action(99, ctx)
        assert "Error: Invalid index" in res


@pytest.mark.asyncio
async def test_lsp_execute_code_action_returns_edit():
    from mcp_servers.lsp.tools import mutations

    mutations._last_code_actions = {
        "language_id": "python",
        "actions": [{"title": "Action with command returning edit", "command": "test.cmd"}],
    }
    ctx = MagicMock()

    with patch("mcp_servers.lsp.utils.lsp_client") as mock_client:
        mock_client.send_request = AsyncMock(return_value={"changes": {}})

        res = await lsp_execute_code_action(0, ctx)
        assert "Applying workspace edit from command:" in res
        assert "No changes to apply." in res


@pytest.mark.asyncio
async def test_lsp_execute_code_action_error():
    from mcp_servers.lsp.tools import mutations

    mutations._last_code_actions = {"language_id": "python", "actions": [{"command": "test.cmd"}]}
    ctx = MagicMock()

    with patch("mcp_servers.lsp.utils.lsp_client") as mock_client:
        mock_client.send_request = AsyncMock(side_effect=Exception("cmd err"))

        res = await lsp_execute_code_action(0, ctx)
        assert "Error executing command: cmd err" in res


@pytest.mark.asyncio
async def test_lsp_execute_code_action_no_edit_or_command():
    from mcp_servers.lsp.tools import mutations

    mutations._last_code_actions = {"language_id": "python", "actions": [{"title": "Empty action"}]}
    ctx = MagicMock()

    res = await lsp_execute_code_action(0, ctx)
    assert "executed but no edits or commands were found" in res
