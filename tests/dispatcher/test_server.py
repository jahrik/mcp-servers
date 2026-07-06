import json
import sqlite3
import subprocess
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcp_servers.dispatcher import server


@pytest.fixture
def mock_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test_dispatcher.db"
    monkeypatch.setenv("MCP_DISPATCHER_DB_PATH", str(db_path))
    return db_path


@pytest.fixture
def mock_subprocess() -> Generator[MagicMock, None, None]:
    with patch("mcp_servers.dispatcher.server.subprocess.Popen") as mock_popen:
        yield mock_popen


@pytest.mark.parametrize("allow_val", ["true", "1", "TRUE", "True"])
def test_submit_job(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch, allow_val: str
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", allow_val)

    # Test submission
    job_id = server.submit_job(
        server.SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"})
    )

    # Assert subprocess was called
    mock_subprocess.assert_called_once()
    args, kwargs = mock_subprocess.call_args
    assert args[0][0] == "agy"
    assert args[0][1].startswith("--print=You are a background worker")
    assert "Read your AGY_WORKER_TYPE and AGY_JOB_ID" in args[0][1]
    assert "get_job_status tool" in args[0][1]
    assert kwargs.get("start_new_session") is True
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
    job_id = server.submit_job(
        server.SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"})
    )

    status_str = server.get_job_status(server.GetJobStatusArgs(job_id=job_id))
    status = json.loads(status_str)

    assert status["id"] == job_id
    assert status["status"] == "Running"
    assert status["worker_type"] == "test_worker"
    assert status["payload"] == {"foo": "bar"}


def test_get_job_status_not_found(mock_db: Path) -> None:
    status_str = server.get_job_status(
        server.GetJobStatusArgs(job_id="00000000-0000-0000-0000-000000000000")
    )
    status = json.loads(status_str)
    assert "error" in status


def test_get_job_status_invalid_json(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "1")
    job_id = server.submit_job(
        server.SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"})
    )
    # Corrupt the JSON in the DB
    with sqlite3.connect(mock_db) as conn:
        conn.execute("UPDATE jobs SET payload = ? WHERE id = ?", ("{bad json", job_id))
        conn.commit()

    status_str = server.get_job_status(server.GetJobStatusArgs(job_id=job_id))
    status = json.loads(status_str)
    assert status["payload"] == {"error": "Invalid JSON in database"}


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
        server.submit_job(server.SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"}))


def test_submit_job_non_serializable_payload(
    mock_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
    with pytest.raises(ValueError, match="Payload must be JSON-serializable"):
        server.submit_job(
            server.SubmitJobArgs(worker_type="test_worker", payload={"foo": object()})
        )


def test_submit_job_subprocess_exception(
    mock_db: Path, mock_subprocess: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_DISPATCHER_ALLOW_SPAWN", "true")
    mock_subprocess.side_effect = Exception("Popen failed")

    with pytest.raises(Exception, match="Popen failed"):
        server.submit_job(server.SubmitJobArgs(worker_type="test_worker", payload={"foo": "bar"}))

    # Assert DB state is updated to Failed
    with sqlite3.connect(mock_db) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs")
        row = cursor.fetchone()

    assert row is not None
    assert row["status"] == "Failed"
