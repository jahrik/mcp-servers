import json
import pathlib
from typing import Any

from mcp.server.fastmcp import Context

from mcp_servers.lsp import utils

_last_code_actions: dict[str, Any] = {"language_id": None, "actions": []}


def apply_workspace_edit(edit: dict) -> str:
    """Applies a WorkspaceEdit (changes or documentChanges) to disk."""
    file_changes = {}

    if "changes" in edit:
        for uri, edits in edit["changes"].items():
            file_changes[uri] = edits

    if "documentChanges" in edit:
        for doc_change in edit["documentChanges"]:
            if "textDocument" in doc_change:
                uri = doc_change["textDocument"]["uri"]
                file_changes.setdefault(uri, []).extend(doc_change["edits"])

    if not file_changes:
        return "No changes to apply."

    results = []
    for uri, edits in file_changes.items():
        if not uri.startswith("file://"):
            continue
        filepath = uri[7:]
        path_obj = pathlib.Path(filepath)
        if not path_obj.exists():
            results.append(f"Skipped {filepath} (does not exist)")
            continue

        with open(path_obj, encoding="utf-8") as f:
            lines = f.readlines()

        edits.sort(
            key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]),
            reverse=True,
        )

        for e in edits:
            start_line = e["range"]["start"]["line"]
            start_char = e["range"]["start"]["character"]
            end_line = e["range"]["end"]["line"]
            end_char = e["range"]["end"]["character"]
            new_text = e["newText"]

            if start_line == end_line:
                line = lines[start_line]
                lines[start_line] = line[:start_char] + new_text + line[end_char:]
            else:
                start_str = lines[start_line][:start_char]
                end_str = lines[end_line][end_char:] if end_line < len(lines) else ""

                lines[start_line] = start_str + new_text + end_str
                for i in range(start_line + 1, end_line + 1):
                    if i < len(lines):
                        lines[i] = ""

        with open(path_obj, "w", encoding="utf-8") as f:
            f.write("".join(lines))

        results.append(f"Updated {filepath} ({len(edits)} edits applied)")

    return "\n".join(results)


async def lsp_rename(filepath: str, line: int, character: int, new_name: str, ctx: Context) -> str:
    """Rename a symbol across the workspace and apply the edits to disk."""
    path_obj = pathlib.Path(filepath)
    if not path_obj.exists():
        return f"Error: File not found {filepath}"

    try:
        uri, language_id = await utils._sync_file_with_lsp(path_obj)
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": character},
            "newName": new_name,
        }
        res = await utils.lsp_client.send_request(language_id, "textDocument/rename", params)
        if not res:
            return "No rename edits returned."

        return apply_workspace_edit(res)
    except Exception as e:
        return f"Error querying LSP for rename: {e}"


async def lsp_code_actions(filepath: str, line: int, character: int, ctx: Context) -> str:
    """Get available code actions for a specific location. Use lsp_execute_code_action to apply one."""
    path_obj = pathlib.Path(filepath)
    if not path_obj.exists():
        return f"Error: File not found {filepath}"

    try:
        uri, language_id = await utils._sync_file_with_lsp(path_obj)
        params = {
            "textDocument": {"uri": uri},
            "range": {
                "start": {"line": line - 1, "character": character},
                "end": {"line": line - 1, "character": character},
            },
            "context": {"diagnostics": []},
        }
        res = await utils.lsp_client.send_request(language_id, "textDocument/codeAction", params)
        if not res:
            return "No code actions available."

        global _last_code_actions
        _last_code_actions["language_id"] = language_id
        _last_code_actions["actions"] = res

        output = []
        for i, action in enumerate(res):
            title = action.get("title", "Unknown action")
            kind = action.get("kind", "")
            output.append(f"[{i}] {title} (kind: {kind})")

        return (
            "Available code actions:\n"
            + "\n".join(output)
            + "\n\nUse lsp_execute_code_action to run one of these."
        )
    except Exception as e:
        return f"Error querying LSP for code actions: {e}"


async def lsp_execute_code_action(index: int, ctx: Context) -> str:
    """Execute a code action previously returned by lsp_code_actions."""
    global _last_code_actions
    actions = _last_code_actions.get("actions", [])
    language_id = _last_code_actions.get("language_id")

    if index < 0 or index >= len(actions):
        return f"Error: Invalid index {index}. Only {len(actions)} actions available."

    action = actions[index]
    results = []

    if "edit" in action:
        results.append("Applying workspace edit:")
        results.append(apply_workspace_edit(action["edit"]))

    if "command" in action:
        command_obj = action["command"]
        # CodeAction might return a Command directly or inside a CodeAction
        if isinstance(command_obj, str):
            cmd_name = command_obj
            args = []
        else:
            cmd_name = command_obj.get("command")
            args = command_obj.get("arguments", [])

        try:
            res = await utils.lsp_client.send_request(
                str(language_id),
                "workspace/executeCommand",
                {"command": cmd_name, "arguments": args},
            )
            # Some commands might also return a WorkspaceEdit!
            if isinstance(res, dict) and ("changes" in res or "documentChanges" in res):
                results.append("Applying workspace edit from command:")
                results.append(apply_workspace_edit(res))
            else:
                results.append(f"Command '{cmd_name}' executed. Result: {json.dumps(res)}")
        except Exception as e:
            results.append(f"Error executing command: {e}")

    if not results:
        return f"Action '{action.get('title')}' executed but no edits or commands were found."

    return "\n".join(results)
