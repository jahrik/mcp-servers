import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_servers.lsp.client import LSPClient, LSPError, LSPSession


@pytest.fixture
def mock_process():
    process = MagicMock(spec=asyncio.subprocess.Process)

    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdin.drain = AsyncMock()

    process.stdout = AsyncMock()
    process.stderr = AsyncMock()

    process.terminate = MagicMock()
    process.kill = MagicMock()
    process.wait = AsyncMock()

    return process


@pytest.fixture
def client():
    return LSPSession(["dummy", "cmd"])


def test_lsp_error():
    err = LSPError(-32601, "Method not found", {"foo": "bar"})
    assert err.code == -32601
    assert err.message == "Method not found"
    assert err.data == {"foo": "bar"}
    assert str(err) == "LSP Error -32601: Method not found"


@pytest.mark.asyncio
async def test_start(client, mock_process):
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_process
        await client.start()

        mock_exec.assert_called_once_with(
            "dummy",
            "cmd",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert client._process == mock_process
        assert client._read_task is not None
        assert client._stderr_task is not None

        # calling start again should return immediately
        await client.start()
        mock_exec.assert_called_once()

        # Cleanup
        client.send_request = AsyncMock()
        client.send_notification = AsyncMock()
        await client.stop()


@pytest.mark.asyncio
async def test_stop(client, mock_process):
    await client.stop()  # Calling stop when not started does nothing

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_process
        await client.start()

        # Mock successful send_notification
        client.send_request = AsyncMock()
        client.send_notification = AsyncMock()

        await client.stop()

        client.send_request.assert_called_once_with("shutdown", None, timeout=5.0)
        client.send_notification.assert_called_once_with("exit", None)
        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_awaited_once()
        assert client._process is None


@pytest.mark.asyncio
async def test_stop_exception(client, mock_process):
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_process
        await client.start()

        client.send_request = AsyncMock(side_effect=Exception("mock err"))
        client.send_notification = AsyncMock()

        await client.stop()

        client.send_request.assert_called_once()
        client.send_notification.assert_not_called()
        mock_process.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_stop_timeout(client, mock_process):
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_process
        await client.start()

        # Make wait time out
        mock_process.wait.side_effect = [TimeoutError, None]
        client.send_request = AsyncMock()
        client.send_notification = AsyncMock()

        await client.stop()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()


@pytest.mark.asyncio
async def test_send(client, mock_process):
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_process
        await client.start()

        await client._send({"test": "data"})

        payload_bytes = b'{"test":"data"}'
        headers = f"Content-Length: {len(payload_bytes)}\r\n\r\n".encode("ascii")

        mock_process.stdin.write.assert_called_once_with(headers + payload_bytes)
        mock_process.stdin.drain.assert_awaited_once()

        # Reset process to None to test error
        client._process = None
        with pytest.raises(RuntimeError, match="LSP process is not running"):
            await client._send({})


@pytest.mark.asyncio
async def test_send_notification(client, mock_process):
    client._send = AsyncMock()
    await client.send_notification("test/method", {"foo": "bar"})
    client._send.assert_called_once_with(
        {"jsonrpc": "2.0", "method": "test/method", "params": {"foo": "bar"}}
    )

    # Test without params
    client._send.reset_mock()
    await client.send_notification("test/method")
    client._send.assert_called_once_with({"jsonrpc": "2.0", "method": "test/method"})


@pytest.mark.asyncio
async def test_send_request(client, mock_process):
    client._send = AsyncMock()

    # We need to simulate a response to fulfill the future
    async def mock_send(payload):
        req_id = payload["id"]
        # Fulfill future
        if req_id in client._pending_requests:
            client._pending_requests[req_id].set_result("success")

    client._send.side_effect = mock_send

    result = await client.send_request("test/req", {"foo": "bar"})
    assert result == "success"

    assert client._request_id == 1


@pytest.mark.asyncio
async def test_send_request_timeout(client):
    client._send = AsyncMock()

    # Never fulfill future
    with pytest.raises(TimeoutError, match="LSP Request test timed out after 0.01s"):
        await client.send_request("test", timeout=0.01)


@pytest.mark.asyncio
async def test_send_request_no_timeout(client):
    client._send = AsyncMock()

    async def mock_send(payload):
        client._pending_requests[payload["id"]].set_result("success")

    client._send.side_effect = mock_send

    result = await client.send_request("test", timeout=None)
    assert result == "success"


@pytest.mark.asyncio
async def test_initialize(client):
    client.send_request = AsyncMock(return_value={"capabilities": {}})
    client.send_notification = AsyncMock()

    res = await client.initialize("file:///tmp")
    assert res == {"capabilities": {}}
    client.send_request.assert_called_once()
    client.send_notification.assert_called_once_with("initialized", {})


@pytest.mark.asyncio
async def test_sync_file(client):
    client.send_notification = AsyncMock()
    await client.sync_file("file:///tmp/test.py", "python", "print('hello')")
    client.send_notification.assert_called_once()
    assert "didOpen" in client.send_notification.call_args[0][0]

    client.send_notification.reset_mock()
    await client.sync_file("file:///tmp/test.py", "python", "print('hello world')")
    client.send_notification.assert_called_once()
    assert "didChange" in client.send_notification.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_payload_response():
    client = LSPSession(["dummy"])

    future = asyncio.Future()
    client._pending_requests[1] = future

    # Success
    client._handle_payload({"id": 1, "result": "ok"})
    assert future.result() == "ok"

    # Error
    future2 = asyncio.Future()
    client._pending_requests[2] = future2
    client._handle_payload({"id": 2, "error": {"code": -1, "message": "err"}})
    with pytest.raises(LSPError, match="LSP Error -1: err"):
        future2.result()


@pytest.mark.asyncio
async def test_handle_payload_server_request():
    client = LSPSession(["dummy"])
    client._send = AsyncMock()

    # Method without ID
    client._handle_payload({"method": "window/logMessage", "params": {}})
    client._send.assert_not_called()

    # Method with ID (requires response)
    client._handle_payload({"id": 10, "method": "workspace/someUnknownMethod", "params": {}})
    # asyncio.create_task is used, so we need to yield to event loop
    await asyncio.sleep(0.01)

    client._send.assert_called_once()
    payload = client._send.call_args[0][0]
    assert payload["id"] == 10
    assert payload["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_handle_payload_unhandled():
    client = LSPSession(["dummy"])
    # Shouldn't crash
    client._handle_payload({"unknown": "type"})


@pytest.mark.asyncio
async def test_handle_payload_publish_diagnostics():
    client = LSPSession(["dummy"])
    client._handle_payload(
        {
            "method": "textDocument/publishDiagnostics",
            "params": {"uri": "file:///tmp/foo.py", "diagnostics": [{"message": "error1"}]},
        }
    )
    assert client.get_diagnostics("file:///tmp/foo.py") == [{"message": "error1"}]
    assert client.get_diagnostics("file:///tmp/other.py") is None


@pytest.mark.asyncio
async def test_stderr_loop(client, mock_process):
    mock_process.stderr.readline.side_effect = [b"log line\n", b""]
    client._process = mock_process

    await client._stderr_loop()


@pytest.mark.asyncio
async def test_stderr_loop_cancellation(client, mock_process):
    mock_process.stderr.readline.side_effect = asyncio.CancelledError
    client._process = mock_process

    await client._stderr_loop()
    # Should silently pass


@pytest.mark.asyncio
async def test_read_loop(client, mock_process):
    body = b'{"id": 1, "result": "ok"}'

    mock_process.stdout.readline.side_effect = [
        b"Content-Length: " + str(len(body)).encode("utf-8") + b"\r\n",
        b"\r\n",
        b"",  # EOF
    ]
    mock_process.stdout.readexactly.return_value = body

    client._process = mock_process
    client._handle_payload = MagicMock()

    await client._read_loop()

    client._handle_payload.assert_called_once_with({"id": 1, "result": "ok"})


@pytest.mark.asyncio
async def test_read_loop_empty_content(client, mock_process):
    mock_process.stdout.readline.side_effect = [
        b"Content-Length: 0\r\n",
        b"\r\n",
        b"",  # EOF
    ]

    client._process = mock_process
    client._handle_payload = MagicMock()

    await client._read_loop()
    client._handle_payload.assert_not_called()


@pytest.mark.asyncio
async def test_read_loop_invalid_content_length(client, mock_process):
    mock_process.stdout.readline.side_effect = [
        b"Content-Length: bad\r\n",
        b"\r\n",
        b"",  # EOF
    ]

    client._process = mock_process
    client._handle_payload = MagicMock()

    await client._read_loop()
    client._handle_payload.assert_not_called()


@pytest.mark.asyncio
async def test_read_loop_bad_json(client, mock_process):
    body = b"not json"

    mock_process.stdout.readline.side_effect = [
        b"Content-Length: " + str(len(body)).encode("utf-8") + b"\r\n",
        b"\r\n",
        b"",  # EOF
    ]
    mock_process.stdout.readexactly.return_value = body

    client._process = mock_process
    client._handle_payload = MagicMock()

    await client._read_loop()

    client._handle_payload.assert_not_called()


@pytest.mark.asyncio
async def test_read_loop_handle_payload_exception(client, mock_process):
    body = b'{"id": 1}'

    mock_process.stdout.readline.side_effect = [
        b"Content-Length: " + str(len(body)).encode("utf-8") + b"\r\n",
        b"\r\n",
        b"",  # EOF
    ]
    mock_process.stdout.readexactly.return_value = body

    client._process = mock_process
    client._handle_payload = MagicMock(side_effect=Exception("mock err"))

    await client._read_loop()
    # Should log and continue, ending on EOF
    client._handle_payload.assert_called_once()


@pytest.mark.asyncio
async def test_read_loop_exception(client, mock_process):
    mock_process.stdout.readline.side_effect = Exception("mock error")
    client._process = mock_process

    await client._read_loop()


@pytest.mark.asyncio
async def test_read_loop_cancellation_and_cleanup(client, mock_process):
    mock_process.stdout.readline.side_effect = asyncio.CancelledError
    client._process = mock_process

    future = asyncio.Future()
    client._pending_requests[1] = future

    await client._read_loop()

    with pytest.raises(RuntimeError, match="LSP connection closed"):
        future.result()
    assert len(client._pending_requests) == 0


@pytest.mark.asyncio
async def test_read_loop_unhandled_method_send_error(client, mock_process):
    body = b'{"jsonrpc": "2.0", "id": 999, "method": "unknown/method"}'
    mock_process.stdout.readline.side_effect = [
        b"Content-Length: " + str(len(body)).encode("utf-8") + b"\r\n",
        b"\r\n",
        b"",  # EOF
    ]
    mock_process.stdout.readexactly = AsyncMock(return_value=body)
    client._process = mock_process

    # Mock _send to raise an exception
    client._send = AsyncMock(side_effect=Exception("mock send error"))

    await client._read_loop()

    # Yield to the event loop so the background task runs
    await asyncio.sleep(0.01)

    # Should be called to send the error response, and the exception should be caught silently
    client._send.assert_called_once()


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
async def test_router_get_or_create_session(router):
    router.language_commands = {"python": [["pyright-langserver", "--stdio"]]}
    with patch("mcp_servers.lsp.client.LSPSession") as MockSession:
        mock_session = MockSession.return_value
        mock_session.is_alive.return_value = True
        mock_session.start = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.stop = AsyncMock()
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
        with patch("mcp_servers.lsp.client.LSPSession", return_value=mock_session):
            await router._get_or_create_sessions("python")
            mock_session.stop.assert_awaited_once()

        with pytest.raises(ValueError, match="Unsupported language: unknown"):
            await router._get_or_create_sessions("unknown")


@pytest.mark.asyncio
async def test_router_get_or_create_session_init_error(router):
    router.language_commands = {"python": [["pyright-langserver", "--stdio"]]}
    with patch("mcp_servers.lsp.client.LSPSession") as MockSession:
        mock_session = MockSession.return_value
        mock_session.start = AsyncMock()
        mock_session.initialize = AsyncMock(side_effect=Exception("init error"))
        mock_session.stop = AsyncMock()

        with pytest.raises(RuntimeError, match="All configured LSP servers failed to start"):
            await router._get_or_create_sessions("python")
        mock_session.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_sync_file(router):
    router.language_commands = {"python": [["pyright-langserver", "--stdio"]]}
    with patch.object(router, "_get_or_create_sessions") as mock_get:
        mock_session = MagicMock()
        mock_session.sync_file = AsyncMock()
        mock_session.command = ["pyright-langserver", "--stdio"]
        mock_get.return_value = [mock_session]

        await router.sync_file("file:///a.py", "python", "code")
        mock_session.sync_file.assert_awaited_once_with("file:///a.py", "python", "code")

        # Retry logic
        mock_session.sync_file = AsyncMock(side_effect=[RuntimeError("broken pipe"), None])
        await router.sync_file("file:///a.py", "python", "code")
        assert mock_session.sync_file.call_count == 2
        assert mock_get.call_count == 3


@pytest.mark.asyncio
async def test_router_send_request(router):
    router.language_commands = {"python": [["pyright-langserver", "--stdio"]]}
    with patch.object(router, "_get_or_create_sessions") as mock_get:
        mock_session = MagicMock()
        mock_session.send_request = AsyncMock(return_value="res")
        mock_session.capabilities = {}
        mock_session.command = ["pyright-langserver", "--stdio"]
        mock_get.return_value = [mock_session]

        res = await router.send_request("python", "method", "params", 10.0)
        assert res == "res"
        mock_session.send_request.assert_awaited_once_with("method", "params", 10.0)

        mock_session.send_request = AsyncMock(side_effect=[RuntimeError("broken pipe"), "res2"])
        res2 = await router.send_request("python", "method", "params", 10.0)
        assert res2 == "res2"
        assert mock_session.send_request.call_count == 2
        assert mock_get.call_count == 3


@pytest.mark.asyncio
async def test_router_send_notification(router):
    router.language_commands = {"python": [["pyright-langserver", "--stdio"]]}
    with patch.object(router, "_get_or_create_sessions") as mock_get:
        mock_session = MagicMock()
        mock_session.send_notification = AsyncMock()
        mock_session.command = ["pyright-langserver", "--stdio"]
        mock_get.return_value = [mock_session]

        await router.send_notification("python", "method", "params")
        mock_session.send_notification.assert_awaited_once_with("method", "params")

        mock_session.send_notification = AsyncMock(side_effect=[RuntimeError("broken pipe"), None])
        await router.send_notification("python", "method", "params")
        assert mock_session.send_notification.call_count == 2
        assert mock_get.call_count == 3


def test_router_get_diagnostics(router):
    assert router.get_diagnostics("uri", "python") is None

    mock_session = MagicMock()
    mock_session.get_diagnostics.return_value = ["diag"]
    router.sessions["python"] = [mock_session]

    assert router.get_diagnostics("uri", "python") == ["diag"]


@pytest.mark.asyncio
async def test_router_reap_loop_fast():
    import time

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_sleep.side_effect = [None, asyncio.CancelledError()]

        router = LSPClient(root_uri="file:///workspace")
        router.idle_timeout_secs = 0.01

        mock_session = MagicMock()
        mock_session.command = ["pyright-langserver", "--stdio"]
        mock_session.last_used = time.monotonic() - 1.0
        mock_session.stop = AsyncMock()
        router.sessions["python"] = [mock_session]

        await router._reap_loop()
        mock_session.stop.assert_awaited_once()
        assert router.sessions["python"] == [None]


def test_session_is_alive():
    session = LSPSession(["dummy"])
    assert session.is_alive() is False
    from unittest.mock import MagicMock

    session._process = MagicMock()
    session._process.returncode = None
    assert session.is_alive() is True
    session._process.returncode = 0
    assert session.is_alive() is False


@pytest.mark.asyncio
async def test_router_stop_with_sessions():
    router = LSPClient()
    mock_session = AsyncMock()
    router.sessions["python"] = [mock_session]
    await router.stop()
    mock_session.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_watch_loop():
    import asyncio
    from unittest.mock import MagicMock, patch

    with (
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("os.walk") as mock_walk,
        patch("pathlib.Path.stat") as mock_stat,
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_file", return_value=True),
    ):
        mock_sleep.side_effect = [None, None, asyncio.CancelledError()]

        # mock os.walk to return a file
        mock_walk.return_value = [("/workspace", [], ["file.py", "ignored.txt", ".git/config"])]

        # mock stat to return an mtime that changes
        mock_stat_1 = MagicMock(st_mtime_ns=100)
        mock_stat_2 = MagicMock(st_mtime_ns=200)
        # 1 call on first sleep, 1 call on second sleep
        mock_stat.side_effect = [mock_stat_1, mock_stat_2, Exception("stop")]

        router = LSPClient(root_uri="file:///workspace")
        mock_session = AsyncMock()
        mock_session.command = ["pyright-langserver", "--stdio"]
        router.sessions["python"] = [mock_session]

        await router._watch_loop()

        # Should have sent didChangeWatchedFiles
        mock_session.send_notification.assert_called_with(
            "workspace/didChangeWatchedFiles",
            {"changes": [{"uri": "file:///workspace/file.py", "type": 2}]},
        )


@pytest.mark.asyncio
async def test_session_incremental_sync():
    session = LSPSession(["dummy"])
    session._sync_kind = 2
    session.send_notification = AsyncMock()

    # initial sync
    await session.sync_file("file:///test.py", "python", "a\nb\n")
    session.send_notification.assert_called_with(
        "textDocument/didOpen",
        {
            "textDocument": {
                "uri": "file:///test.py",
                "languageId": "python",
                "version": 1,
                "text": "a\nb\n",
            }
        },
    )

    # second sync with change
    await session.sync_file("file:///test.py", "python", "a\nc\n")
    session.send_notification.assert_called_with(
        "textDocument/didChange",
        {
            "textDocument": {"uri": "file:///test.py", "version": 2},
            "contentChanges": [
                {
                    "range": {
                        "start": {"line": 1, "character": 0},
                        "end": {"line": 1, "character": 1},
                    },
                    "text": "c\n",
                }
            ],
        },
    )

    # fallback sync
    session._sync_kind = 1
    await session.sync_file("file:///test.py", "python", "a\nd\n")
    session.send_notification.assert_called_with(
        "textDocument/didChange",
        {
            "textDocument": {"uri": "file:///test.py", "version": 3},
            "contentChanges": [{"text": "a\nd\n"}],
        },
    )


@pytest.mark.asyncio
async def test_session_initialize_sync_kind():
    session = LSPSession(["dummy"])
    session.send_request = AsyncMock(
        return_value={"capabilities": {"textDocumentSync": {"change": 2}}}
    )
    session.send_notification = AsyncMock()

    await session.initialize("file:///test")
    assert session._sync_kind == 2

    session.send_request = AsyncMock(return_value={"capabilities": {"textDocumentSync": 1}})
    await session.initialize("file:///test")
    assert session._sync_kind == 1


@pytest.mark.asyncio
async def test_watch_loop_skips_git():
    client = LSPClient("file:///workspace")
    mock_session = AsyncMock()
    client.sessions["python"] = mock_session

    with (
        patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_file", return_value=True),
        patch("os.walk", return_value=[("/workspace/.git", [], ["test.py"])]),
    ):
        await client._watch_loop()
        mock_session.send_notification.assert_not_called()


@pytest.mark.asyncio
async def test_watch_loop_no_sessions():
    client = LSPClient("file:///workspace")
    with (
        patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_file", return_value=True),
    ):
        await client._watch_loop()


@pytest.mark.asyncio
async def test_watch_loop_not_file_uri():
    client = LSPClient("http:///workspace")
    await client._watch_loop()


@pytest.mark.asyncio
async def test_watch_loop_stat_fails():
    client = LSPClient("file:///workspace")
    mock_session = AsyncMock()
    client.sessions["python"] = mock_session

    def stat_fail(*args, **kwargs):
        raise OSError("Stat failed")

    with (
        patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]),
        patch("os.walk", return_value=[("/workspace", [], ["test.py"])]),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_file", return_value=True),
        patch("pathlib.Path.stat", side_effect=stat_fail),
    ):
        await client._watch_loop()
        mock_session.send_notification.assert_not_called()


