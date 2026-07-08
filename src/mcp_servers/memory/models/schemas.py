from __future__ import annotations

import os

from pydantic import BaseModel, Field, field_validator


def normalize_path(v: str | None) -> str | None:
    if v is None:
        return None
    return os.path.abspath(os.path.expanduser(v))


class RememberArgs(BaseModel, frozen=True):
    content: str = Field(
        ...,
        description="The fact, preference, project detail, or instruction to remember.",
    )
    key: str | None = Field(
        None,
        description="An optional unique key to associate with this memory, allowing it to be easily overwritten or deleted later.",
    )
    category: str | None = Field(
        None,
        description="An optional category classification (e.g., 'preferences', 'project_notes', 'tool_tips').",
    )
    tags: list[str] | None = Field(
        None,
        description="An optional list of tags to label this memory for easier grouping and recall.",
    )


class RecallArgs(BaseModel, frozen=True):
    query: str = Field(
        ...,
        description="The search query or keyword to find matching memories.",
    )
    category: str | None = Field(
        None,
        description="Optional category to filter search results.",
    )
    tags: list[str] | None = Field(
        None,
        description="Optional list of tags to filter search results (memories matching any of the tags).",
    )
    limit: int = Field(
        5,
        ge=1,
        le=100,
        description="Maximum number of memories to return (defaults to 5).",
    )


class ForgetArgs(BaseModel, frozen=True):
    key: str | None = Field(
        None,
        description="The unique lookup key of the memory to forget. Either 'key' or 'id' must be specified.",
    )
    id: str | None = Field(
        None,
        description="The unique database ID of the memory to forget. Either 'key' or 'id' must be specified.",
    )


class ListMemoriesArgs(BaseModel, frozen=True):
    category: str | None = Field(
        None,
        description="Optional category to filter the list of memories.",
    )
    limit: int = Field(
        50,
        ge=1,
        le=1000,
        description="Maximum number of memories to return (defaults to 50).",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Number of memories to skip for pagination (defaults to 0).",
    )


class SyncExistingDataArgs(BaseModel, frozen=True):
    dry_run: bool = Field(
        False,
        description="If True, scan and preview the import without writing any data to the database.",
    )
    brain_dir: str | None = Field(
        None,
        description="Optional custom path to the Antigravity brain directory (defaults to ~/.gemini/antigravity-cli/brain).",
    )
    summaries_db: str | None = Field(
        None,
        description="Optional custom path to the Antigravity conversation summaries database file (defaults to ~/.gemini/antigravity-cli/conversation_summaries.db).",
    )
    claude_dir: str | None = Field(
        None,
        description="Optional custom path to the Claude projects directory (defaults to ~/.claude/projects).",
    )

    @field_validator("brain_dir", "summaries_db", "claude_dir")
    @classmethod
    def validate_paths(cls, v: str | None) -> str | None:
        return normalize_path(v)
