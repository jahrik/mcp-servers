import mcp_servers.workspace.server


def test_server_main(monkeypatch):
    called = False

    def mock_run():
        nonlocal called
        called = True

    monkeypatch.setattr(mcp_servers.workspace.server.mcp, "run", mock_run)
    mcp_servers.workspace.server.main()
    assert called
