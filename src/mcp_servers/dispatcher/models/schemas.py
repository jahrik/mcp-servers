from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SubmitJobArgs(BaseModel, frozen=True):
    worker_type: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="The type of worker to handle this job.",
    )
    payload: dict[str, Any] = Field(
        ...,
        description="JSON payload for the job.",
    )


class GetJobStatusArgs(BaseModel, frozen=True):
    job_id: str = Field(
        ...,
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        description="The ID of the job to check.",
    )
