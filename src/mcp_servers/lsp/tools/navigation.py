from __future__ import annotations

import asyncio

from mcp.server.fastmcp import Context

from mcp_servers.lsp import utils


async def lsp_hover(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Get the type signature and docstring for a symbol (IDE hover).

    Prefer over reading the whole file when you just need a symbol's inferred
    type and documentation at a position.

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
    """Jump to where a symbol is defined (IDE go-to-definition).

    Prefer this over grep/rg when you want the *definition* of a symbol: it
    resolves imports, aliases, and scope, returning the true source location
    rather than every textual match.

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
            formatted_lines = [utils._format_location(loc) for loc in response]
            return utils._cap_and_spill(response, formatted_lines)

        return str(response)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_type_definition(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Jump to the definition of a symbol's type (IDE go-to-type-definition).

    Prefer over grep when you have a variable/expression and need its declared
    type's source — critical for Go interfaces and Python duck typing.

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
            formatted_lines = [utils._format_location(loc) for loc in response]
            return utils._cap_and_spill(response, formatted_lines)

        return str(response)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_implementation(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Find concrete implementations of an interface/abstract symbol (IDE go-to-implementation).

    Prefer over grep for "what implements this": it understands the type
    system, so it finds implementers even when they never name the interface
    textually (e.g. Go structural interfaces).

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
            formatted_lines = [utils._format_location(loc) for loc in response]
            return utils._cap_and_spill(response, formatted_lines)

        return str(response)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_references(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Find every use of a symbol across the project (IDE find-references).

    Prefer this over grep/rg for "where is this used": it matches the symbol
    semantically (not by name), so it excludes unrelated identifiers that
    happen to share the same text and includes uses reached through imports.

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
            formatted_lines = [utils._format_location(loc) for loc in response]
            return utils._cap_and_spill(response, formatted_lines)

        return str(response)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_call_hierarchy(
    filepath: str, line: int, char: int, direction: str, ctx: Context, *, detail: str = "compact"
) -> str:
    """Trace who calls a function, or what it calls (IDE call hierarchy).

    Prefer over grep for understanding execution flow: `incoming` returns the
    callers of the symbol, `outgoing` returns the functions it calls, each
    resolved semantically with exact call-site ranges.

    Args:
        filepath: Absolute or workspace-relative path to the file.
        line: 1-indexed line number.
        char: 0-indexed character position.
        direction: "incoming" or "outgoing"
        detail: "compact" (default) for one `Kind name  path:line` line per
            call; "full" for the raw LSP JSON.
    """
    if direction not in ("incoming", "outgoing"):
        return "Error: direction must be 'incoming' or 'outgoing'"

    if detail not in ("compact", "full"):
        return "Error: detail must be 'compact' or 'full'"

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

        if detail == "full":
            import json

            return json.dumps(all_calls, indent=2)

        # Each call is {from|to: CallHierarchyItem, fromRanges: [...]}; unwrap
        # to the item and format compactly.
        key = "from" if direction == "incoming" else "to"
        items = [call[key] for call in all_calls if isinstance(call, dict) and key in call]
        formatted_lines = utils._format_symbols(items)
        return utils._cap_and_spill(all_calls, formatted_lines)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"
