from __future__ import annotations

from mcp_servers.lsp import utils
from mcp_servers.lsp.treesitter import (
    InvalidNodeTypeError,
    extract_node,
    get_outline,
    get_scope_at_position,
    parse_file,
    run_query,
)


async def ts_query(filepath: str, query: str, language: str | None = None) -> str:
    """Run a tree-sitter structural query pattern against a file.

    Use this to find code patterns by syntax structure (e.g. all functions with
    a specific decorator, all try blocks, all assignments to a variable).
    Works instantly without an LSP server. Supports Python, Go, Rust, TypeScript, JavaScript.

    Args:
        filepath: Absolute or workspace-relative path to the file.
        query: Tree-sitter S-expression query pattern (e.g. '(function_definition name: (identifier) @name)').
        language: Language override (auto-detected from extension if omitted).
    """
    filepath_obj = utils._prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        tree, lang = parse_file(filepath_obj, language)
    except ValueError as e:
        return f"Error: {e}"

    try:
        results = run_query(tree, lang, query)
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

    return utils._cap_and_spill(results, results, lines)


async def ts_outline(filepath: str, language: str | None = None) -> str:
    """Get a fast symbol outline of a file using tree-sitter (no LSP server needed).

    Returns classes and functions with their line positions. Works for languages
    without a configured LSP and has zero startup delay.

    Args:
        filepath: Absolute or workspace-relative path to the file.
        language: Language override (auto-detected from extension if omitted).
    """
    filepath_obj = utils._prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        tree, lang = parse_file(filepath_obj, language)
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
    return utils._cap_and_spill(symbols, symbols, lines)


async def ts_extract(filepath: str, node_type: str, name: str, language: str | None = None) -> str:
    """Extract the full source text of a named node (function, class) by structural identity.

    Use when you need the complete source of a specific function or class without
    knowing exact line numbers.

    Args:
        filepath: Absolute or workspace-relative path to the file.
        node_type: Tree-sitter node type (e.g. 'function_definition', 'class_definition').
        name: Name of the symbol to extract.
        language: Language override (auto-detected from extension if omitted).
    """
    filepath_obj = utils._prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        tree, lang = parse_file(filepath_obj, language)
    except ValueError as e:
        return f"Error: {e}"

    source = filepath_obj.read_bytes()
    try:
        result = extract_node(tree, lang, source, node_type, name)
    except InvalidNodeTypeError as e:
        return f"Error: {e}"
    if result is None:
        return f"No {node_type} named '{name}' found."

    header = f"# {filepath_obj}:{result['start_line']}-{result['end_line']}"
    return f"{header}\n{result['text']}"


async def ts_scope_at_position(
    filepath: str, line: int, char: int = 0, language: str | None = None
) -> str:
    """Identify the enclosing scopes (function, class, module) at a given position.

    Useful for understanding what context a specific line is in.

    Args:
        filepath: Absolute or workspace-relative path to the file.
        line: 1-indexed line number.
        char: 0-indexed character position (default 0).
        language: Language override (auto-detected from extension if omitted).
    """
    filepath_obj = utils._prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    if line < 1 or char < 0:
        return "Error: line must be >= 1 and char must be >= 0"

    try:
        tree, lang = parse_file(filepath_obj, language)
    except ValueError as e:
        return f"Error: {e}"

    try:
        scopes = get_scope_at_position(tree, lang, line - 1, char)
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
