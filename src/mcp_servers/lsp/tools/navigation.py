from __future__ import annotations

import asyncio

from mcp.server.fastmcp import Context

from mcp_servers.lsp import utils
from mcp_servers.lsp.models.schemas import CallHierarchyArgs, PositionArgs


async def lsp_hover(args: PositionArgs, ctx: Context) -> str:
    """Get the type signature and docstring for a symbol (IDE hover).

    Prefer over reading the whole file when you just need a symbol's inferred
    type and documentation at a position.
    """
    filepath_obj = utils._prepare_file(args.filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        uri, language_id = await utils._sync_file_with_lsp(filepath_obj)

        # Send hover request (LSP uses 0-indexed lines)
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": args.line - 1, "character": args.char},
        }
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


async def lsp_definition(args: PositionArgs, ctx: Context) -> str:
    """Jump to where a symbol is defined (IDE go-to-definition).

    Prefer this over grep/rg when you want the *definition* of a symbol: it
    resolves imports, aliases, and scope, returning the true source location
    rather than every textual match.
    """
    filepath_obj = utils._prepare_file(args.filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        uri, language_id = await utils._sync_file_with_lsp(filepath_obj)
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": args.line - 1, "character": args.char},
        }
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
            return utils._cap_and_spill(response, response, formatted_lines)

        return str(response)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_type_definition(args: PositionArgs, ctx: Context) -> str:
    """Jump to the definition of a symbol's type (IDE go-to-type-definition).

    Prefer over grep when you have a variable/expression and need its declared
    type's source — critical for Go interfaces and Python duck typing.
    """
    filepath_obj = utils._prepare_file(args.filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        uri, language_id = await utils._sync_file_with_lsp(filepath_obj)
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": args.line - 1, "character": args.char},
        }
        response = await utils.lsp_client.send_request(
            language_id, "textDocument/typeDefinition", params
        )
        if not response:
            return "No type definition found at this position."

        if isinstance(response, dict):
            return utils._format_location(response)
        elif isinstance(response, list):
            formatted_lines = [utils._format_location(loc) for loc in response]
            return utils._cap_and_spill(response, response, formatted_lines)

        return str(response)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_implementation(args: PositionArgs, ctx: Context) -> str:
    """Find concrete implementations of an interface/abstract symbol (IDE go-to-implementation).

    Prefer over grep for "what implements this": it understands the type
    system, so it finds implementers even when they never name the interface
    textually (e.g. Go structural interfaces).
    """
    filepath_obj = utils._prepare_file(args.filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        uri, language_id = await utils._sync_file_with_lsp(filepath_obj)
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": args.line - 1, "character": args.char},
        }
        response = await utils.lsp_client.send_request(
            language_id, "textDocument/implementation", params
        )
        if not response:
            return "No implementation found at this position."

        if isinstance(response, dict):
            return utils._format_location(response)
        elif isinstance(response, list):
            formatted_lines = [utils._format_location(loc) for loc in response]
            return utils._cap_and_spill(response, response, formatted_lines)

        return str(response)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_references(args: PositionArgs, ctx: Context) -> str:
    """Find every use of a symbol across the project (IDE find-references).

    Prefer this over grep/rg for "where is this used": it matches the symbol
    semantically (not by name), so it excludes unrelated identifiers that
    happen to share the same text and includes uses reached through imports.
    """
    filepath_obj = utils._prepare_file(args.filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        uri, language_id = await utils._sync_file_with_lsp(filepath_obj)
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": args.line - 1, "character": args.char},
            "context": {"includeDeclaration": True},
        }
        response = await utils.lsp_client.send_request(
            language_id, "textDocument/references", params
        )
        if not response:
            return "No references found at this position."

        if isinstance(response, list):
            formatted_lines = [utils._format_location(loc) for loc in response]
            return utils._cap_and_spill(response, response, formatted_lines)

        return str(response)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_call_hierarchy(args: CallHierarchyArgs, ctx: Context) -> str:
    """Trace who calls a function, or what it calls (IDE call hierarchy).

    Prefer over grep for understanding execution flow: `incoming` returns the
    callers of the symbol, `outgoing` returns the functions it calls, each
    resolved semantically with exact call-site ranges.
    """
    filepath_obj = utils._prepare_file(args.filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        uri, language_id = await utils._sync_file_with_lsp(filepath_obj)
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": args.line - 1, "character": args.char},
        }
        # 1. Prepare call hierarchy
        items = await utils.lsp_client.send_request(
            language_id, "textDocument/prepareCallHierarchy", params
        )
        if not items:
            return "No call hierarchy items found at this position."

        # 2. Get incoming or outgoing calls for all items
        method = (
            "callHierarchy/incomingCalls"
            if args.direction == "incoming"
            else "callHierarchy/outgoingCalls"
        )

        all_calls = []
        for item in items:
            call_params = {"item": item}
            calls = await utils.lsp_client.send_request(language_id, method, call_params)
            if calls:
                all_calls.extend(calls)

        if not all_calls:
            return f"No {args.direction} calls found."

        if args.detail == "full":
            import json

            return json.dumps(all_calls, indent=2)

        # Each call is {from|to: CallHierarchyItem, fromRanges: [...]}; unwrap
        # to the item and format compactly.
        key = "from" if args.direction == "incoming" else "to"
        items = [call[key] for call in all_calls if isinstance(call, dict) and key in call]
        formatted_lines = utils._format_symbols(items)
        return utils._cap_and_spill(all_calls, all_calls, formatted_lines)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"
