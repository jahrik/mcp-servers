from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mcp_servers.dispatcher import server
from mcp_servers.dispatcher.models.schemas import (
    ClaimJobArgs,
    CleanupJobsArgs,
    GetJobStatusArgs,
    GetMessagesArgs,
    JobStatus,
    ListJobsArgs,
    SendMessageArgs,
    SubmitJobArgs,
    UpdateJobStatusArgs,
)
from mcp_servers.dispatcher.tools import jobs


@pytest.fixture
def mock_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test_dispatcher.db"
    monkeypatch.setenv("MCP_DISPATCHER_DB_PATH", str(db_path))
    return db_path


def test_submit_job(mock_db: Path) -> None:
    job_id = jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"}))

    with sqlite3.connect(mock_db) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()

    assert row is not None
    assert row["status"] == "Queued"
    assert row["worker_type"] == "test_worker"
    assert row["payload"] == '{"foo": "bar"}'


def test_claim_job(mock_db: Path) -> None:
    job_id1 = jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"job": 1}))
    jobs.submit_job(SubmitJobArgs(worker_type="other_worker", payload={"job": 2}))

    res_str = jobs.claim_job(ClaimJobArgs(worker_type="test_worker", agent_id="agent-1"))
    res = json.loads(res_str)

    assert res["job"] is not None
    assert res["job"]["id"] == job_id1
    assert res["job"]["status"] == "Running"
    assert res["job"]["claimed_by"] == "agent-1"

    # Next claim for test_worker should find nothing
    res_str2 = jobs.claim_job(ClaimJobArgs(worker_type="test_worker", agent_id="agent-1"))
    res2 = json.loads(res_str2)
    assert res2["job"] is None


def test_get_job_status(mock_db: Path) -> None:
    job_id = jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"}))

    status_str = jobs.get_job_status(GetJobStatusArgs(job_id=job_id))
    status = json.loads(status_str)

    assert status["id"] == job_id
    assert status["status"] == "Queued"
    assert status["worker_type"] == "test_worker"
    assert status["payload"] == {"foo": "bar"}


def test_get_job_status_not_found(mock_db: Path) -> None:
    status_str = jobs.get_job_status(
        GetJobStatusArgs(job_id="00000000-0000-0000-0000-000000000000")
    )
    status = json.loads(status_str)
    assert "error" in status


def test_get_job_status_invalid_json(mock_db: Path) -> None:
    job_id = jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"}))
    with sqlite3.connect(mock_db) as conn:
        conn.execute("UPDATE jobs SET payload = ? WHERE id = ?", ("{bad json", job_id))
        conn.commit()

    status_str = jobs.get_job_status(GetJobStatusArgs(job_id=job_id))
    status = json.loads(status_str)
    assert status["payload"] == {"error": "Invalid JSON in database"}


def test_submit_job_stamps_timestamps(mock_db: Path) -> None:
    job_id = jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={}))

    status = json.loads(jobs.get_job_status(GetJobStatusArgs(job_id=job_id)))
    assert status["created_at"] is not None
    assert status["updated_at"] == status["created_at"]


def test_update_job_status(mock_db: Path) -> None:
    job_id = jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"k": "v"}))
    jobs.claim_job(ClaimJobArgs(worker_type="test_worker", agent_id="agent-1"))

    res = json.loads(
        jobs.update_job_status(
            UpdateJobStatusArgs(job_id=job_id, status=JobStatus.COMPLETED, result={"ans": 42})
        )
    )
    assert res["status"] == "Completed"
    assert res["payload"] == {"k": "v"}
    assert res["result"] == {"ans": 42}
    assert res["updated_at"] is not None


def test_update_job_status_not_found(mock_db: Path) -> None:
    res = json.loads(
        jobs.update_job_status(
            UpdateJobStatusArgs(
                job_id="00000000-0000-0000-0000-000000000000", status=JobStatus.FAILED
            )
        )
    )
    assert "error" in res


def test_update_job_status_rejects_unknown_status() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        UpdateJobStatusArgs(
            job_id="00000000-0000-0000-0000-000000000000",
            status="Bogus",  # ty: ignore[invalid-argument-type]
        )


def test_server_main(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def mock_run() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(server.mcp, "run", mock_run)
    server.main()
    assert called


def test_submit_job_non_serializable_payload(mock_db: Path) -> None:
    with pytest.raises(ValueError, match="Payload must be JSON-serializable"):
        jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"foo": object()}))


def test_update_job_status_terminal_is_immutable(mock_db: Path) -> None:
    job_id = jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={}))

    # First move to a terminal state.
    jobs.update_job_status(UpdateJobStatusArgs(job_id=job_id, status=JobStatus.COMPLETED))

    # Any further transition is rejected and the status stays terminal.
    res = json.loads(
        jobs.update_job_status(UpdateJobStatusArgs(job_id=job_id, status=JobStatus.RUNNING))
    )
    assert "error" in res
    assert "terminal" in res["error"]

    status = json.loads(jobs.get_job_status(GetJobStatusArgs(job_id=job_id)))
    assert status["status"] == "Completed"