@pytest.mark.asyncio
async def test_watch_loop_send_fails():
    client = LSPClient("file:///workspace")
    mock_session = AsyncMock()
    mock_session.command = ["pyright-langserver", "--stdio"]
    client.sessions["python"] = [mock_session]

    # Change to trigger notification
    mock_stat1 = MagicMock()
    mock_stat1.st_mtime_ns = 100
    mock_stat2 = MagicMock()
    mock_stat2.st_mtime_ns = 200

    mock_session.send_notification.side_effect = Exception("Send failed")

    with (
        patch("asyncio.sleep", side_effect=[None, None, asyncio.CancelledError()]),
        patch("os.walk", return_value=[("/workspace", [], ["test.py"])]),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_file", return_value=True),
        patch("pathlib.Path.stat", side_effect=[mock_stat1, mock_stat2, mock_stat2]),
    ):
        await client._watch_loop()
        assert mock_session.send_notification.call_count == 1


@pytest.mark.asyncio
async def test_watch_loop_create_delete():
    client = LSPClient("file:///workspace")
    mock_session = AsyncMock()
    mock_session.command = ["pyright-langserver", "--stdio"]
    client.sessions["python"] = [mock_session]

    mock_stat1 = MagicMock()
    mock_stat1.st_mtime_ns = 100
    mock_stat2 = MagicMock()
    mock_stat2.st_mtime_ns = 200

    def mock_walk_pass1(*args, **kwargs):
        return [("/workspace", [], ["test.py"])]

    def mock_walk_pass2(*args, **kwargs):
        return [("/workspace", [], ["test.py", "new.py"])]

    def mock_walk_pass3(*args, **kwargs):
        return [("/workspace", [], ["new.py"])]  # test.py deleted

    with (
        patch("asyncio.sleep", side_effect=[None, None, None, asyncio.CancelledError()]),
        patch("os.walk", side_effect=[mock_walk_pass1(), mock_walk_pass2(), mock_walk_pass3()]),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_file", return_value=True),
        patch("pathlib.Path.stat", return_value=mock_stat1),
    ):
        await client._watch_loop()
        # Pass 1: populate last_mtimes
        # Pass 2: new.py created (type 1)
        # Pass 3: test.py deleted (type 3)
        assert mock_session.send_notification.call_count == 2
        calls = mock_session.send_notification.call_args_list
        assert "type': 1" in str(calls[0])
        assert "type': 3" in str(calls[1])


