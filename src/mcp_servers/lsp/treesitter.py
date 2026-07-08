from __future__ import annotations

from pathlib import Path

import tree_sitter as ts

_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
}

_PARSERS: dict[str, ts.Parser] = {}
_LANGUAGES: dict[str, ts.Language] = {}


def _load_language(language: str) -> ts.Language:
    if language in _LANGUAGES:
        return _LANGUAGES[language]

    if language == "python":
        import tree_sitter_python as mod
    elif language == "go":
        import tree_sitter_go as mod
    elif language == "rust":
        import tree_sitter_rust as mod
    elif language == "typescript":
        import tree_sitter_typescript as mod

        lang = ts.Language(mod.language_typescript())
        _LANGUAGES[language] = lang
        return lang
    elif language == "tsx":
        import tree_sitter_typescript as mod

        lang = ts.Language(mod.language_tsx())
        _LANGUAGES[language] = lang
        return lang
    elif language == "javascript":
        import tree_sitter_javascript as mod
    else:
        raise ValueError(f"Unsupported language: {language}")

    lang = ts.Language(mod.language())
    _LANGUAGES[language] = lang
    return lang


def get_parser(language: str) -> ts.Parser:
    if language in _PARSERS:
        return _PARSERS[language]
    lang = _load_language(language)
    parser = ts.Parser(lang)
    _PARSERS[language] = parser
    return parser


def detect_language(filepath: Path) -> str | None:
    return _EXTENSION_TO_LANGUAGE.get(filepath.suffix)


def parse_file(filepath: Path, language: str | None = None) -> tuple[ts.Tree, str]:
    """Parse a file and return the tree and detected language."""
    if language is None:
        language = detect_language(filepath)
    if language is None:
        raise ValueError(
            f"Cannot detect language for {filepath.suffix}. "
            f"Supported: {', '.join(sorted(_EXTENSION_TO_LANGUAGE.keys()))}"
        )
    parser = get_parser(language)
    source = filepath.read_bytes()
    tree = parser.parse(source)
    return tree, language


def run_query(tree: ts.Tree, language: str, pattern: str) -> list[dict]:
    """Run a tree-sitter query and return captures."""
    lang = _load_language(language)
    query = ts.Query(lang, pattern)
    cursor = ts.QueryCursor(query)
    matches = cursor.matches(tree.root_node)

    results: list[dict] = []
    for _pattern_idx, captures in matches:
        for capture_name, nodes in captures.items():
            for node in nodes:
                results.append(
                    {
                        "capture": capture_name,
                        "type": node.type,
                        "text": (node.text or b"").decode("utf-8", errors="replace"),
                        "start_line": node.start_point[0] + 1,
                        "start_char": node.start_point[1],
                        "end_line": node.end_point[0] + 1,
                        "end_char": node.end_point[1],
                    }
                )
    return results


_OUTLINE_QUERIES: dict[str, str] = {
    "python": """
        (class_definition name: (identifier) @class.name) @class.def
        (function_definition name: (identifier) @function.name) @function.def
    """,
    "go": """
        (type_declaration (type_spec name: (type_identifier) @class.name)) @class.def
        (function_declaration name: (identifier) @function.name) @function.def
        (method_declaration name: (field_identifier) @function.name) @function.def
    """,
    "rust": """
        (struct_item name: (type_identifier) @class.name) @class.def
        (enum_item name: (type_identifier) @class.name) @class.def
        (trait_item name: (type_identifier) @class.name) @class.def
        (impl_item type: (type_identifier) @class.name) @class.def
        (function_item name: (identifier) @function.name) @function.def
    """,
    "typescript": """
        (class_declaration name: (type_identifier) @class.name) @class.def
        (interface_declaration name: (type_identifier) @class.name) @class.def
        (function_declaration name: (identifier) @function.name) @function.def
        (method_definition name: (property_identifier) @function.name) @function.def
    """,
    "javascript": """
        (class_declaration name: (identifier) @class.name) @class.def
        (function_declaration name: (identifier) @function.name) @function.def
        (method_definition name: (property_identifier) @function.name) @function.def
    """,
}
_OUTLINE_QUERIES["tsx"] = _OUTLINE_QUERIES["typescript"]


