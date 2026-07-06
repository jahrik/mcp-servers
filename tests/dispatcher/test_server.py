import json
import sqlite3
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcp_servers.dispatcher import server


@pytest.fixture
def mock_db(tmp_path: Path) -> Generator[Path, None, None]:
    db_path = tmp_path / "test_dispatcher.db"
    with patch("mcp_servers.dispatcher.server.DB_PATH", db_path):
        yield db_path


@pytest.fixture
def mock_subprocess() -> Generator[MagicMock, None, None]:
    with patch("mcp_servers.dispatcher.server.subprocess.Popen") as mock_popen:
        yield mock_popen


def test_submit_job(mock_db: Path, mock_subprocess: MagicMock) -> None:
    # Test submission
    job_id = server.submit_job("test_worker", '{"foo": "bar"}')

    # Assert subprocess was called
    mock_subprocess.assert_called_once()
    args, kwargs = mock_subprocess.call_args
    assert args[0] == ["agy", '--print={"foo": "bar"}']
    assert kwargs.get("start_new_session") is True
    assert "env" in kwargs
    assert kwargs["env"]["AGY_JOB_ID"] == job_id
    assert kwargs["env"]["AGY_WORKER_TYPE"] == "test_worker"

    # Assert DB state
    with sqlite3.connect(mock_db) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()

    assert row is not None
    assert row["status"] == "Running"
    assert row["worker_type"] == "test_worker"
    assert row["payload"] == '{"foo": "bar"}'


def test_get_job_status(mock_db: Path, mock_subprocess: MagicMock) -> None:
    job_id = server.submit_job("test_worker", '{"foo": "bar"}')

    status_str = server.get_job_status(job_id)
    status = json.loads(status_str)

    assert status["id"] == job_id
    assert status["status"] == "Running"
    assert status["worker_type"] == "test_worker"
    assert status["payload"] == '{"foo": "bar"}'


def test_get_job_status_not_found(mock_db: Path) -> None:
    status_str = server.get_job_status("nonexistent")
    status = json.loads(status_str)
    assert "error" in status


def test_server_main(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def mock_run() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(server.mcp, "run", mock_run)
    server.main()
    assert called
