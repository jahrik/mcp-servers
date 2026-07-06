from __future__ import annotations

import os
from pathlib import Path

from mcp_servers.lsp.client import LSPClient

WORKSPACE_ROOT = os.environ.get("MCP_LSP_ROOT", os.getcwd())
if WORKSPACE_ROOT.startswith("~"):  # pragma: no cover
    WORKSPACE_ROOT = str(Path(WORKSPACE_ROOT).expanduser())

# Create a global client instance
lsp_client = LSPClient()


def _prepare_file(filepath: str) -> Path | str:
    """Validate and resolve filepath. Returns Path on success, error string on failure."""
    p = Path(filepath)
    filepath_obj = (Path(WORKSPACE_ROOT) / p).resolve() if not p.is_absolute() else p.resolve()
    root_obj = Path(WORKSPACE_ROOT).resolve()
    try:
        filepath_obj.relative_to(root_obj)
    except ValueError:
        return f"Error: Filepath must be within the workspace root {WORKSPACE_ROOT}"
    if not filepath_obj.exists():
        return f"Error: File not found: {filepath_obj}"
    return filepath_obj


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

    with open(filepath_obj, encoding="utf-8") as f:
        content = f.read()
    await lsp_client.sync_file(uri, language_id, content)
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
