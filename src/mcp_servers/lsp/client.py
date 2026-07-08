from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .session import LSPError, LSPSession

logger = logging.getLogger(__name__)

__all__ = ["LSPClient", "LSPSession", "LSPError"]


class LSPClient:
    """A routing client that manages multiple LSPSessions based on language."""

    def __init__(self, root_uri: str = "") -> None:
        self.root_uri = root_uri
        self.sessions: dict[str, list[LSPSession | None]] = {}
        self.language_commands = {
            "python": [
                ["ty", "server"],
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
            self.language_commands["python"] = [shlex.split(env_cmd), ["ruff", "server"]]

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
            del self.sessions[language_id]
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
                    if all(s is None for s in session_list):
                        del self.sessions[lang]
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
        session_commands = [s.command for s in active_sessions]
        tasks = [s.send_request(method, params, timeout) for s in active_sessions]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # If any query task returned a RuntimeError (e.g. broken pipe), retry by command identity
        if any(isinstance(r, RuntimeError) for r in results):
            refreshed_sessions = await self._get_or_create_sessions(language_id)
            cmd_to_session = {tuple(s.command): s for s in refreshed_sessions}
            retry_tasks = []
            for idx, r in enumerate(results):
                if isinstance(r, RuntimeError):
                    refreshed = cmd_to_session.get(tuple(session_commands[idx]))
                    if refreshed:
                        retry_tasks.append(refreshed.send_request(method, params, timeout))
                    else:
                        fut: asyncio.Future[Any] = asyncio.Future()
                        fut.set_exception(r)
                        retry_tasks.append(fut)
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
