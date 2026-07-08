from __future__ import annotations

import asyncio

import pytest

from mcp_servers.lsp.client import LSPClient


@pytest.fixture
def router():
    return LSPClient(root_uri="file:///workspace")


@pytest.mark.asyncio
async def test_router_start_stop(router):
    await router.start()
    assert router._reap_task is not None
    await router.stop()
    assert router._reap_task is None
    assert len(router.sessions) == 0


@pytest.mark.asyncio
async def test_router_initialize(router):
    res = await router.initialize("file:///new_root")
    assert router.root_uri == "file:///new_root"
    assert "capabilities" in res


@pytest.mark.asyncio
async def test_router_get_or_create_session(router, mocker):
    router.language_commands = {"python": [["pyright-langserver", "--stdio"]]}
    MockSession = mocker.patch("mcp_servers.lsp.client.LSPSession")
    mock_session = MockSession.return_value
    mock_session.is_alive.return_value = True
    mock_session.start = mocker.AsyncMock()
    mock_session.initialize = mocker.AsyncMock()
    mock_session.stop = mocker.AsyncMock()
    mock_session.command = ["pyright-langserver", "--stdio"]

    sessions = await router._get_or_create_sessions("python")
    assert len(sessions) == 1
    assert sessions[0] == mock_session
    assert "python" in router.sessions
    assert router.sessions["python"] == [mock_session]
    mock_session.start.assert_awaited_once()
    mock_session.initialize.assert_awaited_once_with("file:///workspace")

    # Get existing alive session
    sessions2 = await router._get_or_create_sessions("python")
    assert len(sessions2) == 1
    assert sessions2[0] == mock_session
    assert mock_session.start.call_count == 1

    # Session crashed
    mock_session.is_alive.return_value = False
    mocker.patch("mcp_servers.lsp.client.LSPSession", return_value=mock_session)
    await router._get_or_create_sessions("python")
    mock_session.stop.assert_awaited_once()

    with pytest.raises(ValueError, match="Unsupported language: unknown"):
        await router._get_or_create_sessions("unknown")


@pytest.mark.asyncio
async def test_router_get_or_create_session_init_error(router, mocker):
    router.language_commands = {"python": [["pyright-langserver", "--stdio"]]}
    MockSession = mocker.patch("mcp_servers.lsp.client.LSPSession")
    mock_session = MockSession.return_value
    mock_session.start = mocker.AsyncMock()
    mock_session.initialize = mocker.AsyncMock(side_effect=Exception("init error"))
    mock_session.stop = mocker.AsyncMock()

    with pytest.raises(RuntimeError, match="All configured LSP servers failed to start"):
        await router._get_or_create_sessions("python")
    mock_session.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_sync_file(router, mocker):
    router.language_commands = {"python": [["pyright-langserver", "--stdio"]]}
    mock_get = mocker.patch.object(router, "_get_or_create_sessions")
    mock_session = mocker.MagicMock()
    mock_session.sync_file = mocker.AsyncMock()
    mock_session.command = ["pyright-langserver", "--stdio"]
    mock_get.return_value = [mock_session]

    await router.sync_file("file:///a.py", "python", "code")
    mock_session.sync_file.assert_awaited_once_with("file:///a.py", "python", "code")

    # Retry logic
    mock_session.sync_file = mocker.AsyncMock(side_effect=[RuntimeError("broken pipe"), None])
    await router.sync_file("file:///a.py", "python", "code")
    assert mock_session.sync_file.call_count == 2
    assert mock_get.call_count == 3


@pytest.mark.asyncio
async def test_router_send_request(router, mocker):
    router.language_commands = {"python": [["pyright-langserver", "--stdio"]]}
    mock_get = mocker.patch.object(router, "_get_or_create_sessions")
    mock_session = mocker.MagicMock()
    mock_session.send_request = mocker.AsyncMock(return_value="res")
    mock_session.capabilities = {}
    mock_session.command = ["pyright-langserver", "--stdio"]
    mock_get.return_value = [mock_session]

    res = await router.send_request("python", "method", "params", 10.0)
    assert res == "res"
    mock_session.send_request.assert_awaited_once_with("method", "params", 10.0)

    mock_session.send_request = mocker.AsyncMock(side_effect=[RuntimeError("broken pipe"), "res2"])
    res2 = await router.send_request("python", "method", "params", 10.0)
    assert res2 == "res2"
    assert mock_session.send_request.call_count == 2
    assert mock_get.call_count == 3


