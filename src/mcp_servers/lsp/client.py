from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class LSPError(Exception):
    """Exception raised for errors returned by the LSP server."""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"LSP Error {code}: {message}")


class LSPSession:
    """A client for managing the lifecycle and JSON-RPC transport to a language server subprocess."""

    def __init__(self, command: list[str]) -> None:
        self.command = command
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending_requests: dict[int, asyncio.Future[Any]] = {}
        self._read_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._document_versions: dict[str, int] = {}
        self._document_texts: dict[str, str] = {}
        self._sync_kind: int = 1  # 1 = Full, 2 = Incremental
        self._diagnostics: dict[str, list[Any]] = {}
        self.last_used = time.monotonic()
        self._settings: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}

    def update_activity(self):
        self.last_used = time.monotonic()

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
        self.update_activity()

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
        self._document_texts.clear()
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
                logger.info(f"LSP STDERR: {line.decode('utf-8').strip()}")
        except asyncio.CancelledError:
            pass

    def _handle_payload(self, payload: dict[str, Any]) -> None:
        """Handle an incoming JSON-RPC payload."""
        self.update_activity()
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

            if method == "workspace/configuration" and req_id is not None:
                params = payload.get("params", {})
                items = params.get("items", [])
                result = []
                for item in items:
                    section = item.get("section")
                    val = self._get_configuration_for_section(section)
                    result.append(val)

                response = {"jsonrpc": "2.0", "id": req_id, "result": result}
                asyncio.create_task(self._send(response))
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
        self.update_activity()
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
        self.update_activity()
        payload = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        await self._send(payload)

    def _get_configuration_for_section(self, section: str | None) -> Any:
        """Resolve settings for a specific section, supporting flat and nested structures."""
        if not section:
            return self._settings

        # 1. Resolve exact or nested match first
        resolved_val = None
        found = False

        if section in self._settings:
            resolved_val = self._settings[section]
            found = True
        else:
            parts = section.split(".")
            curr = self._settings
            found_nested = True
            for part in parts:
                if isinstance(curr, dict) and part in curr:
                    curr = curr[part]
                else:
                    found_nested = False
                    break
            if found_nested:
                resolved_val = curr
                found = True

        # If it was found and is not a dictionary (e.g. a string/bool), return it immediately
        if found and not isinstance(resolved_val, dict):
            return resolved_val

        # 2. Build flat-to-nested construction for this section
        flat_val = {}
        prefix = section + "."
        for k, v in self._settings.items():
            if k.startswith(prefix):
                sub_key = k[len(prefix) :]
                sub_parts = sub_key.split(".")
                d = flat_val
                for part in sub_parts[:-1]:
                    d = d.setdefault(part, {})
                d[sub_parts[-1]] = v

        # 3. Merge the resolved dictionary and the flat-to-nested dictionary
        if resolved_val is not None or flat_val:
            if isinstance(resolved_val, dict):

                def merge_dicts(d1: dict, d2: dict) -> dict:
                    res = dict(d1)
                    for key, val in d2.items():
                        if key in res and isinstance(res[key], dict) and isinstance(val, dict):
                            res[key] = merge_dicts(res[key], val)
                        else:
                            res[key] = val
                    return res

                return merge_dicts(resolved_val, flat_val)
            return flat_val

        return None

    async def initialize(self, root_uri: str) -> Any:
        """Perform the LSP initialize handshake."""
        # Load local workspace settings
        self._settings = {
            "python.analysis.indexing": True,
        }

        try:
            from pathlib import Path
            from urllib.parse import unquote

            if root_uri.startswith("file://"):
                root_path = Path(unquote(root_uri[7:]))

                # Check for .venv to auto-detect python path
                venv_dir = root_path / ".venv"
                if venv_dir.is_dir():
                    import sys

                    python_bin = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
                    python_path = venv_dir / python_bin
                    if python_path.is_file():
                        self._settings["python.pythonPath"] = str(python_path)
                    self._settings["python.venvPath"] = str(root_path)
                    self._settings["python.venv"] = ".venv"

                # Load pyproject.toml
                pyproject = root_path / "pyproject.toml"
                if pyproject.is_file():
                    try:
                        import tomllib

                        with open(pyproject, "rb") as f:
                            toml_data = tomllib.load(f)
                        tool = toml_data.get("tool", {})
                        pyright_settings = tool.get("pyright", {})
                        if isinstance(pyright_settings, dict):
                            self._settings["pyright"] = pyright_settings
                    except Exception as e:
                        logger.warning(f"Failed to load pyproject.toml settings: {e}")

                # Load vscode settings
                vscode_settings = root_path / ".vscode" / "settings.json"
                if vscode_settings.is_file():
                    try:
                        with open(vscode_settings, encoding="utf-8") as f:
                            content = f.read()
                        import re

                        pattern = re.compile(r'("(?:\\.|[^"\\])*")|//.*')
                        content_clean = pattern.sub(lambda m: m.group(1) or "", content)
                        vscode_data = json.loads(content_clean)
                        if isinstance(vscode_data, dict):
                            self._settings.update(vscode_data)
                    except Exception as e:
                        logger.warning(f"Failed to load VS Code settings: {e}")
        except Exception as e:
            logger.warning(f"Failed to load workspace configuration: {e}")

        params = {
            "processId": None,
            "rootUri": root_uri,
            "capabilities": {
                "workspace": {
                    "workspaceEdit": {"documentChanges": True},
                    "symbol": {"dynamicRegistration": False},
                    "configuration": True,
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
                    "callHierarchy": {"dynamicRegistration": False},
                    "typeDefinition": {"dynamicRegistration": False},
                    "implementation": {"dynamicRegistration": False},
                    "documentHighlight": {"dynamicRegistration": False},
                },
            },
        }

        result = await self.send_request("initialize", params, timeout=15.0)

        # Parse sync kind
        if result and "capabilities" in result:
            self.capabilities = result["capabilities"]
            sync = result["capabilities"].get("textDocumentSync")
            if isinstance(sync, dict):
                self._sync_kind = sync.get("change", 1)
            elif isinstance(sync, int):
                self._sync_kind = sync

        await self.send_notification("initialized", {})
        return result

    async def sync_file(self, uri: str, language_id: str, text: str) -> None:
        """Synchronize the file content with the language server via didOpen/didChange."""
        self.update_activity()
        if uri not in self._document_versions:
            self._document_versions[uri] = 1
            self._document_texts[uri] = text
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
            old_text = self._document_texts.get(uri, "")
            if old_text == text:
                return

            self._document_versions[uri] += 1
            self._document_texts[uri] = text

            content_changes = []
            if self._sync_kind == 2:
                import difflib

                old_lines = old_text.splitlines(keepends=True)
                new_lines = text.splitlines(keepends=True)
                sm = difflib.SequenceMatcher(None, old_lines, new_lines)

                for tag, i1, i2, j1, j2 in sm.get_opcodes():
                    if tag == "equal":
                        continue

                    start_pos = {"line": i1, "character": 0}
                    if i2 < len(old_lines):
                        end_pos = {"line": i2, "character": 0}
                    else:
                        if old_lines:
                            end_pos = {
                                "line": i2 - 1,
                                "character": len(old_lines[-1].rstrip("\r\n")),
                            }
                        else:
                            end_pos = {"line": 0, "character": 0}

                    content_changes.append(
                        {
                            "range": {"start": start_pos, "end": end_pos},
                            "text": "".join(new_lines[j1:j2]),
                        }
                    )
                # Reverse to avoid line number shifting during sequential application
                content_changes.reverse()
            else:
                content_changes = [{"text": text}]

            await self.send_notification(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": uri, "version": self._document_versions[uri]},
                    "contentChanges": content_changes,
                },
            )

    def get_diagnostics(self, uri: str) -> list[Any] | None:
        """Return the most recently received diagnostics for a URI, or None if not yet received."""
        return self._diagnostics.get(uri)

    def is_alive(self) -> bool:
        return self._process is not None and self._process.returncode is None


