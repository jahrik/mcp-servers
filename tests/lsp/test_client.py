import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_servers.lsp.client import LSPClient, LSPError


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
    return LSPClient(["dummy", "cmd"])


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
    client = LSPClient(["dummy"])

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
    client = LSPClient(["dummy"])
    client._send = AsyncMock()

    # Method without ID
    client._handle_payload({"method": "window/logMessage", "params": {}})
    client._send.assert_not_called()

    # Method with ID (requires response)
    client._handle_payload({"id": 10, "method": "workspace/configuration", "params": {}})
    # asyncio.create_task is used, so we need to yield to event loop
    await asyncio.sleep(0.01)

    client._send.assert_called_once()
    payload = client._send.call_args[0][0]
    assert payload["id"] == 10
    assert payload["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_handle_payload_unhandled():
    client = LSPClient(["dummy"])
    # Shouldn't crash
    client._handle_payload({"unknown": "type"})


@pytest.mark.asyncio
async def test_handle_payload_publish_diagnostics():
    client = LSPClient(["dummy"])
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