@pytest.mark.asyncio
async def test_sync_file_incremental_diff_branches():
    session = LSPSession(["dummy"])
    session.send_notification = AsyncMock()
    session._sync_kind = 2  # Incremental

    # 1. No change
    await session.sync_file("file:///test.py", "python", "test")
    await session.sync_file("file:///test.py", "python", "test")
    session.send_notification.assert_called_once()  # Only the first one (didOpen)
    session.send_notification.reset_mock()

    # 2. i2 < len(old_lines)
    await session.sync_file("file:///test.py", "python", "test\nnew_line\n")
    session.send_notification.assert_called_once()
    session.send_notification.reset_mock()

    # 3. i2 < len(old_lines)
    session._document_texts["file:///test.py"] = "line1\nline2\nline3\n"
    session._document_versions["file:///test.py"] = 2
    await session.sync_file("file:///test.py", "python", "line1\nline2_changed\nline3\n")
    session.send_notification.assert_called_once()
    session.send_notification.reset_mock()

    # 4. empty old_lines
    session._document_texts["file:///test2.py"] = ""
    session._document_versions["file:///test2.py"] = 1
    await session.sync_file("file:///test2.py", "python", "test\n")
    session.send_notification.assert_called_once()


@pytest.mark.asyncio
async def test_lsp_session_settings_loading_and_configuration(tmp_path):
    session = LSPSession(["dummy"])
    session.send_request = AsyncMock(return_value={"capabilities": {}})
    session.send_notification = AsyncMock()

    # 1. Setup mock venv, pyproject.toml, and .vscode/settings.json
    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    import sys

    python_bin = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    python_path = venv_dir / python_bin
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("python")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.pyright]\nextraPaths = ["src/lib"]\n')

    vscode_dir = tmp_path / ".vscode"
    vscode_dir.mkdir()
    settings_json = vscode_dir / "settings.json"
    settings_json.write_text(
        '{\n  // comment\n  "python.analysis.indexing": false,\n  "python.analysis.extraPaths": ["src/my_extra"],\n  "someUrl": "https://example.com/api" // trailing comment\n}\n'
    )

    root_uri = tmp_path.resolve().as_uri()
    await session.initialize(root_uri)

    # 2. Check settings were loaded and merged correctly
    # Default python.analysis.indexing was overridden by settings.json
    assert session._get_configuration_for_section("python.analysis.indexing") is False
    assert session._get_configuration_for_section("python.analysis.extraPaths") == ["src/my_extra"]
    assert session._get_configuration_for_section("someUrl") == "https://example.com/api"

    # pyproject.toml setting
    assert session._get_configuration_for_section("pyright") == {"extraPaths": ["src/lib"]}

    # Auto-detected python path
    assert session._get_configuration_for_section("python.pythonPath") == str(python_path)

    # Nested and flat key reconstruction
    # Section "python" should return a dict containing analysis and pythonPath
    python_config = session._get_configuration_for_section("python")
    assert isinstance(python_config, dict)
    assert python_config["pythonPath"] == str(python_path)
    assert python_config["analysis"]["indexing"] is False
    assert python_config["analysis"]["extraPaths"] == ["src/my_extra"]