@pytest.mark.asyncio
async def test_router_send_notification(router, mocker):
    router.language_commands = {"python": [["pyright-langserver", "--stdio"]]}
    mock_get = mocker.patch.object(router, "_get_or_create_sessions")
    mock_session = mocker.MagicMock()
    mock_session.send_notification = mocker.AsyncMock()
    mock_session.command = ["pyright-langserver", "--stdio"]
    mock_get.return_value = [mock_session]

    await router.send_notification("python", "method", "params")
    mock_session.send_notification.assert_awaited_once_with("method", "params")

    mock_session.send_notification = mocker.AsyncMock(
        side_effect=[RuntimeError("broken pipe"), None]
    )
    await router.send_notification("python", "method", "params")
    assert mock_session.send_notification.call_count == 2
    assert mock_get.call_count == 3


def test_router_get_diagnostics(router, mocker):
    assert router.get_diagnostics("uri", "python") is None

    mock_session = mocker.MagicMock()
    mock_session.get_diagnostics.return_value = ["diag"]
    router.sessions["python"] = [mock_session]

    assert router.get_diagnostics("uri", "python") == ["diag"]


@pytest.mark.asyncio
async def test_router_reap_loop_fast(mocker):
    import time

    mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
    mock_sleep.side_effect = [None, asyncio.CancelledError()]

    router = LSPClient(root_uri="file:///workspace")
    router.idle_timeout_secs = 0.01

    mock_session = mocker.MagicMock()
    mock_session.command = ["pyright-langserver", "--stdio"]
    mock_session.last_used = time.monotonic() - 1.0
    mock_session.stop = mocker.AsyncMock()
    router.sessions["python"] = [mock_session]

    await router._reap_loop()
    mock_session.stop.assert_awaited_once()
    assert "python" not in router.sessions


@pytest.mark.asyncio
async def test_router_stop_with_sessions(mocker):
    router = LSPClient()
    mock_session = mocker.AsyncMock()
    router.sessions["python"] = [mock_session]
    await router.stop()
    mock_session.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_watch_loop(mocker):
    import asyncio

    mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
    mock_walk = mocker.patch("os.walk")
    mock_stat = mocker.patch("pathlib.Path.stat")
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)

    mock_sleep.side_effect = [None, None, asyncio.CancelledError()]

    # mock os.walk to return a file
    mock_walk.return_value = [("/workspace", [], ["file.py", "ignored.txt", ".git/config"])]

    # mock stat to return an mtime that changes
    mock_stat_1 = mocker.MagicMock(st_mtime_ns=100)
    mock_stat_2 = mocker.MagicMock(st_mtime_ns=200)
    # 1 call on first sleep, 1 call on second sleep
    mock_stat.side_effect = [mock_stat_1, mock_stat_2, Exception("stop")]

    router = LSPClient(root_uri="file:///workspace")
    mock_session = mocker.AsyncMock()
    mock_session.command = ["pyright-langserver", "--stdio"]
    router.sessions["python"] = [mock_session]

    await router._watch_loop()

    # Should have sent didChangeWatchedFiles
    mock_session.send_notification.assert_called_with(
        "workspace/didChangeWatchedFiles",
        {"changes": [{"uri": "file:///workspace/file.py", "type": 2}]},
    )


@pytest.mark.asyncio
async def test_watch_loop_skips_git(mocker):
    client = LSPClient("file:///workspace")
    mock_session = mocker.AsyncMock()
    client.sessions["python"] = mock_session

    mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()])
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("os.walk", return_value=[("/workspace/.git", [], ["test.py"])])

    await client._watch_loop()
    mock_session.send_notification.assert_not_called()


