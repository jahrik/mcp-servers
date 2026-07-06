from typing import Any

import pytest

from mcp_servers.lsp.client import LSPClient


@pytest.mark.asyncio
async def test_lsp_client_init() -> None:
    client = LSPClient(["dummy", "command"])
    assert client.command == ["dummy", "command"]
    assert client._process is None


@pytest.mark.asyncio
async def test_lsp_payload_handling() -> None:
    client = LSPClient(["dummy"])

    # Mock future
    import asyncio

    future: asyncio.Future[Any] = asyncio.Future()
    client._pending_requests[1] = future

    # Test successful response
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"foo": "bar"}}
    client._handle_payload(payload)

    assert future.done()
    assert future.result() == {"foo": "bar"}