@pytest.mark.asyncio
async def test_lsp_session_handle_payload_workspace_configuration():
    session = LSPSession(["dummy"])
    session._send = AsyncMock()
    session._settings = {"python": {"venvPath": "/path/to/venv"}}

    # We call _handle_payload with workspace/configuration
    session._handle_payload(
        {
            "id": 123,
            "method": "workspace/configuration",
            "params": {"items": [{"section": "python"}]},
        }
    )

    # Yield to let asyncio task execute
    await asyncio.sleep(0.01)

    session._send.assert_called_once()
    payload = session._send.call_args[0][0]
    assert payload["id"] == 123
    assert payload["result"] == [{"venvPath": "/path/to/venv"}]


def test_get_configuration_for_section_missed_branches():
    session = LSPSession(["dummy"])
    session._settings = {
        "python": {"analysis": {"indexing": True}},
        "python.venvPath": "/flat/venv",
        "python.analysis.extraPaths": ["/paths"],
    }

    # Line 279: empty section
    assert session._get_configuration_for_section(None) == session._settings
    assert session._get_configuration_for_section("") == session._settings

    # Line 291 & 296: check nested match traversing pre-existing dict
    assert session._get_configuration_for_section("python.analysis") == {
        "indexing": True,
        "extraPaths": ["/paths"],
    }

    # Verify merging logic
    merged_config = session._get_configuration_for_section("python")
    assert merged_config == {
        "analysis": {"indexing": True, "extraPaths": ["/paths"]},
        "venvPath": "/flat/venv",
    }

    # Line 312: not found
    assert session._get_configuration_for_section("nonexistent") is None


