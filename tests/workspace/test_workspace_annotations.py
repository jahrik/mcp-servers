from __future__ import annotations

from mcp_servers.workspace.server import mcp


def test_tool_annotations():
    tools = mcp._tool_manager.list_tools()
    tools_by_name = {t.name: t for t in tools}

    expected = {"ws_status": {"readOnlyHint": True}}

    for t_name, attrs in expected.items():
        assert t_name in tools_by_name, f"Tool {t_name} not found"
        t = tools_by_name[t_name]

        for attr, expected_val in attrs.items():
            if expected_val is None:
                if t.annotations is None:
                    continue
                assert getattr(t.annotations, attr) is None or getattr(t.annotations, attr) is False
            else:
                assert t.annotations is not None, f"Tool {t_name} missing annotations"
                assert getattr(t.annotations, attr) == expected_val, (
                    f"Tool {t_name} annotation {attr} != {expected_val}"
                )