@pytest.mark.asyncio
async def test_watch_loop_no_sessions(mocker):
    client = LSPClient("file:///workspace")
    mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()])
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)

    await client._watch_loop()


@pytest.mark.asyncio
async def test_watch_loop_not_file_uri():
    client = LSPClient("http:///workspace")
    await client._watch_loop()


@pytest.mark.asyncio
async def test_watch_loop_stat_fails(mocker):
    client = LSPClient("file:///workspace")
    mock_session = mocker.AsyncMock()
    client.sessions["python"] = mock_session

    def stat_fail(*args, **kwargs):
        raise OSError("Stat failed")

    mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()])
    mocker.patch("os.walk", return_value=[("/workspace", [], ["test.py"])])
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.stat", side_effect=stat_fail)

    await client._watch_loop()
    mock_session.send_notification.assert_not_called()


@pytest.mark.asyncio
async def test_watch_loop_send_fails(mocker):
    client = LSPClient("file:///workspace")
    mock_session = mocker.AsyncMock()
    mock_session.command = ["pyright-langserver", "--stdio"]
    client.sessions["python"] = [mock_session]

    # Change to trigger notification
    mock_stat1 = mocker.MagicMock()
    mock_stat1.st_mtime_ns = 100
    mock_stat2 = mocker.MagicMock()
    mock_stat2.st_mtime_ns = 200

    mock_session.send_notification.side_effect = Exception("Send failed")

    mocker.patch("asyncio.sleep", side_effect=[None, None, asyncio.CancelledError()])
    mocker.patch("os.walk", return_value=[("/workspace", [], ["test.py"])])
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.stat", side_effect=[mock_stat1, mock_stat2, mock_stat2])

    await client._watch_loop()
    assert mock_session.send_notification.call_count == 1


@pytest.mark.asyncio
async def test_watch_loop_create_delete(mocker):
    client = LSPClient("file:///workspace")
    mock_session = mocker.AsyncMock()
    mock_session.command = ["pyright-langserver", "--stdio"]
    client.sessions["python"] = [mock_session]

    mock_stat1 = mocker.MagicMock()
    mock_stat1.st_mtime_ns = 100
    mock_stat2 = mocker.MagicMock()
    mock_stat2.st_mtime_ns = 200

    def mock_walk_pass1(*args, **kwargs):
        return [("/workspace", [], ["test.py"])]

    def mock_walk_pass2(*args, **kwargs):
        return [("/workspace", [], ["test.py", "new.py"])]

    def mock_walk_pass3(*args, **kwargs):
        return [("/workspace", [], ["new.py"])]  # test.py deleted

    mocker.patch("asyncio.sleep", side_effect=[None, None, None, asyncio.CancelledError()])
    mocker.patch("os.walk", side_effect=[mock_walk_pass1(), mock_walk_pass2(), mock_walk_pass3()])
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch("pathlib.Path.stat", return_value=mock_stat1)

    await client._watch_loop()
    # Pass 1: populate last_mtimes
    # Pass 2: new.py created (type 1)
    # Pass 3: test.py deleted (type 3)
    assert mock_session.send_notification.call_count == 2
    calls = mock_session.send_notification.call_args_list
    assert "type': 1" in str(calls[0])
    assert "type': 3" in str(calls[1])


@pytest.mark.asyncio
async def test_concurrent_sessions_hover_merging(mocker):
    router = LSPClient()
    router.language_commands = {"python": [["s1"], ["s2"]]}

    mock_s1 = mocker.MagicMock()
    mock_s1.command = ["s1"]
    mock_s1.send_request = mocker.AsyncMock(return_value={"contents": ["content 1"]})
    mock_s1.is_alive.return_value = True

    mock_s2 = mocker.MagicMock()
    mock_s2.command = ["s2"]
    mock_s2.send_request = mocker.AsyncMock(return_value={"contents": "content 2"})
    mock_s2.is_alive.return_value = True

    router.sessions["python"] = [mock_s1, mock_s2]

    res = await router.send_request(
        "python",
        "textDocument/hover",
        {"textDocument": {"uri": "file:///a.py"}, "position": {"line": 1, "character": 1}},
    )
    assert res == {"contents": ["content 1", "content 2"]}