@pytest.mark.asyncio
async def test_lsp_session_settings_loading_exceptions(tmp_path):
    session = LSPSession(["dummy"])
    session.send_request = AsyncMock(return_value={"capabilities": {}})
    session.send_notification = AsyncMock()

    # 1. Invalid pyproject.toml syntax (triggers line 352-353 exception)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("invalid = { [to\n")

    # 2. Invalid settings.json syntax (triggers line 368-369 exception)
    vscode_dir = tmp_path / ".vscode"
    vscode_dir.mkdir()
    settings_json = vscode_dir / "settings.json"
    settings_json.write_text("{ invalid json")

    root_uri = tmp_path.resolve().as_uri()
    await session.initialize(root_uri)
    # The initialization catches both exceptions safely and logs a warning, so it shouldn't crash
    assert session._settings == {"python.analysis.indexing": True}

    # 3. Overall exception handling (triggers line 370-371 exception)
    with patch("urllib.parse.unquote", side_effect=ValueError("unquote error")):
        await session.initialize("file:///invalid/path")
        # Should catch exception and not crash
        assert session._settings == {"python.analysis.indexing": True}


@pytest.mark.asyncio
async def test_concurrent_sessions_hover_merging():
    router = LSPClient()
    router.language_commands = {"python": [["s1"], ["s2"]]}

    mock_s1 = MagicMock()
    mock_s1.command = ["s1"]
    mock_s1.send_request = AsyncMock(return_value={"contents": ["content 1"]})
    mock_s1.is_alive.return_value = True

    mock_s2 = MagicMock()
    mock_s2.command = ["s2"]
    mock_s2.send_request = AsyncMock(return_value={"contents": "content 2"})
    mock_s2.is_alive.return_value = True

    router.sessions["python"] = [mock_s1, mock_s2]

    res = await router.send_request(
        "python",
        "textDocument/hover",
        {"textDocument": {"uri": "file:///a.py"}, "position": {"line": 1, "character": 1}},
    )
    assert res == {"contents": ["content 1", "content 2"]}


