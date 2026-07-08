from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --- shared building blocks -------------------------------------------------

_FILEPATH = "Absolute or workspace-relative path to the file."
_LINE = "1-indexed line number."
_CHAR = "0-indexed character position."
_LANGUAGE = "Language override (auto-detected from the file extension if omitted)."
_DETAIL = "``compact`` (default) for one line per result; ``full`` for the raw LSP JSON."
_KINDS = "Optional list of symbol kinds to filter by (e.g. ``['Class', 'Method']``)."


class PositionArgs(BaseModel, frozen=True):
    """A file position — shared by the position-based navigation tools."""

    filepath: str = Field(description=_FILEPATH)
    line: int = Field(ge=1, description=_LINE)
    char: int = Field(ge=0, description=_CHAR)


class FilePathArgs(BaseModel, frozen=True):
    """A single file path — shared by whole-file tools."""

    filepath: str = Field(description=_FILEPATH)


# --- navigation -------------------------------------------------------------


class CallHierarchyArgs(BaseModel, frozen=True):
    filepath: str = Field(description=_FILEPATH)
    line: int = Field(ge=1, description=_LINE)
    char: int = Field(ge=0, description=_CHAR)
    direction: Literal["incoming", "outgoing"] = Field(
        description="``incoming`` returns the callers of the symbol; "
        "``outgoing`` returns the functions it calls."
    )
    detail: Literal["compact", "full"] = Field("compact", description=_DETAIL)


# --- symbols ----------------------------------------------------------------


class DocumentSymbolsArgs(BaseModel, frozen=True):
    filepath: str = Field(description=_FILEPATH)
    detail: Literal["compact", "full"] = Field("compact", description=_DETAIL)
    kinds: list[str] | None = Field(None, description=_KINDS)
    top_level: bool = Field(False, description="If True, return only top-level symbols.")


class WorkspaceSymbolsArgs(BaseModel, frozen=True):
    query: str = Field(description="The symbol name or partial name to search for.")
    detail: Literal["compact", "full"] = Field("compact", description=_DETAIL)
    kinds: list[str] | None = Field(None, description=_KINDS)
    top_level: bool = Field(False, description="If True, return only top-level symbols.")


# --- mutations --------------------------------------------------------------


class RenameArgs(BaseModel, frozen=True):
    filepath: str = Field(description=_FILEPATH)
    line: int = Field(ge=1, description=_LINE)
    character: int = Field(ge=0, description=_CHAR)
    new_name: str = Field(description="The new name for the symbol.")


class CodeActionsArgs(BaseModel, frozen=True):
    filepath: str = Field(description=_FILEPATH)
    line: int = Field(ge=1, description=_LINE)
    character: int = Field(ge=0, description=_CHAR)


class ExecuteCodeActionArgs(BaseModel, frozen=True):
    index: int = Field(
        ge=0, description="Index of the action from the most recent ``lsp_code_actions`` call."
    )


# --- tree-sitter (offline; no LSP server) -----------------------------------


class TsQueryArgs(BaseModel, frozen=True):
    filepath: str = Field(description=_FILEPATH)
    query: str = Field(
        description="Tree-sitter S-expression query pattern "
        "(e.g. ``(function_definition name: (identifier) @name)``)."
    )
    language: str | None = Field(None, description=_LANGUAGE)


class TsOutlineArgs(BaseModel, frozen=True):
    filepath: str = Field(description=_FILEPATH)
    language: str | None = Field(None, description=_LANGUAGE)


class TsExtractArgs(BaseModel, frozen=True):
    filepath: str = Field(description=_FILEPATH)
    node_type: str = Field(
        description="Tree-sitter node type (e.g. ``function_definition``, ``class_definition``)."
    )
    name: str = Field(description="Name of the symbol to extract.")
    language: str | None = Field(None, description=_LANGUAGE)


class TsScopeArgs(BaseModel, frozen=True):
    filepath: str = Field(description=_FILEPATH)
    line: int = Field(ge=1, description=_LINE)
    char: int = Field(0, ge=0, description=_CHAR)
    language: str | None = Field(None, description=_LANGUAGE)
