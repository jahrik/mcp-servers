from __future__ import annotations

import os
from pathlib import Path

from mcp_servers.lsp.client import LSPClient

WORKSPACE_ROOT = os.environ.get("MCP_LSP_ROOT", os.getcwd())
if WORKSPACE_ROOT.startswith("~"):  # pragma: no cover
    WORKSPACE_ROOT = str(Path(WORKSPACE_ROOT).expanduser())

# Create a global client instance
lsp_client = LSPClient(root_uri=Path(WORKSPACE_ROOT).resolve().as_uri())


def _candidate_roots() -> list[Path]:
    """Roots that a relative filepath may be resolved against.

    Returns the workspace root followed by its immediate child directories that
    look like repositories (contain a ``.git`` entry). This lets a repo-relative
    path such as ``src/foo.py`` resolve correctly even when ``WORKSPACE_ROOT`` is
    a parent directory holding several checked-out repositories.
    """
    root = Path(WORKSPACE_ROOT).resolve()
    roots = [root]
    try:
        children = sorted(root.iterdir())
    except OSError:
        return roots
    for child in children:
        try:
            if child.is_dir() and (child / ".git").exists():
                roots.append(child)
        except OSError:
            continue
    return roots


def _safe_exists(p: Path) -> bool:
    """``Path.exists()`` that treats an unreadable path (OSError) as absent."""
    try:
        return p.exists()
    except OSError:
        return False


def _safe_is_file(p: Path) -> bool:
    """``Path.is_file()`` that treats an unreadable path (OSError) as not-a-file."""
    try:
        return p.is_file()
    except OSError:
        return False


def _prepare_file(filepath: str) -> Path | str:
    """Validate and resolve filepath. Returns Path on success, error string on failure."""
    root_obj = Path(WORKSPACE_ROOT).resolve()
    p = Path(filepath)

    if p.is_absolute():
        filepath_obj = p.resolve()
        try:
            filepath_obj.relative_to(root_obj)
        except ValueError:
            return f"Error: Filepath must be within the workspace root {WORKSPACE_ROOT}"
        if not _safe_exists(filepath_obj):
            return f"Error: File not found: {filepath_obj}"
        if not _safe_is_file(filepath_obj):
            return f"Error: Not a regular file: {filepath_obj}"
        return filepath_obj

    # Relative path: try the workspace root and each child repository. Every
    # candidate is containment-checked, so this never escapes the workspace.
    # Only regular files count as matches — a directory would fail later when
    # opened for syncing, so it must not be returned here.
    matches: list[Path] = []
    for base in _candidate_roots():
        candidate = (base / p).resolve()
        try:
            candidate.relative_to(root_obj)
        except ValueError:
            continue
        if _safe_is_file(candidate) and candidate not in matches:
            matches.append(candidate)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        joined = ", ".join(str(m) for m in matches)
        return (
            f"Error: Ambiguous filepath '{filepath}' matches multiple repositories "
            f"({joined}). Pass an absolute path to disambiguate."
        )
    # No match: report against the workspace root for a stable, clear message.
    return f"Error: File not found: {(root_obj / p)}"


_file_mtimes: dict[str, int] = {}


async def _sync_file_with_lsp(filepath_obj: Path) -> tuple[str, str]:
    """Sync file to LSP and return URI and language ID."""
    uri = filepath_obj.as_uri()
    filepath = str(filepath_obj)
    language_id = "python"
    if filepath.endswith(".go"):
        language_id = "go"
    elif filepath.endswith(".rs"):
        language_id = "rust"
    elif filepath.endswith((".ts", ".tsx")):
        language_id = "typescript"
    elif filepath.endswith((".js", ".jsx")):
        language_id = "javascript"

    try:
        mtime = filepath_obj.stat().st_mtime_ns
    except FileNotFoundError:
        mtime = 0
    if uri not in _file_mtimes or _file_mtimes[uri] != mtime:
        with open(filepath_obj, encoding="utf-8") as f:
            content = f.read()
        await lsp_client.sync_file(uri, language_id, content)
        _file_mtimes[uri] = mtime
    return uri, language_id


def _format_location(loc: dict) -> str:
    """Format an LSP Location or LocationLink into a readable string."""
    uri = loc.get("uri") or loc.get("targetUri", "")
    if uri.startswith("file://"):
        uri = uri[7:]

    range_dict = loc.get("range") or loc.get("targetSelectionRange") or loc.get("targetRange")
    if range_dict:
        start = range_dict.get("start", {})
        line = start.get("line", 0) + 1
        char = start.get("character", 0)
        return f"{uri}:{line}:{char}"
    return uri


# LSP SymbolKind enum (spec §Symbol Kind) → readable name.
_SYMBOL_KINDS = {
    1: "File",
    2: "Module",
    3: "Namespace",
    4: "Package",
    5: "Class",
    6: "Method",
    7: "Property",
    8: "Field",
    9: "Constructor",
    10: "Enum",
    11: "Interface",
    12: "Function",
    13: "Variable",
    14: "Constant",
    15: "String",
    16: "Number",
    17: "Boolean",
    18: "Array",
    19: "Object",
    20: "Key",
    21: "Null",
    22: "EnumMember",
    23: "Struct",
    24: "Event",
    25: "Operator",
    26: "TypeParameter",
}