@pytest.mark.asyncio
async def test_concurrent_sessions_list_merging(mocker):
    router = LSPClient()
    router.language_commands = {"python": [["s1"], ["s2"]]}

    mock_s1 = mocker.MagicMock()
    mock_s1.command = ["s1"]
    mock_s1.send_request = mocker.AsyncMock(return_value=[{"uri": "file:///s1.py", "range": {}}])
    mock_s1.is_alive.return_value = True

    mock_s2 = mocker.MagicMock()
    mock_s2.command = ["s2"]
    mock_s2.send_request = mocker.AsyncMock(return_value=[{"uri": "file:///s2.py", "range": {}}])
    mock_s2.is_alive.return_value = True

    router.sessions["python"] = [mock_s1, mock_s2]

    res = await router.send_request(
        "python",
        "textDocument/definition",
        {"textDocument": {"uri": "file:///a.py"}, "position": {"line": 1, "character": 1}},
    )
    assert res == [
        {"uri": "file:///s1.py", "range": {}},
        {"uri": "file:///s2.py", "range": {}},
    ]


@pytest.mark.asyncio
async def test_concurrent_sessions_mutation_routing(mocker):
    router = LSPClient()
    router.language_commands = {"python": [["s1"], ["s2"]]}

    mock_s1 = mocker.MagicMock()
    mock_s1.command = ["s1"]
    mock_s1.capabilities = {"renameProvider": True}
    mock_s1.send_request = mocker.AsyncMock(return_value="rename_res")
    mock_s1.is_alive.return_value = True

    mock_s2 = mocker.MagicMock()
    mock_s2.command = ["s2"]
    mock_s2.capabilities = {"documentFormattingProvider": True}
    mock_s2.send_request = mocker.AsyncMock(return_value="format_res")
    mock_s2.is_alive.return_value = True

    router.sessions["python"] = [mock_s1, mock_s2]

    # Format request should go to s2
    res_format = await router.send_request(
        "python", "textDocument/formatting", {"textDocument": {"uri": "file:///a.py"}}
    )
    assert res_format == "format_res"
    mock_s2.send_request.assert_awaited_once()
    mock_s1.send_request.assert_not_called()

    # Rename request should go to s1
    res_rename = await router.send_request(
        "python",
        "textDocument/rename",
        {"textDocument": {"uri": "file:///a.py"}, "newName": "new"},
    )
    assert res_rename == "rename_res"
    mock_s1.send_request.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_sessions_optional_spawn_failure(mocker):
    router = LSPClient()
    router.language_commands = {"python": [["s1"], ["s2"]]}

    MockSession = mocker.patch("mcp_servers.lsp.client.LSPSession")
    # Mock first session to spawn successfully, second session to raise exception on start
    mock_s1 = mocker.MagicMock()
    mock_s1.is_alive.return_value = True
    mock_s1.start = mocker.AsyncMock()
    mock_s1.initialize = mocker.AsyncMock()
    mock_s1.command = ["s1"]

    mock_s2_start = mocker.AsyncMock(side_effect=Exception("spawn failure"))
    mock_s2 = mocker.MagicMock()
    mock_s2.is_alive.return_value = True
    mock_s2.start = mock_s2_start
    mock_s2.stop = mocker.AsyncMock()
    mock_s2.command = ["s2"]

    MockSession.side_effect = [mock_s1, mock_s2]

    # Should proceed since at least one session starts successfully
    sessions = await router._get_or_create_sessions("python")
    assert len(sessions) == 1
    assert sessions[0] == mock_s1
    assert router.sessions["python"] == [mock_s1, None]


