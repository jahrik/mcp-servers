from __future__ import annotations

from mcp_servers.lsp import utils
from mcp_servers.lsp.models.schemas import (
    TsExtractArgs,
    TsOutlineArgs,
    TsQueryArgs,
    TsScopeArgs,
)
from mcp_servers.lsp.treesitter import (
    InvalidNodeTypeError,
    extract_nodes,
    get_outline,
    get_scope_at_position,
    parse_file,
    run_query,
)


async def ts_query(args: TsQueryArgs) -> str:
    """Run a tree-sitter structural query pattern against a file.

    Use this to find code patterns by syntax structure (e.g. all functions with
    a specific decorator, all try blocks, all assignments to a variable).
    Works instantly without an LSP server. Supports Python, Go, Rust, TypeScript, JavaScript.
    """
    filepath_obj = utils._prepare_file(args.filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        tree, lang = parse_file(filepath_obj, args.language)
    except ValueError as e:
        return f"Error: {e}"

    try:
        results = run_query(tree, lang, args.query)
    except Exception as e:
        return f"Error in query: {e}"

    if not results:
        return "No matches found."

    lines: list[str] = []
    for r in results:
        text_preview = r["text"]
        if len(text_preview) > 100:
            text_preview = text_preview[:100] + "..."
        lines.append(
            f"@{r['capture']} [{r['type']}] {filepath_obj}:{r['start_line']}:{r['start_char']}  {text_preview}"
        )

    return utils._cap_and_spill(
        results, results, lines, hint="refine the query pattern or query the full spill file"
    )


async def ts_outline(args: TsOutlineArgs) -> str:
    """Get a fast symbol outline of a file using tree-sitter (no LSP server needed).

    Returns classes and functions with their line positions. Works for languages
    without a configured LSP and has zero startup delay.
    """
    filepath_obj = utils._prepare_file(args.filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        tree, lang = parse_file(filepath_obj, args.language)
    except ValueError as e:
        return f"Error: {e}"

    try:
        symbols = get_outline(tree, lang)
    except ValueError as e:
        return f"Error: {e}"

    if not symbols:
        return "No symbols found."

    lines: list[str] = []
    for sym in symbols:
        indent = "  " if sym["start_char"] > 0 else ""
        lines.append(
            f"{indent}{sym['kind']} {sym['name']}  {filepath_obj}:{sym['start_line']}-{sym['end_line']}"
        )
    return utils._cap_and_spill(
        symbols, symbols, lines, hint="file has many symbols; query the full spill file for all"
    )


async def ts_extract(args: TsExtractArgs) -> str:
    """Extract the full source text of a named node (function, class) by structural identity.

    Use when you need the complete source of a specific function or class without
    knowing exact line numbers.
    """
    filepath_obj = utils._prepare_file(args.filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        tree, lang = parse_file(filepath_obj, args.language)
    except ValueError as e:
        return f"Error: {e}"

    source = filepath_obj.read_bytes()
    try:
        results = extract_nodes(tree, lang, source, args.node_type, args.name)
    except InvalidNodeTypeError as e:
        return f"Error: {e}"
    if not results:
        return f"No {args.node_type} named '{args.name}' found."

    blocks = [f"# {filepath_obj}:{r['start_line']}-{r['end_line']}\n{r['text']}" for r in results]
    if len(blocks) == 1:
        return blocks[0]

    lines_list = ", ".join(str(r["start_line"]) for r in results)
    note = (
        f"# {len(blocks)} {args.node_type} nodes named '{args.name}' found "
        f"(at lines {lines_list}); showing all:"
    )
    return note + "\n" + "\n\n".join(blocks)


async def ts_scope_at_position(args: TsScopeArgs) -> str:
    """Identify the enclosing scopes (function, class, module) at a given position.

    Useful for understanding what context a specific line is in.
    """
    filepath_obj = utils._prepare_file(args.filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        tree, lang = parse_file(filepath_obj, args.language)
    except ValueError as e:
        return f"Error: {e}"

    try:
        scopes = get_scope_at_position(tree, lang, args.line - 1, args.char)
    except ValueError as e:
        return f"Error: {e}"

    if not scopes:
        return "No enclosing scope found."

    lines: list[str] = []
    for i, scope in enumerate(scopes):
        indent = "  " * i
        name_part = f" {scope['name']}" if scope["name"] else ""
        lines.append(
            f"{indent}{scope['type']}{name_part}  (lines {scope['start_line']}-{scope['end_line']})"
        )
    return "\n".join(lines)
