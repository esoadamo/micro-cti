import sys
import asyncio
from os import environ
from datetime import datetime, timezone as tz
from pathlib import Path

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


async def run_job(job_name: str) -> int:
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
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            line = f"[{datetime.now(tz=tz.utc).isoformat()}] [{job_name}] ".encode() + line
            f.write(line.strip() + b'\n')
            f.flush()
            print(line.decode('utf-8', errors='replace').rstrip())
        stderr = await process.stderr.read()
        if stderr:
            f.write(b"[ERROR] " + stderr)
            f.flush()
        code = await process.wait()
        line = f"[{datetime.now(tz=tz.utc).isoformat()}] [{job_name}] Job {job_name} finished with code {code}\n".encode()
        f.write(line)
        f.flush()
        print(line.decode('utf-8', errors='replace').rstrip())
    return code


async def run_scheduled_jobs() -> int:
    jobs_to_run = []
    now = datetime.now(tz=tz.utc).timestamp()
    for job_name, interval in JOBS.items():
        last_run = TABLE_LAST_RUN.get(job_name, 0)
        if now - last_run >= interval:
            TABLE_LAST_RUN[job_name] = now
            jobs_to_run.append(run_job(job_name))
    results = await asyncio.gather(*jobs_to_run)
    return sum(results)


async def main() -> None:
    while True:
        code = await run_scheduled_jobs()
        if code != 0:
            print(f"[!] Some jobs failed with code {code}, check logs for details")
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
