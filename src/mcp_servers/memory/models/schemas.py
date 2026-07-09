from __future__ import annotations

from pydantic import BaseModel, Field


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
