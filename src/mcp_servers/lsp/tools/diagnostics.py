from __future__ import annotations

import asyncio

from mcp.server.fastmcp import Context

from mcp_servers.lsp import utils


async def lsp_diagnostics(filepath: str, ctx: Context) -> str:
    """Get live syntax and type-checking diagnostics for a file (IDE problems panel).

    Prefer over running a linter/type-checker in the shell to check a single
    file: returns the language server's errors and warnings with positions,
    already in sync with your latest edits.

    Args:
        filepath: Absolute or workspace-relative path to the file.
    """
    filepath_obj = utils._prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        uri, language_id = await utils._sync_file_with_lsp(filepath_obj)
        # We need to give the LSP a moment to process and publish diagnostics.
        # Poll briefly, up to 0.5s.
        diagnostics = None
        for _ in range(5):
            diagnostics = utils.lsp_client.get_diagnostics(uri, language_id)
            if diagnostics is not None:
                break
            await asyncio.sleep(0.1)

        if diagnostics is None:
            diagnostics = utils.lsp_client.get_diagnostics(uri, language_id, force=True)

        if diagnostics is None:
            return "No diagnostics found for this file (the LSP hasn't finished analyzing it yet)."
        if not diagnostics:
            return "No diagnostics found for this file (it is error-free)."

        import json

        return json.dumps(diagnostics, indent=2)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP diagnostics: {e}"
