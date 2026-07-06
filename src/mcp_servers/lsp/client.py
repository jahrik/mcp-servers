from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LSPError(Exception):
    """Exception raised for errors returned by the LSP server."""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"LSP Error {code}: {message}")


class LSPClient:
    """A client for managing the lifecycle and JSON-RPC transport to a language server subprocess."""

    def __init__(self, command: list[str]) -> None:
        self.command = command
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending_requests: dict[int, asyncio.Future[Any]] = {}
        self._read_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._document_versions: dict[str, int] = {}
        self._diagnostics: dict[str, list[Any]] = {}

    async def start(self) -> None:
        """Start the LSP subprocess."""
        if self._process is not None:
            return

        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info(f"Started LSP process: {' '.join(self.command)}")

        # Start background tasks for reading stdout and stderr
        self._read_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())

    async def stop(self) -> None:
        """Stop the LSP subprocess."""
        if self._process is None:
            return

        # Try to send exit notification if possible
        try:
            await self.send_request("shutdown", None, timeout=5.0)
            await self.send_notification("exit", None)
        except Exception as e:
            logger.debug(f"Failed to send exit notification: {e}")

        # Cancel tasks
        if self._read_task:
            self._read_task.cancel()
        if self._stderr_task:
            self._stderr_task.cancel()

        tasks_to_await = [t for t in (self._read_task, self._stderr_task) if t]
        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)

        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except TimeoutError:
            logger.warning("LSP process did not terminate gracefully, killing it.")
            self._process.kill()
            await self._process.wait()

        self._process = None
        self._pending_requests.clear()
        self._document_versions.clear()
        self._diagnostics.clear()
        logger.info("Stopped LSP process.")

    async def _read_loop(self) -> None:
        """Background task to read stdout from the LSP server."""
        if not self._process or not self._process.stdout:
            return

        try:
            while True:
                # Read headers
                content_length = 0
                while True:
                    line = await self._process.stdout.readline()
                    if not line:
                        return  # EOF

                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        break  # Empty line signifies end of headers

                    if line_str.lower().startswith("content-length:"):
                        try:
                            content_length = int(line_str.split(":", 1)[1].strip())
                        except ValueError:
                            logger.error(f"Invalid Content-Length header: {line_str}")

                if content_length == 0:
                    logger.error("No Content-Length provided or 0, breaking to avoid stream desync")
                    break

                # Read body
                body_bytes = await self._process.stdout.readexactly(content_length)
                body_str = body_bytes.decode("utf-8")

                try:
                    payload = json.loads(body_str)
                    self._handle_payload(payload)
                except json.JSONDecodeError:
                    logger.error(f"Failed to decode LSP payload: {body_str}")
                except Exception as e:
                    logger.error(f"Error handling LSP payload: {e}", exc_info=True)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in LSP read loop: {e}", exc_info=True)
        finally:
            for _req_id, future in list(self._pending_requests.items()):
                if not future.done():
                    future.set_exception(RuntimeError("LSP connection closed"))
            self._pending_requests.clear()

    async def _stderr_loop(self) -> None:
        """Background task to read stderr from the LSP server."""
        if not self._process or not self._process.stderr:
            return

        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                logger.warning(f"LSP STDERR: {line.decode('utf-8').strip()}")
        except asyncio.CancelledError:
            pass

    def _handle_payload(self, payload: dict[str, Any]) -> None:
        """Handle an incoming JSON-RPC payload."""
        if "id" in payload and ("result" in payload or "error" in payload):
            # It's a response
            req_id = payload["id"]
            if req_id in self._pending_requests:
                future = self._pending_requests.pop(req_id)
                if not future.done():
                    if "error" in payload:
                        err = payload["error"]
                        future.set_exception(
                            LSPError(
                                code=err.get("code", -32000),
                                message=err.get("message", "Unknown error"),
                                data=err.get("data"),
                            )
                        )
                    else:
                        future.set_result(payload.get("result"))
        elif "method" in payload:
            # It's a server-to-client request or notification
            method = payload["method"]
            req_id = payload.get("id")
            logger.debug(f"Received LSP server method: {method}")

            if method == "textDocument/publishDiagnostics":
                params = payload.get("params", {})
                uri = params.get("uri")
                if uri:
                    self._diagnostics[uri] = params.get("diagnostics", [])
                return

            if req_id is not None:
                # We don't implement client-side methods yet, but we MUST reply
                error_response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method '{method}' not implemented"},
                }

                async def _send_error():
                    try:
                        await self._send(error_response)
                    except Exception as e:
                        logger.error(f"Failed to send method not found error: {e}")

                asyncio.create_task(_send_error())
        else:
            logger.warning(f"Received unhandled LSP payload type: {payload}")

    async def _send(self, payload: dict[str, Any]) -> None:
        """Send a JSON-RPC payload to the LSP server."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("LSP process is not running")

        body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = f"Content-Length: {len(body_bytes)}\r\n\r\n".encode("ascii")

        self._process.stdin.write(headers + body_bytes)
        await self._process.stdin.drain()

    async def send_request(
        self, method: str, params: Any = None, timeout: float | None = 10.0
    ) -> Any:
        """Send a JSON-RPC request and wait for the response."""
        self._request_id += 1
        req_id = self._request_id

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        future: asyncio.Future[Any] = asyncio.Future()
        self._pending_requests[req_id] = future
        try:
            await self._send(payload)
            if timeout is not None:
                return await asyncio.wait_for(future, timeout=timeout)
            return await future
        except TimeoutError as err:
            raise TimeoutError(f"LSP Request {method} timed out after {timeout}s") from err
        finally:
            self._pending_requests.pop(req_id, None)

    async def send_notification(self, method: str, params: Any = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        await self._send(payload)

    async def initialize(self, root_uri: str) -> Any:
        """Perform the LSP initialize handshake."""
        params = {
            "processId": None,
            "rootUri": root_uri,
            "capabilities": {
                "workspace": {
                    "workspaceEdit": {"documentChanges": True},
                    "symbol": {"dynamicRegistration": False},
                },
                "textDocument": {
                    "synchronization": {
                        "dynamicRegistration": False,
                        "willSave": False,
                        "willSaveWaitUntil": False,
                        "didSave": True,
                    },
                    "hover": {
                        "dynamicRegistration": False,
                        "contentFormat": ["markdown", "plaintext"],
                    },
                    "definition": {"dynamicRegistration": False},
                    "references": {"dynamicRegistration": False},
                    "documentSymbol": {"dynamicRegistration": False},
                },
            },
        }

        result = await self.send_request("initialize", params, timeout=15.0)
        await self.send_notification("initialized", {})
        return result

    async def sync_file(self, uri: str, language_id: str, text: str) -> None:
        """Synchronize the file content with the language server via didOpen/didChange."""
        if uri not in self._document_versions:
            self._document_versions[uri] = 1
            await self.send_notification(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": language_id,
                        "version": 1,
                        "text": text,
                    }
                },
            )
        else:
            self._document_versions[uri] += 1
            await self.send_notification(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": uri, "version": self._document_versions[uri]},
                    "contentChanges": [{"text": text}],
                },
            )

    def get_diagnostics(self, uri: str) -> list[Any]:
        """Return the most recently received diagnostics for a URI."""
        return self._diagnostics.get(uri, [])
