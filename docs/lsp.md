# lsp

The `lsp` server fronts real Language Server Protocol processes (`pyright`, `gopls`,
`rust-analyzer`, `typescript-language-server`) and exposes their semantic intelligence as MCP
tools. Agents get IDE-grade answers about what a symbol *means* and connects to — resolving
imports, types, and scope — without managing JSON-RPC lifecycles, subprocesses, or document
syncing themselves.

Installed as `mcp-lsp`; registered as `lsp`.

The guiding split for agents: `rg` for text, `ts_*` for syntax structure (tree-sitter), and
`lsp_*` for what a symbol *means*. Prefer `lsp_*` over grep whenever the question is semantic
(definition, references, type, implementation, call flow, rename). Use `ts_*` for instant
structural queries, cold-start outlines, or languages without a configured LSP.

## Architecture

The server is a **router over per-language sessions**, not a single proxy:

- **`LSPClient` (router)** keys one `LSPSession` per language id (`python`, `go`, `rust`,
  `typescript`, `javascript`) and maps each to its server command. Sessions are spawned **lazily**
  on first use for that language, not at boot.
- **`LSPSession` (transport)** speaks raw JSON-RPC over the subprocess's stdio (`Content-Length`
  framing), matching responses to pending requests by id and caching published diagnostics.
- **Crash recovery** — a dead session is detected, reaped, and recreated transparently; every
  request and file-sync retries once on a broken pipe.
- **Idle reaping** — a background loop stops any session unused for 10 minutes, freeing the
  subprocess.
- **Workspace file watcher** — a background loop polls the workspace (skipping `.git`,
  `__pycache__`, `node_modules`, `.venv`) and pushes `workspace/didChangeWatchedFiles`
  (created/changed/deleted) to every live session so servers see edits made outside the tools.

## Path resolution

Every file-taking tool accepts an **absolute or workspace-relative** `filepath`. Relative paths
are resolved against the workspace root **and each immediate child repository** (directories
containing `.git`), so a bare `src/foo.py` resolves correctly even when `MCP_LSP_ROOT` points at a
parent directory holding several checked-out repos.

- All candidates are containment-checked — a path can never escape `MCP_LSP_ROOT` via `..`.
- A relative path that matches files in **multiple** repos returns a clear "pass an absolute path
  to disambiguate" error.
- Directories are rejected (`Not a regular file`), and unreadable paths return an error string
  rather than crashing the tool.

## Output format

Symbol- and hierarchy-listing tools return **compact, one-line-per-result** text
(`Kind name  path:line`, indented for nesting) by default, keeping output small and cheap for an
agent to read. Pass `detail="full"` to get the raw LSP JSON instead (e.g. when you need exact
ranges). `detail` is validated — an unknown value returns an explicit error rather than silently
falling back.

## Tools

### Navigation (position-based)

Each takes `filepath`, `line` (1-indexed), and `char` (0-indexed).

- `lsp_hover` — type signature and docstring for the symbol at a position.
- `lsp_definition` — go-to-definition; returns the true source location as `path:line:char`,
  resolving imports and aliases.
- `lsp_type_definition` — jump to the definition of a value's *type* (e.g. a Go interface, a
  Python class behind a variable).
- `lsp_implementation` — concrete implementations of an interface/abstract symbol, including
  structural implementers that never name it textually.
- `lsp_references` — every semantic use of the symbol across the project, excluding same-named
  identifiers in other scopes.
- `lsp_call_hierarchy` — trace call flow. Extra input `direction`: `"incoming"` (callers) or
  `"outgoing"` (callees). Supports `detail`.

### Symbols

- `lsp_document_symbols` — outline of every symbol in a file (nested), as `Kind name  path:line`.
  Inputs: `filepath`; supports `detail`.
- `lsp_workspace_symbols` — find a declaration by name across the whole workspace (fans out to all
  languages). Inputs: `query`; supports `detail`.
- `lsp_document_highlight` — every read/write of the symbol within one file. Inputs: `filepath`,
  `line`, `char`.

