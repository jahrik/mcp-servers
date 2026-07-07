from __future__ import annotations

import asyncio

from mcp.server.fastmcp import Context

from mcp_servers.lsp import utils


async def lsp_document_symbols(filepath: str, ctx: Context) -> str:
    """Get all symbols (classes, functions, methods, etc.) defined in the given file.

    Args:
        filepath: Absolute or workspace-relative path to the file.
    """
    filepath_obj = utils._prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        uri, language_id = await utils._sync_file_with_lsp(filepath_obj)
        params = {"textDocument": {"uri": uri}}
        response = await utils.lsp_client.send_request(
            language_id, "textDocument/documentSymbol", params
        )
        if not response:
            return "No symbols found in this document."

        import json

        return json.dumps(response, indent=2)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_workspace_symbols(query: str, ctx: Context) -> str:
    """Search for a symbol across the entire workspace/project.

    Args:
        query: The symbol name or partial name to search for.
    """
    try:
        params = {"query": query}
        results = []
        languages = set(utils.lsp_client.sessions.keys()) | {
            "python",
            "go",
            "rust",
            "typescript",
            "javascript",
        }
        for lang in languages:
            try:
                response = await utils.lsp_client.send_request(lang, "workspace/symbol", params)
                if response:
                    results.append({lang: response})
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        if not results:
            return f"No workspace symbols found matching query '{query}'."

        import json

        return json.dumps(results, indent=2)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_document_highlight(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Get document highlights for the symbol at the given position (e.g. all read/write occurrences).

    Args:
        filepath: Absolute or workspace-relative path to the file.
        line: 1-indexed line number.
        char: 0-indexed character position.
    """
    filepath_obj = utils._prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    if line < 1 or char < 0:
        return "Error: line must be >= 1 and char must be >= 0"

    try:
        uri, language_id = await utils._sync_file_with_lsp(filepath_obj)
        params = {"textDocument": {"uri": uri}, "position": {"line": line - 1, "character": char}}
        response = await utils.lsp_client.send_request(
            language_id, "textDocument/documentHighlight", params
        )
        if not response:
            return "No highlights found at this position."

        import json

        return json.dumps(response, indent=2)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"
