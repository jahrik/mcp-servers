from __future__ import annotations

import functools
import inspect
import json
import os
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

_CACHE: dict[str, tuple[float, Any]] = {}


def _ttl_cache(func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(args: Any) -> Any:
        if getattr(args, "no_cache", False):
            return func(args)
        dump_args = {}
        if hasattr(args, "model_dump"):
            dump_args = args.model_dump(exclude={"no_cache"} if hasattr(args, "no_cache") else None)
        key = f"{getattr(func, '__name__', str(func))}:{json.dumps(dump_args, sort_keys=True)}"
        now = time.time()

        expired = [k for k, (ts, _) in _CACHE.items() if now - ts >= 300]
        for k in expired:
            del _CACHE[k]

        if key in _CACHE:
            timestamp, value = _CACHE[key]
            if now - timestamp < 300:
                return value
        result = func(args)
        _CACHE[key] = (now, result)
        return result

    return wrapper


def _audit_log[F: Callable[..., Any]](func: F) -> F:
    """Decorator to audit log write tools to a SQLite DB."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if os.environ.get("MCP_GITHUB_ALLOW_WRITE") != "1":
            raise RuntimeError(
                "Write operations are disabled. Set MCP_GITHUB_ALLOW_WRITE=1 to enable."
            )

        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()

        dumped_args = {}
        for k, v in bound.arguments.items():
            if hasattr(v, "model_dump"):
                dumped_args[k] = v.model_dump()
            else:
                dumped_args[k] = v
        args_json = json.dumps(dumped_args, default=str)

        start_time = datetime.now(UTC)
        success = True
        stderr = None

        try:
            return func(*args, **kwargs)
        except Exception as e:
            success = False

            stderr = getattr(e, "stderr", str(e))
            raise
        finally:
            end_time = datetime.now(UTC)
            duration_ms = (end_time - start_time).total_seconds() * 1000

            try:
                mcp_dir = os.path.expanduser("~/.mcp")
                os.makedirs(mcp_dir, exist_ok=True)
                db_path = os.path.join(mcp_dir, "audit.db")

                conn = sqlite3.connect(db_path)
                try:
                    with conn:
                        conn.execute(
                            """CREATE TABLE IF NOT EXISTS audit_log (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                timestamp TEXT,
                                tool_name TEXT,
                                arguments TEXT,
                                duration_ms REAL,
                                success BOOLEAN,
                                stderr TEXT
                            )"""
                        )
                        # Migrations for existing DBs
                        import contextlib

                        for col, col_type in [
                            ("duration_ms", "REAL"),
                            ("success", "BOOLEAN"),
                            ("stderr", "TEXT"),
                        ]:
                            with contextlib.suppress(sqlite3.OperationalError):
                                conn.execute(f"ALTER TABLE audit_log ADD COLUMN {col} {col_type}")

                        ts = start_time.isoformat()
                        conn.execute(
                            "INSERT INTO audit_log (timestamp, tool_name, arguments, "
                            "duration_ms, success, stderr) VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                ts,
                                getattr(func, "__name__", str(func)),
                                args_json,
                                duration_ms,
                                success,
                                stderr,
                            ),
                        )
                finally:
                    conn.close()
            except Exception:
                pass

    return cast(F, wrapper)