def _symbol_kind_name(kind: int) -> str:
    """Map an LSP SymbolKind integer to its readable name."""
    return _SYMBOL_KINDS.get(kind, f"Kind{kind}")


def _symbol_location(sym: dict) -> str:
    """Best-effort ``path:line:char`` for any symbol/hierarchy-item shape.

    Handles ``SymbolInformation`` (nested ``location``), ``DocumentSymbol``
    (file-local ``range``/``selectionRange`` only), and ``CallHierarchyItem``
    (top-level ``uri`` + ``range``).
    """
    loc = sym.get("location")
    if isinstance(loc, dict):
        return _format_location(loc)
    if sym.get("uri") or sym.get("targetUri"):
        return _format_location(sym)
    range_dict = sym.get("selectionRange") or sym.get("range")
    if range_dict:
        start = range_dict.get("start", {})
        return f":{start.get('line', 0) + 1}:{start.get('character', 0)}"
    return ""


def _format_symbols(symbols: list, indent: int = 0) -> list[str]:
    """Render a list of LSP symbols as compact ``Kind name  path:line`` lines.

    Recurses into ``DocumentSymbol.children`` with two-space indentation; a
    ``containerName`` (flat ``SymbolInformation``) is appended as ``[container]``.
    """
    lines: list[str] = []
    for sym in symbols:
        if not isinstance(sym, dict):
            continue
        kind = _symbol_kind_name(sym.get("kind", 0))
        name = sym.get("name", "?")
        where = _symbol_location(sym)
        container = sym.get("containerName")
        prefix = "  " * indent
        suffix = f"  [{container}]" if container else ""
        lines.append(f"{prefix}{kind} {name}  {where}{suffix}")
        children = sym.get("children")
        if children:
            lines.extend(_format_symbols(children, indent + 1))
    return lines


def _filter_symbols(symbols: list, kinds: list[str] | None = None, top_level: bool = False) -> list:
    """Filter list of LSP symbols by kind and/or top-level constraint."""
    filtered = []
    kinds_lower = [k.lower() for k in kinds] if kinds is not None else None
    for sym in symbols:
        if not isinstance(sym, dict):
            continue
        s = dict(sym)
        kind_name = _symbol_kind_name(s.get("kind", 0))

        # If top_level is True, we strip children from this level
        if top_level and "children" in s:
            s.pop("children")

        # Check if it matches kinds
        matches_kind = True
        if kinds_lower is not None:
            matches_kind = kind_name.lower() in kinds_lower

        if matches_kind:
            # If not top_level, we recursively filter children
            if not top_level and "children" in s and isinstance(s["children"], list):
                s["children"] = _filter_symbols(s["children"], kinds, top_level)
            filtered.append(s)
        elif not top_level and "children" in s and isinstance(s["children"], list):
            # If it didn't match the kind, but we are not top_level,
            # we check if any children match. If they do, we keep this container.
            child_matches = _filter_symbols(s["children"], kinds, top_level)
            if child_matches:
                s["children"] = child_matches
                filtered.append(s)
    return filtered


def _cap_and_spill(
    raw_results: list,
    display_items: list,
    formatted_lines: list[str],
    max_n: int = 100,
) -> str:
    """Limit the returned lines to max_n, and spill the full results payload to a JSONL file.

    Both the capping decision and the 'more' count are driven by the number of display items.
    """
    import getpass
    import logging
    import tempfile

    total_items = len(display_items)
    if total_items <= max_n:
        return "\n".join(formatted_lines)

    # We need to spill. Let's write the full raw_results payload.
    try:
        import json

        username = getpass.getuser()
        spill_dir = Path(tempfile.gettempdir()) / f"mcp-lsp-spill-{username}"
        spill_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", dir=spill_dir, delete=False, mode="w", encoding="utf-8"
        ) as f:
            for item in raw_results:
                f.write(json.dumps(item) + "\n")
            spill_path = f.name

        kept_lines = []
        item_count = 0
        for line in formatted_lines:
            if item_count >= max_n:
                break
            kept_lines.append(line)
            # Lines starting with "# " are headers (e.g. language name in workspace symbols)
            # and do not correspond to individual symbol items.
            if not line.startswith("# "):
                item_count += 1

        more_count = total_items - max_n
        kept_lines.append(
            f"... {more_count} more (narrow with kinds/top_level or query the full spill file)"
        )

        posix_spill_path = Path(spill_path).as_posix()
        kept_lines.append(
            f"\n[Spilled full results to: {spill_path} (query with data MCP server: "
            f"duckdb_query(query=\"SELECT * FROM read_json_auto('{posix_spill_path}')\"))]"
        )
    except Exception as e:
        logging.getLogger(__name__).warning(f"Failed to spill results to file: {e}")
        kept_lines = []
        item_count = 0
        for line in formatted_lines:
            if item_count >= max_n:
                break
            kept_lines.append(line)
            if not line.startswith("# "):
                item_count += 1
        kept_lines.append(f"\n[Error: Failed to write full spill file: {e}]")

    return "\n".join(kept_lines)