class LSPClient:
    """A routing client that manages multiple LSPSessions based on language."""

    def __init__(self, root_uri: str = "") -> None:
        self.root_uri = root_uri
        self.sessions: dict[str, list[LSPSession | None]] = {}
        self.language_commands = {
            "python": [
                ["pyright-langserver", "--stdio"],
                ["ruff", "server"],
            ],
            "go": [["gopls"]],
            "rust": [["rust-analyzer"]],
            "typescript": [["typescript-language-server", "--stdio"]],
            "javascript": [["typescript-language-server", "--stdio"]],
        }

        import os
        import shlex

        env_cmd = os.environ.get("MCP_LSP_COMMAND")
        if env_cmd:
            self.language_commands["python"] = [shlex.split(env_cmd)]

        self.idle_timeout_secs = 600.0  # 10 minutes
        self._reap_task: asyncio.Task[None] | None = None
        self._watch_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the reaping task and watcher task."""
        if not self._reap_task:
            self._reap_task = asyncio.create_task(self._reap_loop())
        if not self._watch_task:
            self._watch_task = asyncio.create_task(self._watch_loop())

    async def stop(self) -> None:
        """Stop all sessions and the reap task."""
        import contextlib

        if self._reap_task:
            self._reap_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reap_task
            self._reap_task = None
        if self._watch_task:
            self._watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watch_task
            self._watch_task = None

        for session_list in list(self.sessions.values()):
            for session in session_list:
                if session is not None:
                    await session.stop()
        self.sessions.clear()

    async def initialize(self, root_uri: str) -> Any:
        """Store the root URI to initialize spawned sessions."""
        self.root_uri = root_uri
        return {"capabilities": {}}

    async def _get_or_create_sessions(self, language_id: str) -> list[LSPSession]:
        if language_id not in self.language_commands:
            raise ValueError(f"Unsupported language: {language_id}")

        cmds = self.language_commands[language_id]
        if language_id not in self.sessions:
            self.sessions[language_id] = [None] * len(cmds)

        session_list = self.sessions[language_id]
        active_sessions = []

        for idx, cmd in enumerate(cmds):
            session = session_list[idx]
            if session is not None and not session.is_alive():
                logger.warning(
                    f"LSP session for {language_id} (command: {' '.join(cmd)}) crashed. Restarting..."
                )
                await session.stop()
                session = None
                session_list[idx] = None

            if session is None:
                try:
                    session = LSPSession(cmd)
                    await session.start()
                    if self.root_uri:
                        await session.initialize(self.root_uri)
                    session_list[idx] = session
                except Exception as e:
                    logger.error(
                        f"Failed to spawn/initialize LSP session for {language_id} (command: {' '.join(cmd)}): {e}"
                    )
                    if session is not None:
                        await session.stop()
                    session = None
                    session_list[idx] = None

            if session is not None:
                active_sessions.append(session)

        if not active_sessions:
            raise RuntimeError(f"All configured LSP servers failed to start for {language_id}")

        return active_sessions

    async def _reap_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(60)
                now = time.monotonic()
                for lang, session_list in list(self.sessions.items()):
                    for idx, session in enumerate(session_list):
                        if session is not None and now - session.last_used > self.idle_timeout_secs:
                            logger.info(
                                f"Reaping idle LSP session for {lang} (command: {' '.join(session.command)})"
                            )
                            await session.stop()
                            session_list[idx] = None
        except asyncio.CancelledError:
            pass

    async def _watch_loop(self) -> None:
        """Background task to poll for workspace file changes and send didChangeWatchedFiles."""
        import os
        from pathlib import Path
        from urllib.parse import unquote

        if not self.root_uri.startswith("file://"):
            return

        root_path = Path(unquote(self.root_uri[7:]))
        if not root_path.exists():
            return

        extensions = {".py", ".go", ".rs", ".ts", ".tsx", ".js", ".jsx"}
        last_mtimes: dict[str, float] = {}
        is_first_pass = True

        try:
            while True:
                await asyncio.sleep(5)
                if not self.sessions:
                    continue

                changes = []
                current_pass_uris = set()
                for root, _, files in os.walk(root_path):
                    if (
                        ".git" in root
                        or "__pycache__" in root
                        or "node_modules" in root
                        or ".venv" in root
                    ):
                        continue

                    for f in files:
                        if any(f.endswith(ext) for ext in extensions):
                            path = Path(root) / f
                            try:
                                mtime = path.stat().st_mtime_ns
                                uri = path.as_uri()
                                current_pass_uris.add(uri)
                                old_mtime = last_mtimes.get(uri)
                                if old_mtime is None:
                                    last_mtimes[uri] = mtime
                                    if not is_first_pass:
                                        changes.append({"uri": uri, "type": 1})  # 1 = Created
                                elif mtime > old_mtime:
                                    last_mtimes[uri] = mtime
                                    changes.append({"uri": uri, "type": 2})  # 2 = Changed
                            except Exception:
                                pass

                if not is_first_pass:
                    for uri in list(last_mtimes.keys()):
                        if uri not in current_pass_uris:
                            del last_mtimes[uri]
                            changes.append({"uri": uri, "type": 3})  # 3 = Deleted

                is_first_pass = False

                if changes:
                    for lang, session_list in list(self.sessions.items()):
                        for session in session_list:
                            if session is not None:
                                try:
                                    await session.send_notification(
                                        "workspace/didChangeWatchedFiles", {"changes": changes}
                                    )
                                except Exception as e:
                                    logger.error(
                                        f"Failed to send didChangeWatchedFiles to {lang} (command: {' '.join(session.command)}): {e}"
                                    )
        except asyncio.CancelledError:
            pass

    async def sync_file(self, uri: str, language_id: str, text: str) -> None:
        """Synchronize file with all active language servers, with retry logic."""
        sessions = await self._get_or_create_sessions(language_id)
        for session in sessions:
            try:
                await session.sync_file(uri, language_id, text)
            except RuntimeError:
                # Maybe broken pipe, recreate and retry once
                sessions_retry = await self._get_or_create_sessions(language_id)
                for s in sessions_retry:
                    if s.command == session.command:
                        await s.sync_file(uri, language_id, text)
                        break

    async def send_request(
        self, language_id: str, method: str, params: Any = None, timeout: float | None = 10.0
    ) -> Any:
        active_sessions = await self._get_or_create_sessions(language_id)
        if not active_sessions:
            raise RuntimeError(f"No active LSP sessions running for {language_id}")

        MUTATION_CAPABILITIES = {
            "textDocument/rename": "renameProvider",
            "textDocument/codeAction": "codeActionProvider",
            "textDocument/formatting": "documentFormattingProvider",
            "workspace/executeCommand": "executeCommandProvider",
        }

        # 1. Routing for mutations
        if method in MUTATION_CAPABILITIES:
            capability = MUTATION_CAPABILITIES[method]
            target_session = None

            if method == "workspace/executeCommand":
                cmd_name = params.get("command") if isinstance(params, dict) else None
                if cmd_name:
                    for s in active_sessions:
                        provider = s.capabilities.get("executeCommandProvider")
                        if isinstance(provider, dict) and cmd_name in provider.get("commands", []):
                            target_session = s
                            break

            if target_session is None:
                for s in active_sessions:
                    if s.capabilities.get(capability):
                        target_session = s
                        break

            if target_session is None:
                logger.warning(
                    f"No session for {language_id} declared capability {capability}. Routing to first active session."
                )
                target_session = active_sessions[0]

            try:
                return await target_session.send_request(method, params, timeout)
            except RuntimeError:
                # Retry once by recreating sessions
                active_sessions = await self._get_or_create_sessions(language_id)
                target_session = None
                if method == "workspace/executeCommand":
                    cmd_name = params.get("command") if isinstance(params, dict) else None
                    if cmd_name:
                        for s in active_sessions:
                            provider = s.capabilities.get("executeCommandProvider")
                            if isinstance(provider, dict) and cmd_name in provider.get(
                                "commands", []
                            ):
                                target_session = s
                                break
                if target_session is None:
                    for s in active_sessions:
                        if s.capabilities.get(capability):
                            target_session = s
                            break
                if target_session is None:
                    target_session = active_sessions[0]
                return await target_session.send_request(method, params, timeout)

        # 2. Fan-out for Queries & Navigation
        tasks = [s.send_request(method, params, timeout) for s in active_sessions]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # If any query task returned a RuntimeError (e.g. broken pipe), retry those tasks once
        if any(isinstance(r, RuntimeError) for r in results):
            active_sessions = await self._get_or_create_sessions(language_id)
            retry_tasks = []
            for idx, r in enumerate(results):
                if isinstance(r, RuntimeError) and idx < len(active_sessions):
                    retry_tasks.append(active_sessions[idx].send_request(method, params, timeout))
                else:
                    fut = asyncio.Future()
                    if isinstance(r, Exception):
                        fut.set_exception(r)
                    else:
                        fut.set_result(r)
                    retry_tasks.append(fut)
            results = await asyncio.gather(*retry_tasks, return_exceptions=True)

        valid_responses = []
        exceptions = []
        for r in results:
            if isinstance(r, Exception):
                exceptions.append(r)
            elif r is not None:
                valid_responses.append(r)

        if not valid_responses and exceptions:
            # Propagate the first exception if everything failed
            raise exceptions[0]

        if not valid_responses:
            return None

        # 3. Merge responses
        if method == "textDocument/hover":
            merged_contents = []
            for resp in valid_responses:
                if isinstance(resp, dict):
                    contents = resp.get("contents")
                    if contents:
                        if isinstance(contents, list):
                            merged_contents.extend(contents)
                        else:
                            merged_contents.append(contents)
            if merged_contents:
                return {"contents": merged_contents}
            return None

        elif method in (
            "textDocument/definition",
            "textDocument/typeDefinition",
            "textDocument/implementation",
            "textDocument/references",
            "textDocument/documentHighlight",
            "textDocument/documentSymbol",
            "textDocument/prepareCallHierarchy",
            "callHierarchy/incomingCalls",
            "callHierarchy/outgoingCalls",
            "workspace/symbol",
        ):
            merged_list = []
            for resp in valid_responses:
                if isinstance(resp, list):
                    merged_list.extend(resp)
                elif isinstance(resp, dict):
                    merged_list.append(resp)
            return merged_list

        return valid_responses[0]

    async def send_notification(self, language_id: str, method: str, params: Any = None) -> None:
        sessions = await self._get_or_create_sessions(language_id)
        for session in sessions:
            try:
                await session.send_notification(method, params)
            except RuntimeError:
                sessions_retry = await self._get_or_create_sessions(language_id)
                for s in sessions_retry:
                    if s.command == session.command:
                        await s.send_notification(method, params)
                        break

    def get_diagnostics(self, uri: str, language_id: str, force: bool = False) -> list[Any] | None:
        if language_id not in self.sessions:
            return None

        merged_diagnostics = []
        any_published = False

        for session in self.sessions[language_id]:
            if session is not None:
                diags = session.get_diagnostics(uri)
                if diags is not None:
                    merged_diagnostics.extend(diags)
                    any_published = True
                elif not force:
                    # If any active server hasn't published yet and we aren't forcing, return None
                    return None

        return merged_diagnostics if any_published else None
