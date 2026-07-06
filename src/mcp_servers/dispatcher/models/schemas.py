from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field

_UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


class JobStatus(enum.StrEnum):
    """Lifecycle states a dispatcher job can be in.

    ``submit_job`` starts a job as ``Running``; a spawn failure marks it ``Failed``.
    The background worker reports ``Completed`` (or ``Failed``) via ``update_job_status``.
    """

    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"


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
        pattern=_UUID_PATTERN,
        description="The ID of the job to check.",
    )


class UpdateJobStatusArgs(BaseModel, frozen=True):
    job_id: str = Field(
        ...,
        pattern=_UUID_PATTERN,
        description="The ID of the job to update.",
    )
    status: JobStatus = Field(
        ...,
        description="New status: one of Running, Completed, or Failed.",
    )