def get_outline(tree: ts.Tree, language: str) -> list[dict]:
    """Extract symbol outline from a parsed tree."""
    query_str = _OUTLINE_QUERIES.get(language)
    if query_str is None:
        raise ValueError(f"No outline query for language: {language}")

    lang = _load_language(language)
    query = ts.Query(lang, query_str)
    cursor = ts.QueryCursor(query)
    matches = cursor.matches(tree.root_node)

    symbols: list[dict] = []
    seen_ids: set[int] = set()
    for _pattern_idx, captures in matches:
        name_nodes = captures.get("class.name") or captures.get("function.name")
        def_nodes = captures.get("class.def") or captures.get("function.def")
        if not name_nodes or not def_nodes:
            continue

        def_node = def_nodes[0]
        if def_node.id in seen_ids:
            continue
        seen_ids.add(def_node.id)

        name_node = name_nodes[0]
        kind = "class" if "class.name" in captures else "function"
        symbols.append(
            {
                "kind": kind,
                "name": (name_node.text or b"").decode("utf-8", errors="replace"),
                "start_line": def_node.start_point[0] + 1,
                "end_line": def_node.end_point[0] + 1,
                "start_char": def_node.start_point[1],
            }
        )
    return symbols


_SCOPE_NODE_TYPES: dict[str, set[str]] = {
    "python": {"module", "class_definition", "function_definition"},
    "go": {"source_file", "function_declaration", "method_declaration", "func_literal"},
    "rust": {"source_file", "function_item", "impl_item", "trait_item", "mod_item"},
    "typescript": {
        "program",
        "class_declaration",
        "function_declaration",
        "method_definition",
        "arrow_function",
    },
    "tsx": {
        "program",
        "class_declaration",
        "function_declaration",
        "method_definition",
        "arrow_function",
    },
    "javascript": {
        "program",
        "class_declaration",
        "function_declaration",
        "method_definition",
        "arrow_function",
    },
}


def _node_name(node: ts.Node) -> str | None:
    """Extract the name of a scope node if it has one."""
    name_node = node.child_by_field_name("name")
    if name_node:
        return (name_node.text or b"").decode("utf-8", errors="replace")
    return None


def get_scope_at_position(tree: ts.Tree, language: str, line: int, char: int) -> list[dict]:
    """Return the chain of enclosing scopes at a position (outermost first)."""
    scope_types = _SCOPE_NODE_TYPES.get(language)
    if scope_types is None:
        raise ValueError(f"No scope info for language: {language}")

    point = (line, char)
    node = tree.root_node.descendant_for_point_range(point, point)

    scopes: list[dict] = []
    current = node
    while current is not None:
        if current.type in scope_types:
            scopes.append(
                {
                    "type": current.type,
                    "name": _node_name(current),
                    "start_line": current.start_point[0] + 1,
                    "end_line": current.end_point[0] + 1,
                }
            )
        current = current.parent

    scopes.reverse()
    return scopes


class InvalidNodeTypeError(ValueError):
    pass


def extract_node(
    tree: ts.Tree, language: str, source: bytes, node_type: str, name: str
) -> dict | None:
    """Find and extract a named node's full text."""
    lang = _load_language(language)

    query_str = f"({node_type} name: (_) @name) @def"
    try:
        query = ts.Query(lang, query_str)
    except Exception as e:
        raise InvalidNodeTypeError(f"Invalid node type '{node_type}': {e}") from e

    cursor = ts.QueryCursor(query)
    matches = cursor.matches(tree.root_node)

    for _pattern_idx, captures in matches:
        name_nodes = captures.get("name")
        def_nodes = captures.get("def")
        if not name_nodes or not def_nodes:
            continue
        name_node = name_nodes[0]
        if (name_node.text or b"").decode("utf-8", errors="replace") == name:
            def_node = def_nodes[0]
            text = source[def_node.start_byte : def_node.end_byte].decode("utf-8", errors="replace")
            return {
                "text": text,
                "start_line": def_node.start_point[0] + 1,
                "end_line": def_node.end_point[0] + 1,
                "start_char": def_node.start_point[1],
                "end_char": def_node.end_point[1],
            }
    return None
