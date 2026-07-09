from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_servers.dispatcher.models.schemas import (
    ClaimJobArgs,
    GetJobStatusArgs,
    JobStatus,
    SendMessageArgs,
    SubmitJobArgs,
    UpdateJobStatusArgs,
)
from mcp_servers.dispatcher.tools import jobs


@pytest.fixture
def mock_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test_dispatcher_e2e.db"
    monkeypatch.setenv("MCP_DISPATCHER_DB_PATH", str(db_path))
    return db_path


def test_pull_model_e2e(mock_db: Path) -> None:
    # 1. Architect submits a devlead job
    devlead_job_id = jobs.submit_job(
        SubmitJobArgs(worker_type="devlead", payload={"task": "Implement feature X"})
    )

    # 2. A mock devlead claims it
    claim_devlead_res = json.loads(
        jobs.claim_job(ClaimJobArgs(worker_type="devlead", agent_id="devlead-agent-1"))
    )
    assert claim_devlead_res["job"] is not None
    assert claim_devlead_res["job"]["id"] == devlead_job_id

    # 3. Devlead does work, updates status to IN_REVIEW
    res_update_devlead = json.loads(
        jobs.update_job_status(
            UpdateJobStatusArgs(
                job_id=devlead_job_id,
                status=JobStatus.IN_REVIEW,
                result={"pr_link": "https://github.com/mock/pr/1"},
            )
        )
    )
    assert res_update_devlead["status"] == "InReview"

    # 4. Architect submits a qa job
    qa_job_id = jobs.submit_job(
        SubmitJobArgs(worker_type="qa", payload={"pr_link": "https://github.com/mock/pr/1"})
    )

    # 5. A mock qa claims it
    claim_qa_res = json.loads(jobs.claim_job(ClaimJobArgs(worker_type="qa", agent_id="qa-agent-1")))
    assert claim_qa_res["job"] is not None
    assert claim_qa_res["job"]["id"] == qa_job_id

    # 6. QA sends a message
    res_send_msg = json.loads(
        jobs.send_message(
            SendMessageArgs(
                job_id=qa_job_id, sender="qa-agent-1", recipient="architect", content="tests pass"
            )
        )
    )
    assert res_send_msg["status"] == "sent"

    # 7. QA marks it COMPLETED
    res_update_qa = json.loads(
        jobs.update_job_status(
            UpdateJobStatusArgs(
                job_id=qa_job_id, status=JobStatus.COMPLETED, result={"status": "approved"}
            )
        )
    )
    assert res_update_qa["status"] == "Completed"

    # 8. Verify the final states
    devlead_status = json.loads(jobs.get_job_status(GetJobStatusArgs(job_id=devlead_job_id)))
    assert devlead_status["status"] == "InReview"

    qa_status = json.loads(jobs.get_job_status(GetJobStatusArgs(job_id=qa_job_id)))
    assert qa_status["status"] == "Completed"
