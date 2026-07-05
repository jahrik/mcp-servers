from __future__ import annotations

import os

from pydantic import BaseModel, Field, field_validator


def normalize_path(v: str | None) -> str | None:
    if v is None:
        return None
    return os.path.abspath(os.path.expanduser(v))


class DuckDbQueryArgs(BaseModel, frozen=True):
    query: str = Field(
        ...,
        description="The SQL query to run. Supports both read queries (SELECT) and mutations (CREATE, INSERT, UPDATE, DROP, COPY).",
    )
    database: str | None = Field(
        None,
        description="Path to a persistent DuckDB database file (e.g., 'data.db'). If omitted, runs against a temporary in-memory database.",
    )
    read_only: bool = Field(
        False,
        description="Connect to the database in read-only mode. Defaults to False to allow mutations.",
    )
    max_rows: int = Field(
        2000,
        ge=1,
        le=10000,
        description="Max rows to return to prevent context window overflow. Defaults to 2000.",
    )

    @field_validator("database")
    @classmethod
    def validate_database_path(cls, v: str | None) -> str | None:
        return normalize_path(v)


class DuckDbDescribeArgs(BaseModel, frozen=True):
    path: str = Field(
        ..., description="Path to a CSV, JSON, Parquet file, or table/view name to describe."
    )
    database: str | None = Field(
        None, description="Path to a persistent DuckDB database file (optional)."
    )

    @field_validator("path")
    @classmethod
    def validate_target_path(cls, v: str) -> str:
        # Resolve target path if it looks like a file (extensions or path separators)
        if (
            "/" in v
            or "\\" in v
            or any(v.endswith(ext) for ext in [".csv", ".tsv", ".json", ".jsonl", ".parquet"])
        ):
            resolved = normalize_path(v)
            return resolved if resolved is not None else v
        return v

    @field_validator("database")
    @classmethod
    def validate_database_path(cls, v: str | None) -> str | None:
        return normalize_path(v)


class DuckDbListTablesArgs(BaseModel, frozen=True):
    database: str | None = Field(
        None, description="Path to a persistent DuckDB database file (optional)."
    )

    @field_validator("database")
    @classmethod
    def validate_database_path(cls, v: str | None) -> str | None:
        return normalize_path(v)


class DuckDbCloseDatabaseArgs(BaseModel, frozen=True):
    database: str | None = Field(
        None,
        description="Path to the database connection to close (e.g. 'data.db' or omit for in-memory).",
    )

    @field_validator("database")
    @classmethod
    def validate_database_path(cls, v: str | None) -> str | None:
        return normalize_path(v)
