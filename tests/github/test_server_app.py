import mcp_servers.github.server


def test_server_main(monkeypatch):
    called = False

    def mock_run():
        nonlocal called
        called = True

    monkeypatch.setattr(mcp_servers.github.server.mcp, "run", mock_run)
    mcp_servers.github.server.main()
    assert called
