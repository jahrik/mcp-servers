from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field

_UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


class JobStatus(enum.StrEnum):
    """Lifecycle states a dispatcher job can be in."""

    QUEUED = "Queued"
    RUNNING = "Running"
    IN_REVIEW = "InReview"
    CHANGES_REQUESTED = "ChangesRequested"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class SubmitJobArgs(BaseModel, frozen=True):
    worker_type: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9_-]+$",
        max_length=256,
        description="The type of worker to handle this job.",
    )
    payload: dict[str, Any] = Field(
        ...,
        description="JSON payload for the job.",
    )
    parent_id: str | None = Field(
        None,
        pattern=_UUID_PATTERN,
        description="Optional ID of parent task to link subtasks.",
    )


class ClaimJobArgs(BaseModel, frozen=True):
    worker_type: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9_-]+$",
        max_length=256,
        description="The type of worker looking for a job.",
    )
    agent_id: str = Field(
        ...,
        max_length=256,
        description="ID of the specific standing agent process claiming the job.",
    )


class HeartbeatJobArgs(BaseModel, frozen=True):
    job_id: str = Field(
        ...,
        pattern=_UUID_PATTERN,
        description="The ID of the job to heartbeat.",
    )


class RequeueStalledJobsArgs(BaseModel, frozen=True):
    timeout_minutes: int = Field(
        ...,
        gt=0,
        description="Jobs with an updated_at older than this many minutes will be requeued.",
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
        description="New status for the job.",
    )
    result: dict[str, Any] | None = Field(
        None,
        description="Optional JSON-serializable task outputs/feedback.",
    )


class SendMessageArgs(BaseModel, frozen=True):
    job_id: str = Field(
        ...,
        pattern=_UUID_PATTERN,
        description="The ID of the job this message is associated with.",
    )
    sender: str = Field(
        ...,
        max_length=256,
        description="The agent sending the message (e.g. 'architect', 'devlead', 'qa').",
    )
    recipient: str = Field(
        ...,
        max_length=256,
        description="The target agent or 'all'.",
    )
    content: str = Field(
        ...,
        description="The markdown content of the message.",
    )


class GetMessagesArgs(BaseModel, frozen=True):
    job_id: str = Field(
        ...,
        pattern=_UUID_PATTERN,
        description="The ID of the job to retrieve messages for.",
    )
    since: str | None = Field(
        None,
        description="Optional ISO-8601 timestamp. Only messages created after this will be returned.",
    )


class ListJobsArgs(BaseModel, frozen=True):
    status: JobStatus | None = Field(
        None,
        description="Optional status to filter by.",
    )
    limit: int = Field(
        50,
        ge=1,
        le=500,
        description="Maximum number of jobs to return.",
    )


class CleanupJobsArgs(BaseModel, frozen=True):
    older_than_days: int | None = Field(
        None,
        ge=0,
        description="Only delete terminal jobs whose last update is older than this many "
        "days. Omit to delete all terminal (Completed/Failed) jobs.",
    )
