import mcp_servers.data.server


def test_server_main(monkeypatch):
    called = False

    def mock_run():
        nonlocal called
        called = True

    monkeypatch.setattr(mcp_servers.data.server.mcp, "run", mock_run)
    mcp_servers.data.server.main()
    assert called
