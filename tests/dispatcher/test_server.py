import json
import sqlite3
import subprocess
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcp_servers.dispatcher import server
from mcp_servers.dispatcher.models.schemas import (
    CleanupJobsArgs,
    GetJobStatusArgs,
    JobStatus,
    ListJobsArgs,
    SubmitJobArgs,
    UpdateJobStatusArgs,
)
from mcp_servers.dispatcher.tools import jobs


@pytest.fixture
def mock_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test_dispatcher.db"
    monkeypatch.setenv("MCP_DISPATCHER_DB_PATH", str(db_path))
    return db_path


@pytest.fixture
def mock_subprocess() -> Generator[MagicMock, None, None]:
    with patch("mcp_servers.dispatcher.tools.jobs.subprocess.Popen") as mock_popen:
        yield mock_popen


@pytest.mark.parametrize("allow_val", ["true", "1", "TRUE", "True"])
def test_submit_job(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch, allow_val: str
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", allow_val)

    # Test submission
    job_id = jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"}))

    # Assert subprocess was called
    mock_subprocess.assert_called_once()
    args, kwargs = mock_subprocess.call_args
    assert args[0][0] == "agy"
    assert args[0][1].startswith("--print=You are a background worker")
    assert "Read your AGY_WORKER_TYPE and AGY_JOB_ID" in args[0][1]
    assert "get_job_status tool" in args[0][1]
    assert kwargs.get("start_new_session") is True
    # stdin must be detached (DEVNULL): inheriting the server's stdio JSON-RPC
    # pipe makes `agy --print` block on a never-EOF stdin and hang forever.
    assert kwargs.get("stdin") == subprocess.DEVNULL
    assert kwargs.get("stdout") == subprocess.DEVNULL
    assert kwargs.get("stderr") == subprocess.DEVNULL

    assert "env" in kwargs
    assert kwargs["env"]["AGY_JOB_ID"] == job_id
    assert kwargs["env"]["AGY_WORKER_TYPE"] == "test_worker"
    assert kwargs["env"]["MCP_DISPATCHER_DB_PATH"] == str(mock_db)

    # Assert DB state
    with sqlite3.connect(mock_db) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()

    assert row is not None
    assert row["status"] == "Running"
    assert row["worker_type"] == "test_worker"
    assert row["payload"] == '{"foo": "bar"}'


def test_get_job_status(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
    job_id = jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"}))

    status_str = jobs.get_job_status(GetJobStatusArgs(job_id=job_id))
    status = json.loads(status_str)

    assert status["id"] == job_id
    assert status["status"] == "Running"
    assert status["worker_type"] == "test_worker"
    assert status["payload"] == {"foo": "bar"}


def test_get_job_status_not_found(mock_db: Path) -> None:
    status_str = jobs.get_job_status(
        GetJobStatusArgs(job_id="00000000-0000-0000-0000-000000000000")
    )
    status = json.loads(status_str)
    assert "error" in status


def test_get_job_status_invalid_json(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "1")
    job_id = jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"}))
    # Corrupt the JSON in the DB
    with sqlite3.connect(mock_db) as conn:
        conn.execute("UPDATE jobs SET payload = ? WHERE id = ?", ("{bad json", job_id))
        conn.commit()

    status_str = jobs.get_job_status(GetJobStatusArgs(job_id=job_id))
    status = json.loads(status_str)
    assert status["payload"] == {"error": "Invalid JSON in database"}


def test_submit_job_stamps_timestamps(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
    job_id = jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={}))

    status = json.loads(jobs.get_job_status(GetJobStatusArgs(job_id=job_id)))
    assert status["created_at"] is not None
    # A brand-new job hasn't been updated since creation.
    assert status["updated_at"] == status["created_at"]


def test_update_job_status(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
    job_id = jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"k": "v"}))

    res = json.loads(
        jobs.update_job_status(UpdateJobStatusArgs(job_id=job_id, status=JobStatus.COMPLETED))
    )
    assert res["status"] == "Completed"
    assert res["payload"] == {"k": "v"}
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


def test_submit_job_spawn_not_allowed(mock_db: Path) -> None:
    with pytest.raises(RuntimeError, match="Spawning is not allowed"):
        jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"}))


def test_submit_job_non_serializable_payload(
    mock_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
    with pytest.raises(ValueError, match="Payload must be JSON-serializable"):
        jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"foo": object()}))


