from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from jobber import JOBS, run_job, JOBS_RUNNING


def test_jobs_schedules_configured():
    assert "cache-expire" in JOBS
    assert "data-export" in JOBS
    assert "filter-tags" in JOBS
    assert "ingest" in JOBS
    assert "tag" in JOBS
    assert JOBS["cache-expire"] == 3600
    assert JOBS["ingest"] == 3600


@pytest.mark.asyncio
async def test_run_job_execution(tmp_path):
    mock_process = MagicMock()
    mock_process.stdin = MagicMock()

    # Emulate chunks of stdout
    mock_process.stdout.read = AsyncMock(side_effect=[b"Step 1 completed\nStep 2 completed\n", b""])
    mock_process.stderr.read = AsyncMock(return_value=b"")
    mock_process.wait = AsyncMock(return_value=0)

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    with patch("jobber.DIR_LOGS", log_dir), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)), \
         patch("jobber.TABLE_LAST_RUN", {}):
        exit_code = await run_job("ingest")

    assert exit_code == 0
    assert "ingest" not in JOBS_RUNNING
    log_file = log_dir / "job-ingest.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "Starting job ingest" in content
    assert "Step 1 completed" in content
    assert "Job ingest finished with code 0" in content