@pytest.mark.asyncio
async def test_concurrent_sessions_list_merging():
    router = LSPClient()
    router.language_commands = {"python": [["s1"], ["s2"]]}

    mock_s1 = MagicMock()
    mock_s1.command = ["s1"]
    mock_s1.send_request = AsyncMock(return_value=[{"uri": "file:///s1.py", "range": {}}])
    mock_s1.is_alive.return_value = True

    mock_s2 = MagicMock()
    mock_s2.command = ["s2"]
    mock_s2.send_request = AsyncMock(return_value=[{"uri": "file:///s2.py", "range": {}}])
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
async def test_concurrent_sessions_mutation_routing():
    router = LSPClient()
    router.language_commands = {"python": [["s1"], ["s2"]]}

    mock_s1 = MagicMock()
    mock_s1.command = ["s1"]
    mock_s1.capabilities = {"renameProvider": True}
    mock_s1.send_request = AsyncMock(return_value="rename_res")
    mock_s1.is_alive.return_value = True

    mock_s2 = MagicMock()
    mock_s2.command = ["s2"]
    mock_s2.capabilities = {"documentFormattingProvider": True}
    mock_s2.send_request = AsyncMock(return_value="format_res")
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
async def test_concurrent_sessions_optional_spawn_failure():
    router = LSPClient()
    router.language_commands = {"python": [["s1"], ["s2"]]}

    with patch("mcp_servers.lsp.client.LSPSession") as MockSession:
        # Mock first session to spawn successfully, second session to raise exception on start
        mock_s1 = MagicMock()
        mock_s1.is_alive.return_value = True
        mock_s1.start = AsyncMock()
        mock_s1.initialize = AsyncMock()
        mock_s1.command = ["s1"]

        mock_s2_start = AsyncMock(side_effect=Exception("spawn failure"))
        mock_s2 = MagicMock()
        mock_s2.is_alive.return_value = True
        mock_s2.start = mock_s2_start
        mock_s2.stop = AsyncMock()
        mock_s2.command = ["s2"]

        MockSession.side_effect = [mock_s1, mock_s2]

        # Should proceed since at least one session starts successfully
        sessions = await router._get_or_create_sessions("python")
        assert len(sessions) == 1
        assert sessions[0] == mock_s1
        assert router.sessions["python"] == [mock_s1, None]


