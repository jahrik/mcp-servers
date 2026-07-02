import os
import time

import pytest

from mcp_servers.github.utils import _audit_log, _ttl_cache


@pytest.mark.asyncio
async def test_ttl_cache_expiry(monkeypatch):
    calls = 0

    @_ttl_cache
    async def dummy(args):
        nonlocal calls
        calls += 1
        return "val"

    class Args:
        pass

    a = Args()

    await dummy(a)
    assert calls == 1

    await dummy(a)
    assert calls == 1

    curr_time = time.time()
    monkeypatch.setattr(time, "time", lambda: curr_time + 400)

    await dummy(a)
    assert calls == 2


@pytest.mark.asyncio
async def test_ttl_cache_no_cache():
    calls = 0

    @_ttl_cache
    async def dummy(args):
        nonlocal calls
        calls += 1
        return "val"

    class Args:
        no_cache = True

    a = Args()
    await dummy(a)
    await dummy(a)
    assert calls == 2


@pytest.mark.asyncio
async def test_audit_log_error(monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")

    @_audit_log
    async def dummy():
        raise ValueError("test error")

    with pytest.raises(ValueError):
        await dummy()

    @_audit_log
    async def dummy2():
        return True

    def bad_makedirs(*args, **kwargs):
        raise OSError("fail")

    monkeypatch.setattr(os, "makedirs", bad_makedirs)
    await dummy2()