### Diagnostics

- `lsp_diagnostics` — live syntax and type-checking errors/warnings for a file, with positions
  (polls the published-diagnostics cache briefly for the server to finish analyzing). Inputs:
  `filepath`.

### Mutations (write to disk)

- `lsp_rename` — semantic rename applied across all affected files; rewrites only true references,
  leaving unrelated same-named identifiers untouched. Inputs: `filepath`, `line`, `character`,
  `new_name`.
- `lsp_code_actions` — list available quick-fixes and refactors at a location. Inputs: `filepath`,
  `line`, `character`.
- `lsp_execute_code_action` — apply an action returned by `lsp_code_actions`, including any
  follow-up `workspace/executeCommand` edit. Inputs: `index`.
- `lsp_format` — format a file using the active language server's formatting capability, writing
  the result to disk. Inputs: `filepath`.

### Tree-sitter (instant, offline structural analysis)

These tools use tree-sitter grammars to parse files directly — no running language server,
no initialization delay, no subprocess. They complement the `lsp_*` tools for cases where you
need structural pattern matching, instant outlines during cold start, or support for languages
without a configured LSP.

Each takes `filepath` (absolute or workspace-relative) and an optional `language` override
(auto-detected from extension when omitted). Supported: Python, Go, Rust, TypeScript, JavaScript.

- `ts_query` — run a tree-sitter S-expression query pattern against a file and return matching
  nodes with positions and text. Use for structural searches LSP cannot express (e.g. "all
  functions with a decorator", "all try blocks without a finally").
  Inputs: `filepath`, `query`, optional `language`.
- `ts_outline` — fast symbol outline (classes and functions with line ranges). Works for languages
  without a configured LSP and has zero startup delay.
  Inputs: `filepath`, optional `language`.
- `ts_extract` — extract the full source text of a named node (function, class) by structural
  identity, without knowing exact line numbers.
  Inputs: `filepath`, `node_type`, `name`, optional `language`.
- `ts_scope_at_position` — return the chain of enclosing scopes (module, class, function) at a
  position, outermost first.
  Inputs: `filepath`, `line` (1-indexed), `char` (0-indexed), optional `language`.

## Configuration

- `MCP_LSP_COMMAND` (default: `"pyright-langserver --stdio"`)
  Command for the **Python** language server, parsed shell-style so quoted arguments
  (e.g. `"/path with spaces/langserver" --stdio`) are supported. Other languages use their
  standard binaries (`gopls`, `rust-analyzer`, `typescript-language-server --stdio`), which must
  be on `PATH`.
- `MCP_LSP_ROOT` (default: current working directory)
  Root directory the language servers analyze. Tilde (`~`) is expanded. May be a parent of several
  repositories — see [Path resolution](#path-resolution).

## Lifecycle

1. On start, the router's initialize handshake records the `MCP_LSP_ROOT` URI and launches the
   idle-reaper and file-watcher background loops.
2. The first tool call for a language spawns that language server, runs the LSP `initialize`
   handshake (declaring client capabilities), and caches the session.
3. Each file-taking tool resolves and validates the path, then syncs the file to the server —
   `textDocument/didOpen` on first touch, incremental `textDocument/didChange` on later edits
   (a minimal range diff when the server supports it, full-text otherwise). Re-sync happens only
   when the file's modification time changed.
4. The requested LSP method runs (e.g. `textDocument/definition`) and the result is formatted.
5. On shutdown, each language server is sent `shutdown`/`exit`, background tasks are cancelled, and
   subprocesses are terminated (killed if they don't exit within 5s).

## Known limitations

- **On-demand analysis (pyright):** pyright only fully analyzes files opened via a tool call, so
  `lsp_workspace_symbols` and cross-file `lsp_references` can be incomplete until the relevant
  files have been touched. Enabling the language server's own project-wide index is the intended
  fix.
- **Verbose symbol sets:** language servers report every local variable, so document symbols for a
  large file can still be long even in compact form; server-side kind/top-level filtering is
  planned.