@pytest.mark.asyncio
async def test_concurrent_sessions_coverage_gaps(mocker):
    # 1. Test line 539: MCP_LSP_COMMAND env var parsing in client initialization
    mocker.patch.dict("os.environ", {"MCP_LSP_COMMAND": "custom-server --flag"})
    c = LSPClient()
    assert c.language_commands["python"] == [["custom-server", "--flag"]]

    # 2. Test line 733: send_request raise RuntimeError when no active sessions
    c2 = LSPClient()
    mocker.patch.object(c2, "_get_or_create_sessions", return_value=[])
    with pytest.raises(RuntimeError, match="No active LSP sessions running"):
        await c2.send_request("python", "textDocument/hover")

    # Smart executeCommand capability routing & executeCommand retry logic (lines 748-754, 773-780, 781-785)
    c3 = LSPClient()
    c3.language_commands = {"python": [["s1"], ["s2"], ["s3"]]}

    mock_s1 = mocker.AsyncMock()
    mock_s1.command = ["s1"]
    mock_s1.capabilities = {
        "executeCommandProvider": {"commands": ["cmd.target"]},
        "renameProvider": True,
    }
    mock_s1.send_request.return_value = "s1_executed"
    mock_s1.is_alive.return_value = True

    mock_s2 = mocker.AsyncMock()
    mock_s2.command = ["s2"]
    mock_s2.capabilities = {"executeCommandProvider": {"commands": ["cmd.other"]}}
    mock_s2.send_request.return_value = "s2_executed"
    mock_s2.is_alive.return_value = True

    mock_s3 = mocker.AsyncMock()
    mock_s3.command = ["s3"]
    mock_s3.capabilities = {}
    mock_s3.send_request.return_value = "s3_executed"
    mock_s3.is_alive.return_value = True

    c3.sessions["python"] = [mock_s1, mock_s2, mock_s3]
    c3._get_or_create_sessions = mocker.AsyncMock(return_value=[mock_s1, mock_s2, mock_s3])

    res_cmd = await c3.send_request("python", "workspace/executeCommand", {"command": "cmd.target"})
    assert res_cmd == "s1_executed"

    # Test line 773-780: Mutation retry for executeCommand on RuntimeError
    mock_s1.send_request = mocker.AsyncMock(
        side_effect=[RuntimeError("retry executeCommand"), "s1_retry_success"]
    )
    res_cmd_retry = await c3.send_request(
        "python", "workspace/executeCommand", {"command": "cmd.target"}
    )
    assert res_cmd_retry == "s1_retry_success"

    # Test line 781-785: Mutation retry matching capability for rename
    mock_s1.send_request = mocker.AsyncMock(
        side_effect=[RuntimeError("retry rename"), "rename_retry_success"]
    )
    res_rename_retry = await c3.send_request("python", "textDocument/rename", {"newName": "foo"})
    assert res_rename_retry == "rename_retry_success"

    # Warn and route to first active session when no capability matches & retry fallback (line 790)
    mock_s1.capabilities = {}
    mock_s2.capabilities = {}
    mock_s3.capabilities = {}
    mock_s1.send_request = mocker.AsyncMock(
        side_effect=[RuntimeError("retry fallback formatting"), "formatting_fallback_success"]
    )
    res_fallback_retry = await c3.send_request("python", "textDocument/formatting", {})
    assert res_fallback_retry == "formatting_fallback_success"

    # Query retry once on RuntimeError (lines 805-810)
    mock_s1.send_request = mocker.AsyncMock(
        side_effect=[RuntimeError("query retry"), [{"uri": "file:///def.py"}]]
    )
    mock_s2.send_request = mocker.AsyncMock(return_value=ValueError("mock value error"))
    mock_s3.send_request = mocker.AsyncMock(return_value=[])
    res_query_retry = await c3.send_request("python", "textDocument/definition", {})
    assert res_query_retry == [{"uri": "file:///def.py"}]

    # Exception propagation (lines 816, 822)
    mock_s1.send_request = mocker.AsyncMock(side_effect=ValueError("val err"))
    mock_s2.send_request = mocker.AsyncMock(side_effect=TypeError("type err"))
    mock_s3.send_request = mocker.AsyncMock(side_effect=RuntimeError("runtime err"))
    with pytest.raises(ValueError, match="val err"):
        await c3.send_request("python", "textDocument/definition", {})

    # Return None when all queries return None (line 825)
    mock_s1.send_request = mocker.AsyncMock(return_value=None)
    mock_s2.send_request = mocker.AsyncMock(return_value=None)
    mock_s3.send_request = mocker.AsyncMock(return_value=None)
    res_none = await c3.send_request("python", "textDocument/definition", {})
    assert res_none is None

    # Query definition list merging dictionary items (lines 858-859)
    mock_s1.send_request = mocker.AsyncMock(return_value={"uri": "file:///foo.py"})
    mock_s2.send_request = mocker.AsyncMock(return_value=[{"uri": "file:///bar.py"}])
    mock_s3.send_request = mocker.AsyncMock(return_value=None)
    res_dict_merge = await c3.send_request("python", "textDocument/definition", {})
    assert res_dict_merge == [{"uri": "file:///foo.py"}, {"uri": "file:///bar.py"}]

    # Hover contents merging edge cases
    mock_s1.send_request = mocker.AsyncMock(return_value=None)
    mock_s2.send_request = mocker.AsyncMock(return_value={"contents": []})
    mock_s3.send_request = mocker.AsyncMock(return_value=None)
    res_hover_empty = await c3.send_request("python", "textDocument/hover", {})
    assert res_hover_empty is None

    mock_s1.send_request = mocker.AsyncMock(return_value="invalid hover response")
    mock_s2.send_request = mocker.AsyncMock(return_value={})
    mock_s3.send_request = mocker.AsyncMock(return_value=None)
    res_hover_invalid = await c3.send_request("python", "textDocument/hover", {})
    assert res_hover_invalid is None

    # Notification retry on RuntimeError
    mock_s1.send_notification = mocker.AsyncMock(side_effect=[RuntimeError("notif fail"), None])
    mock_s2.send_notification = mocker.AsyncMock()
    mock_s3.send_notification = mocker.AsyncMock()
    await c3.send_notification("python", "testMethod", {})
    assert mock_s1.send_notification.call_count == 2

    # Diagnostics lookup for unsupported language ID & force checks (lines 889-891)
    assert c3.get_diagnostics("uri", "unsupported") is None

    mock_s1.get_diagnostics = mocker.MagicMock(return_value=["diag1"])
    mock_s2.get_diagnostics = mocker.MagicMock(return_value=None)
    mock_s3.get_diagnostics = mocker.MagicMock(return_value=None)
    # force=False -> returns None since mock_s2 and mock_s3 have not published yet
    assert c3.get_diagnostics("uri", "python", force=False) is None
    # force=True -> returns merged diagnostics from mock_s1
    assert c3.get_diagnostics("uri", "python", force=True) == ["diag1"]


