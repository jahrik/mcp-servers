import mcp_servers.duckdb.server


def test_server_main(monkeypatch):
    called = False

    def mock_run():
        nonlocal called
        called = True

    monkeypatch.setattr(mcp_servers.duckdb.server.mcp, "run", mock_run)
    mcp_servers.duckdb.server.main()
    assert called