def test_submit_job_rejects_oversized_payload(mock_db: Path) -> None:
    oversized = {"blob": "x" * (jobs.MAX_PAYLOAD_BYTES + 1)}
    with pytest.raises(ValueError, match="exceeds the"):
        jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload=oversized))
    assert not mock_db.exists()


def test_submit_job_rejects_overlong_worker_type() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SubmitJobArgs(worker_type="a" * 257, payload={})


def test_connections_are_closed(mock_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every SQLite connection the tools open must be closed (no fd leak)."""

    real_connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []

    def tracking_connect(database: str | Path) -> sqlite3.Connection:
        conn = real_connect(database)
        opened.append(conn)
        return conn

    monkeypatch.setattr(jobs.sqlite3, "connect", tracking_connect)

    jid = jobs.submit_job(SubmitJobArgs(worker_type="w", payload={"n": 1}))
    jobs.get_job_status(GetJobStatusArgs(job_id=jid))
    jobs.update_job_status(UpdateJobStatusArgs(job_id=jid, status=JobStatus.COMPLETED))

    assert opened, "expected the tools to open at least one connection"
    # A closed sqlite3 connection raises ProgrammingError when used again.
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_list_jobs_newest_first(mock_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Monkeypatch _now to return deterministic, ordered timestamps
    counter = 0

    def mock_now() -> str:
        nonlocal counter
        counter += 1
        return f"2026-01-01T00:00:0{counter}Z"

    monkeypatch.setattr(jobs, "_now", mock_now)

    job_id1 = jobs.submit_job(SubmitJobArgs(worker_type="worker1", payload={}))
    job_id2 = jobs.submit_job(SubmitJobArgs(worker_type="worker2", payload={}))

    res = json.loads(jobs.list_jobs(ListJobsArgs()))

    assert len(res) == 2
    assert res[0]["id"] == job_id2
    assert res[1]["id"] == job_id1
    assert "payload" not in res[0]
    assert res[0]["worker_type"] == "worker2"
    assert res[1]["worker_type"] == "worker1"


def test_list_jobs_status_filter(mock_db: Path) -> None:
    job_id1 = jobs.submit_job(SubmitJobArgs(worker_type="worker1", payload={}))
    job_id2 = jobs.submit_job(SubmitJobArgs(worker_type="worker2", payload={}))
    jobs.update_job_status(UpdateJobStatusArgs(job_id=job_id1, status=JobStatus.COMPLETED))

    res = json.loads(jobs.list_jobs(ListJobsArgs(status=JobStatus.COMPLETED)))
    assert len(res) == 1
    assert res[0]["id"] == job_id1

    res = json.loads(jobs.list_jobs(ListJobsArgs(status=JobStatus.QUEUED)))
    assert len(res) == 1
    assert res[0]["id"] == job_id2


def test_list_jobs_limit(mock_db: Path) -> None:
    for i in range(5):
        jobs.submit_job(SubmitJobArgs(worker_type=f"worker{i}", payload={}))

    res = json.loads(jobs.list_jobs(ListJobsArgs(limit=3)))
    assert len(res) == 3


def test_cleanup_jobs_removes_only_terminal(mock_db: Path) -> None:
    j1 = jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))
    j2 = jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))
    j3 = jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))
    jobs.update_job_status(UpdateJobStatusArgs(job_id=j1, status=JobStatus.COMPLETED))
    jobs.update_job_status(UpdateJobStatusArgs(job_id=j2, status=JobStatus.FAILED))

    res = json.loads(jobs.cleanup_jobs(CleanupJobsArgs()))
    assert res["deleted"] == 2

    # The still-Queued job survives.
    remaining = json.loads(jobs.list_jobs(ListJobsArgs()))
    assert [r["id"] for r in remaining] == [j3]


def test_cleanup_jobs_older_than_keeps_fresh(mock_db: Path) -> None:
    j1 = jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))
    jobs.update_job_status(UpdateJobStatusArgs(job_id=j1, status=JobStatus.COMPLETED))

    # A just-completed job is younger than a day, so nothing is pruned.
    assert json.loads(jobs.cleanup_jobs(CleanupJobsArgs(older_than_days=1)))["deleted"] == 0
    # Without the age filter it is removed.
    assert json.loads(jobs.cleanup_jobs(CleanupJobsArgs()))["deleted"] == 1


def test_send_and_get_messages(mock_db: Path) -> None:
    job_id = jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))

    # Send a message
    res = json.loads(
        jobs.send_message(
            SendMessageArgs(job_id=job_id, sender="claude", recipient="qa", content="Hello world")
        )
    )
    assert res["status"] == "sent"

    # Get messages
    msgs = json.loads(jobs.get_messages(GetMessagesArgs(job_id=job_id)))
    assert len(msgs) == 1
    assert msgs[0]["sender"] == "claude"
    assert msgs[0]["recipient"] == "qa"
    assert msgs[0]["content"] == "Hello world"
    assert msgs[0]["job_id"] == job_id
