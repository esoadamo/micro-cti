import sys
import asyncio
from os import environ
from datetime import datetime, timezone as tz
from pathlib import Path
from typing import Set
from threading import Thread

from dictature import Dictature
from dictature.backend import DictatureBackendSQLite


JOBS = {
    "cache-expire":  3600,
    "data-export": 24*3600,
    "filter-tags": 24*3600,
    "ingest": 3600,
    "tag": 24*3600
}


DIR_LOGS = Path(environ.get("UCTI_LOG_DIR", f"{(Path(__file__).parent / 'logs').resolve()}"))
DIR_DATA = Path(environ.get("UCTI_DATA_DIR", f"{(Path(__file__).parent / "data").resolve()}"))
DIR_DATA.mkdir(parents=True, exist_ok=True)
DIR_LOGS.mkdir(parents=True, exist_ok=True)
STORAGE = Dictature(DictatureBackendSQLite(DIR_DATA / "jobber.sqlite"))
TABLE_LAST_RUN = STORAGE["job_last_run"]
JOBS_RUNNING: Set[str] = set()


async def run_job(job_name: str) -> int:
    JOBS_RUNNING.add(job_name)
    file_log = DIR_LOGS / f"job-{job_name}.log"
    process = await asyncio.create_subprocess_exec(
        sys.executable, f"{Path(__file__).parent / f"job-{job_name}.py"}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE,
        env={**environ, "PYTHONUNBUFFERED": "1"},
    )
    process.stdin.close()
    with open(file_log, 'ab') as f:
        line = f"[{datetime.now(tz=tz.utc).isoformat()}] [{job_name}] Starting job {job_name}\n".encode()
        f.write(line)
        f.flush()
        print(line.decode('utf-8', errors='replace').rstrip())

        # Buffer for incomplete lines
        buffer = b''

        while True:
            try:
                # Read data in chunks instead of using readline()
                chunk = await process.stdout.read(8192)  # 8KB chunks
                if not chunk:
                    # Process any remaining data in buffer
                    if buffer:
                        line = f"[{datetime.now(tz=tz.utc).isoformat()}] [{job_name}] ".encode() + buffer
                        f.write(line.strip() + b'\n')
                        f.flush()
                        print(line.decode('utf-8', errors='replace').rstrip())
                    break

                # Add chunk to buffer
                buffer += chunk

                # Process complete lines from buffer
                while b'\n' in buffer:
                    line_data, buffer = buffer.split(b'\n', 1)
                    line = f"[{datetime.now(tz=tz.utc).isoformat()}] [{job_name}] ".encode() + line_data
                    f.write(line.strip() + b'\n')
                    f.flush()
                    print(line.decode('utf-8', errors='replace').rstrip())

                # If buffer gets too large without a newline (>1MB), force flush it
                if len(buffer) > 1024 * 1024:
                    line = f"[{datetime.now(tz=tz.utc).isoformat()}] [{job_name}] ".encode() + buffer
                    f.write(line.strip() + b'\n')
                    f.flush()
                    print(line.decode('utf-8', errors='replace').rstrip())
                    buffer = b''

            except Exception as e:
                # Log any read errors and continue
                error_line = f"[{datetime.now(tz=tz.utc).isoformat()}] [{job_name}] [ERROR] Read error: {str(e)}\n".encode()
                f.write(error_line)
                f.flush()
                print(error_line.decode('utf-8', errors='replace').rstrip())
                break

        stderr = await process.stderr.read()
        if stderr:
            f.write(b"[ERROR] " + stderr)
            f.flush()
        code = await process.wait()
        line = f"[{datetime.now(tz=tz.utc).isoformat()}] [{job_name}] Job {job_name} finished with code {code}\n".encode()
        f.write(line)
        f.flush()
        print(line.decode('utf-8', errors='replace').rstrip())
    TABLE_LAST_RUN[job_name] = datetime.now(tz=tz.utc).timestamp()
    JOBS_RUNNING.remove(job_name)
    return code


async def main() -> None:
    while True:
        now = datetime.now(tz=tz.utc).timestamp()
        for job_name, interval in JOBS.items():
            last_run = TABLE_LAST_RUN.get(job_name, 0)
            if now - last_run >= interval and job_name not in JOBS_RUNNING:
                TABLE_LAST_RUN[job_name] = now
                Thread(target=asyncio.run, args=(run_job(job_name),), daemon=True).start()
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