def test_submit_job_subprocess_exception(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
    mock_subprocess.side_effect = Exception("Popen failed")

    with pytest.raises(Exception, match="Popen failed"):
        jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"}))

    # Assert DB state is updated to Failed
    with sqlite3.connect(mock_db) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs")
        row = cursor.fetchone()

    assert row is not None
    assert row["status"] == "Failed"


def test_update_job_status_terminal_is_immutable(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
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


def test_submit_job_rejects_oversized_payload(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
    oversized = {"blob": "x" * (jobs.MAX_PAYLOAD_BYTES + 1)}
    with pytest.raises(ValueError, match="exceeds the"):
        jobs.submit_job(SubmitJobArgs(worker_type="test_worker", payload=oversized))

    # Rejected before the DB is even touched — nothing persisted or spawned.
    mock_subprocess.assert_not_called()
    assert not mock_db.exists()


def test_submit_job_rejects_overlong_worker_type() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SubmitJobArgs(worker_type="a" * 257, payload={})


def test_connections_are_closed(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every SQLite connection the tools open must be closed (no fd leak)."""
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")

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


def test_list_jobs_newest_first(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")

    job_id1 = jobs.submit_job(SubmitJobArgs(worker_type="worker1", payload={}))
    time.sleep(0.01)
    job_id2 = jobs.submit_job(SubmitJobArgs(worker_type="worker2", payload={}))

    res = json.loads(jobs.list_jobs(ListJobsArgs()))

    assert len(res) == 2
    assert res[0]["id"] == job_id2
    assert res[1]["id"] == job_id1
    assert "payload" not in res[0]
    assert res[0]["worker_type"] == "worker2"
    assert res[1]["worker_type"] == "worker1"


def test_list_jobs_status_filter(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")

    job_id1 = jobs.submit_job(SubmitJobArgs(worker_type="worker1", payload={}))
    job_id2 = jobs.submit_job(SubmitJobArgs(worker_type="worker2", payload={}))
    jobs.update_job_status(UpdateJobStatusArgs(job_id=job_id1, status=JobStatus.COMPLETED))

    res = json.loads(jobs.list_jobs(ListJobsArgs(status=JobStatus.COMPLETED)))
    assert len(res) == 1
    assert res[0]["id"] == job_id1

    res = json.loads(jobs.list_jobs(ListJobsArgs(status=JobStatus.RUNNING)))
    assert len(res) == 1
    assert res[0]["id"] == job_id2


def test_list_jobs_limit(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")

    for i in range(5):
        jobs.submit_job(SubmitJobArgs(worker_type=f"worker{i}", payload={}))

    res = json.loads(jobs.list_jobs(ListJobsArgs(limit=3)))
    assert len(res) == 3


def test_cleanup_jobs_removes_only_terminal(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
    monkeypatch.setenv("MCP_DISPATCHER_MAX_RUNNING", "10")

    j1 = jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))
    j2 = jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))
    j3 = jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))
    jobs.update_job_status(UpdateJobStatusArgs(job_id=j1, status=JobStatus.COMPLETED))
    jobs.update_job_status(UpdateJobStatusArgs(job_id=j2, status=JobStatus.FAILED))

    res = json.loads(jobs.cleanup_jobs(CleanupJobsArgs()))
    assert res["deleted"] == 2

    # The still-Running job survives.
    remaining = json.loads(jobs.list_jobs(ListJobsArgs()))
    assert [r["id"] for r in remaining] == [j3]


def test_cleanup_jobs_older_than_keeps_fresh(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
    j1 = jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))
    jobs.update_job_status(UpdateJobStatusArgs(job_id=j1, status=JobStatus.COMPLETED))

    # A just-completed job is younger than a day, so nothing is pruned.
    assert json.loads(jobs.cleanup_jobs(CleanupJobsArgs(older_than_days=1)))["deleted"] == 0
    # Without the age filter it is removed.
    assert json.loads(jobs.cleanup_jobs(CleanupJobsArgs()))["deleted"] == 1


def test_submit_job_respects_max_running(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
    monkeypatch.setenv("MCP_DISPATCHER_MAX_RUNNING", "2")

    j1 = jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))
    jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))

    # Third submit exceeds the cap and is refused before spawning.
    with pytest.raises(RuntimeError, match="Too many jobs in flight"):
        jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))

    # Finishing a job frees a slot.
    jobs.update_job_status(UpdateJobStatusArgs(job_id=j1, status=JobStatus.COMPLETED))
    jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))  # no raise


def test_reap_children_drops_finished(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
    # A finished worker reports an exit code from poll().
    mock_subprocess.return_value.poll.return_value = 0

    jobs._children.clear()
    jobs.submit_job(SubmitJobArgs(worker_type="w", payload={}))
    assert len(jobs._children) == 1  # tracked after spawn

    jobs._reap_children()
    assert jobs._children == []  # finished child reaped


@pytest.mark.parametrize("raw", ["not-an-int", "0", "-3"])
def test_max_running_falls_back_to_default(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # A non-numeric or non-positive override is ignored in favour of the default.
    monkeypatch.setenv("MCP_DISPATCHER_MAX_RUNNING", raw)
    assert jobs._max_running() == jobs._DEFAULT_MAX_RUNNING
