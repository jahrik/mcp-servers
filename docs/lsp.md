# lsp

The `lsp` server proxies requests to an underlying Language Server Protocol (LSP) process (like `pyright`, `ts-server`, or `gopls`), exposing language intelligence tools to AI agents without requiring the agents to manage JSON-RPC lifecycle, binary execution, or document syncing.

## Tools

- `lsp_hover`
  - **Description**: Returns the type signature and docstring for the symbol at the requested file position.
  - **Inputs**:
    - `filepath` (string): Absolute or workspace-relative path to the file. Must reside within the `MCP_LSP_ROOT`.
    - `line` (integer): 1-indexed line number.
    - `char` (integer): 0-indexed character position.
- `lsp_definition`
  - **Description**: Returns the file, line number, and character where the symbol at the requested position is defined (formatted as `path:line:char`).
  - **Inputs**:
    - `filepath` (string): Absolute or workspace-relative path to the file.
    - `line` (integer): 1-indexed line number.
    - `char` (integer): 0-indexed character position.
- `lsp_references`
  - **Description**: Returns a list of all locations in the codebase that reference the symbol at the requested position (each formatted as `path:line:char`).
  - **Inputs**:
    - `filepath` (string): Absolute or workspace-relative path to the file.
    - `line` (integer): 1-indexed line number.
    - `char` (integer): 0-indexed character position.
- `lsp_document_symbols`
  - **Description**: Returns a structured list of all symbols (classes, functions, methods, etc.) defined in the given file.
  - **Inputs**:
    - `filepath` (string): Absolute or workspace-relative path to the file.
- `lsp_workspace_symbols`
  - **Description**: Searches the entire workspace for symbols matching the given query string.
  - **Inputs**:
    - `query` (string): The search query.
- `lsp_diagnostics`
  - **Description**: Returns any syntax errors, type-checking errors, or warnings for the given file.
  - **Inputs**:
    - `filepath` (string): Absolute or workspace-relative path to the file.

## Configuration

The server expects standard environment variables to configure its subprocess:

- `MCP_LSP_COMMAND` (default: `"pyright-langserver --stdio"`)
  The command to execute the underlying language server. It is parsed using shell-like syntax, so quoted arguments (e.g. `"/path with spaces/langserver" --stdio`) are supported.
- `MCP_LSP_ROOT` (default: Current Working Directory)
  The root directory of the workspace the language server should analyze. Tilde (`~`) is automatically expanded to the user's home directory.

## Lifecycle

The server automatically handles LSP lifecycle handshakes:
1. Spawns the subprocess defined by `MCP_LSP_COMMAND`.
2. Sends the `initialize` request with the `MCP_LSP_ROOT` URI.
3. Upon receiving a tool invocation, sends `textDocument/didOpen` for the file (if not already opened).
4. Executes the requested LSP method (e.g., `textDocument/hover`).
5. Upon shutdown, gracefully terminates the background subprocess and pending asyncio tasks.
