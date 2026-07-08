from __future__ import annotations

import asyncio

from mcp.server.fastmcp import Context

from mcp_servers.lsp import utils
from mcp_servers.lsp.models.schemas import (
    DocumentSymbolsArgs,
    PositionArgs,
    WorkspaceSymbolsArgs,
)


async def lsp_document_symbols(args: DocumentSymbolsArgs, ctx: Context) -> str:
    """Outline all symbols (classes, functions, methods, ...) in a file (IDE document outline).

    Prefer over grepping for `def`/`class` to map a file's structure: returns
    each symbol's kind, position, and nesting.
    """
    filepath_obj = utils._prepare_file(args.filepath)
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

        # Filter response
        filtered_response = (
            utils._filter_symbols(response, args.kinds, args.top_level)
            if (args.kinds is not None or args.top_level)
            else response
        )
        if not filtered_response:
            return "No matching symbols found in this document."

        if args.detail == "full":
            import json

            return json.dumps(filtered_response, indent=2)

        formatted_lines = utils._format_symbols(filtered_response)
        return utils._cap_and_spill(response, filtered_response, formatted_lines)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_workspace_symbols(args: WorkspaceSymbolsArgs, ctx: Context) -> str:
    """Find where a symbol is defined anywhere in the project (IDE symbol search / go-to-symbol).

    Prefer over grep to locate a class/function by name: it matches
    declarations across the whole workspace and returns their source
    locations, without the noise of textual matches in comments or strings.
    """
    try:
        params = {"query": args.query}
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
            # Most language servers without workspace indexing (e.g. Microsoft
            # pyright) return nothing for workspace/symbol. Fall back to a
            # tree-sitter scan so the tool still finds top-level declarations.
            fallback = await asyncio.to_thread(utils._treesitter_workspace_symbols, args.query)
            if not fallback:
                return f"No workspace symbols found matching query '{args.query}'."
            results = [{"tree-sitter": fallback}]

        # Filter results
        filtered_results = []
        merged_results_for_spill = []
        merged_filtered_symbols = []
        lines: list[str] = []

        for group in results:
            for lang, symbols in group.items():
                merged_results_for_spill.extend(symbols)
                filtered = (
                    utils._filter_symbols(symbols, args.kinds, args.top_level)
                    if (args.kinds is not None or args.top_level)
                    else symbols
                )
                if filtered:
                    filtered_results.append({lang: filtered})
                    merged_filtered_symbols.extend(filtered)
                    lang_lines = utils._format_symbols(filtered)
                    if lang_lines:
                        lines.append(f"# {lang}")
                        lines.extend(lang_lines)

        if not filtered_results:
            return (
                f"No workspace symbols found matching query "
                f"'{args.query}' with the specified filters."
            )

        if args.detail == "full":
            import json

            return json.dumps(filtered_results, indent=2)

        return utils._cap_and_spill(merged_results_for_spill, merged_filtered_symbols, lines)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


async def lsp_document_highlight(args: PositionArgs, ctx: Context) -> str:
    """Highlight all occurrences of a symbol within one file (IDE highlight-references).

    Prefer over grep to see every read/write of a local variable or parameter
    inside a function: scoped to the file and matched semantically, so it
    won't catch same-named symbols from other scopes.
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