@pytest.mark.asyncio
async def test_concurrent_sessions_coverage_gaps():
    # 1. Test line 539: MCP_LSP_COMMAND env var parsing in client initialization
    with patch.dict("os.environ", {"MCP_LSP_COMMAND": "custom-server --flag"}):
        c = LSPClient()
        assert c.language_commands["python"] == [["custom-server", "--flag"]]

    # 2. Test line 733: send_request raise RuntimeError when no active sessions
    c2 = LSPClient()
    with (
        patch.object(c2, "_get_or_create_sessions", return_value=[]),
        pytest.raises(RuntimeError, match="No active LSP sessions running"),
    ):
        await c2.send_request("python", "textDocument/hover")

    # Smart executeCommand capability routing & executeCommand retry logic (lines 748-754, 773-780, 781-785)
    c3 = LSPClient()
    c3.language_commands = {"python": [["s1"], ["s2"], ["s3"]]}

    mock_s1 = AsyncMock()
    mock_s1.command = ["s1"]
    mock_s1.capabilities = {
        "executeCommandProvider": {"commands": ["cmd.target"]},
        "renameProvider": True,
    }
    mock_s1.send_request.return_value = "s1_executed"
    mock_s1.is_alive.return_value = True

    mock_s2 = AsyncMock()
    mock_s2.command = ["s2"]
    mock_s2.capabilities = {"executeCommandProvider": {"commands": ["cmd.other"]}}
    mock_s2.send_request.return_value = "s2_executed"
    mock_s2.is_alive.return_value = True

    mock_s3 = AsyncMock()
    mock_s3.command = ["s3"]
    mock_s3.capabilities = {}
    mock_s3.send_request.return_value = "s3_executed"
    mock_s3.is_alive.return_value = True

    c3.sessions["python"] = [mock_s1, mock_s2, mock_s3]
    c3._get_or_create_sessions = AsyncMock(return_value=[mock_s1, mock_s2, mock_s3])

    res_cmd = await c3.send_request("python", "workspace/executeCommand", {"command": "cmd.target"})
    assert res_cmd == "s1_executed"

    # Test line 773-780: Mutation retry for executeCommand on RuntimeError
    mock_s1.send_request = AsyncMock(
        side_effect=[RuntimeError("retry executeCommand"), "s1_retry_success"]
    )
    res_cmd_retry = await c3.send_request(
        "python", "workspace/executeCommand", {"command": "cmd.target"}
    )
    assert res_cmd_retry == "s1_retry_success"

    # Test line 781-785: Mutation retry matching capability for rename
    mock_s1.send_request = AsyncMock(
        side_effect=[RuntimeError("retry rename"), "rename_retry_success"]
    )
    res_rename_retry = await c3.send_request("python", "textDocument/rename", {"newName": "foo"})
    assert res_rename_retry == "rename_retry_success"

    # Warn and route to first active session when no capability matches & retry fallback (line 790)
    mock_s1.capabilities = {}
    mock_s2.capabilities = {}
    mock_s3.capabilities = {}
    mock_s1.send_request = AsyncMock(
        side_effect=[RuntimeError("retry fallback formatting"), "formatting_fallback_success"]
    )
    res_fallback_retry = await c3.send_request("python", "textDocument/formatting", {})
    assert res_fallback_retry == "formatting_fallback_success"

    # Query retry once on RuntimeError (lines 805-810)
    mock_s1.send_request = AsyncMock(
        side_effect=[RuntimeError("query retry"), [{"uri": "file:///def.py"}]]
    )
    mock_s2.send_request = AsyncMock(return_value=ValueError("mock value error"))
    mock_s3.send_request = AsyncMock(return_value=[])
    res_query_retry = await c3.send_request("python", "textDocument/definition", {})
    assert res_query_retry == [{"uri": "file:///def.py"}]

    # Exception propagation (lines 816, 822)
    mock_s1.send_request = AsyncMock(side_effect=ValueError("val err"))
    mock_s2.send_request = AsyncMock(side_effect=TypeError("type err"))
    mock_s3.send_request = AsyncMock(side_effect=RuntimeError("runtime err"))
    with pytest.raises(ValueError, match="val err"):
        await c3.send_request("python", "textDocument/definition", {})

    # Return None when all queries return None (line 825)
    mock_s1.send_request = AsyncMock(return_value=None)
    mock_s2.send_request = AsyncMock(return_value=None)
    mock_s3.send_request = AsyncMock(return_value=None)
    res_none = await c3.send_request("python", "textDocument/definition", {})
    assert res_none is None

    # Query definition list merging dictionary items (lines 858-859)
    mock_s1.send_request = AsyncMock(return_value={"uri": "file:///foo.py"})
    mock_s2.send_request = AsyncMock(return_value=[{"uri": "file:///bar.py"}])
    mock_s3.send_request = AsyncMock(return_value=None)
    res_dict_merge = await c3.send_request("python", "textDocument/definition", {})
    assert res_dict_merge == [{"uri": "file:///foo.py"}, {"uri": "file:///bar.py"}]

    # Hover contents merging edge cases
    mock_s1.send_request = AsyncMock(return_value=None)
    mock_s2.send_request = AsyncMock(return_value={"contents": []})
    mock_s3.send_request = AsyncMock(return_value=None)
    res_hover_empty = await c3.send_request("python", "textDocument/hover", {})
    assert res_hover_empty is None

    mock_s1.send_request = AsyncMock(return_value="invalid hover response")
    mock_s2.send_request = AsyncMock(return_value={})
    mock_s3.send_request = AsyncMock(return_value=None)
    res_hover_invalid = await c3.send_request("python", "textDocument/hover", {})
    assert res_hover_invalid is None

    # Notification retry on RuntimeError
    mock_s1.send_notification = AsyncMock(side_effect=[RuntimeError("notif fail"), None])
    mock_s2.send_notification = AsyncMock()
    mock_s3.send_notification = AsyncMock()
    await c3.send_notification("python", "testMethod", {})
    assert mock_s1.send_notification.call_count == 2

    # Diagnostics lookup for unsupported language ID & force checks (lines 889-891)
    assert c3.get_diagnostics("uri", "unsupported") is None

    mock_s1.get_diagnostics = MagicMock(return_value=["diag1"])
    mock_s2.get_diagnostics = MagicMock(return_value=None)
    mock_s3.get_diagnostics = MagicMock(return_value=None)
    # force=False -> returns None since mock_s2 and mock_s3 have not published yet
    assert c3.get_diagnostics("uri", "python", force=False) is None
    # force=True -> returns merged diagnostics from mock_s1
    assert c3.get_diagnostics("uri", "python", force=True) == ["diag1"]
