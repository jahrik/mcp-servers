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
    """Roots a relative filepath may be resolved against.

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
        if not filepath_obj.exists():
            return f"Error: File not found: {filepath_obj}"
        return filepath_obj

    # Relative path: try the workspace root and each child repository. Every
    # candidate is containment-checked, so this never escapes the workspace.
    matches: list[Path] = []
    for base in _candidate_roots():
        candidate = (base / p).resolve()
        try:
            candidate.relative_to(root_obj)
        except ValueError:
            continue
        if candidate.exists() and candidate not in matches:
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