@pytest.mark.asyncio
async def test_query_retry_session_not_found_after_refresh(mocker):
    c = LSPClient()
    c.language_commands = {"python": [["s1"], ["s2"]]}

    mock_s1 = mocker.MagicMock()
    mock_s1.command = ["s1"]
    mock_s1.capabilities = {}
    mock_s1.is_alive.return_value = True
    mock_s1.send_request = mocker.AsyncMock(side_effect=RuntimeError("broken"))

    mock_s2 = mocker.MagicMock()
    mock_s2.command = ["s2"]
    mock_s2.capabilities = {}
    mock_s2.is_alive.return_value = True
    mock_s2.send_request = mocker.AsyncMock(return_value=[{"uri": "file:///ok.py"}])

    c.sessions["python"] = [mock_s1, mock_s2]

    # After refresh, only s2 is available (s1 failed to restart)
    mock_s2_fresh = mocker.MagicMock()
    mock_s2_fresh.command = ["s2"]
    mock_s2_fresh.capabilities = {}
    mock_s2_fresh.is_alive.return_value = True

    original = c._get_or_create_sessions
    call_count = [0]

    async def patched_get_or_create(lang):
        call_count[0] += 1
        if call_count[0] == 1:
            return await original(lang)
        return [mock_s2_fresh]

    mocker.patch.object(c, "_get_or_create_sessions", side_effect=patched_get_or_create)
    result = await c.send_request("python", "textDocument/definition", {})

    # s1's RuntimeError becomes an exception (no matching session on refresh),
    # s2's original success carries through
    assert result == [{"uri": "file:///ok.py"}]
