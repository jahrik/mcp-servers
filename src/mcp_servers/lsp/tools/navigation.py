from __future__ import annotations

import asyncio

from mcp.server.fastmcp import Context

from mcp_servers.lsp import utils


async def lsp_hover(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Get the type signature and docstring for the symbol at the given position.

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

        # Send hover request (LSP uses 0-indexed lines)
        params = {"textDocument": {"uri": uri}, "position": {"line": line - 1, "character": char}}
        response = await utils.lsp_client.send_request(language_id, "textDocument/hover", params)
        if not response:
            return "No hover information found at this position."

        contents = response.get("contents", "")
        if isinstance(contents, dict):
            return contents.get("value", str(contents))
        elif isinstance(contents, list):
            return "\n\n".join(
                [c.get("value", str(c)) if isinstance(c, dict) else str(c) for c in contents]
            )
        else:
            return str(contents)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_definition(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Get the definition location for the symbol at the given position.

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
            language_id, "textDocument/definition", params
        )
        if not response:
            return "No definition found at this position."

        # Format response (could be list of locations or single location)
        if isinstance(response, dict):
            return utils._format_location(response)
        elif isinstance(response, list):
            return "\n".join(utils._format_location(loc) for loc in response)

        return str(response)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_type_definition(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Get the type definition location for the symbol at the given position.

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
            language_id, "textDocument/typeDefinition", params
        )
        if not response:
            return "No type definition found at this position."

        if isinstance(response, dict):
            return utils._format_location(response)
        elif isinstance(response, list):
            return "\n".join(utils._format_location(loc) for loc in response)

        return str(response)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_implementation(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Get the implementation location(s) for the symbol at the given position.

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
            language_id, "textDocument/implementation", params
        )
        if not response:
            return "No implementation found at this position."

        if isinstance(response, dict):
            return utils._format_location(response)
        elif isinstance(response, list):
            return "\n".join(utils._format_location(loc) for loc in response)

        return str(response)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_references(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Get all reference locations for the symbol at the given position.

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
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": char},
            "context": {"includeDeclaration": True},
        }
        response = await utils.lsp_client.send_request(
            language_id, "textDocument/references", params
        )
        if not response:
            return "No references found at this position."

        if isinstance(response, list):
            return "\n".join(utils._format_location(loc) for loc in response)

        return str(response)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_call_hierarchy(
    filepath: str, line: int, char: int, direction: str, ctx: Context
) -> str:
    """Get the call hierarchy (incoming or outgoing calls) for the symbol at the given position.

    Args:
        filepath: Absolute or workspace-relative path to the file.
        line: 1-indexed line number.
        char: 0-indexed character position.
        direction: "incoming" or "outgoing"
    """
    if direction not in ("incoming", "outgoing"):
        return "Error: direction must be 'incoming' or 'outgoing'"

    filepath_obj = utils._prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    if line < 1 or char < 0:
        return "Error: line must be >= 1 and char must be >= 0"

    try:
        uri, language_id = await utils._sync_file_with_lsp(filepath_obj)
        params = {"textDocument": {"uri": uri}, "position": {"line": line - 1, "character": char}}
        # 1. Prepare call hierarchy
        items = await utils.lsp_client.send_request(
            language_id, "textDocument/prepareCallHierarchy", params
        )
        if not items:
            return "No call hierarchy items found at this position."

        # 2. Get incoming or outgoing calls for all items
        method = (
            "callHierarchy/incomingCalls"
            if direction == "incoming"
            else "callHierarchy/outgoingCalls"
        )

        all_calls = []
        for item in items:
            call_params = {"item": item}
            calls = await utils.lsp_client.send_request(language_id, method, call_params)
            if calls:
                all_calls.extend(calls)

        if not all_calls:
            return f"No {direction} calls found."

        import json

        return json.dumps(all_calls, indent=2)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"
