import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    pending    = "pending"
    processing = "processing"
    done       = "done"
    error      = "error"


@dataclass
class Job:
    id:                str
    original_filename: str
    file_bytes:        bytes
    status:            JobStatus = JobStatus.pending
    filename:          str       = ""
    preview_b64:       str       = ""
    error:             str       = ""
    enqueued_at:       datetime  = field(default_factory=datetime.now)


class JobQueue:
    def __init__(self) -> None:
        self._q:    asyncio.Queue[Job] = asyncio.Queue()
        self._jobs: dict[str, Job]     = {}

    def enqueue(self, file_bytes: bytes, original_filename: str) -> Job:
        job = Job(id=str(uuid.uuid4()), original_filename=original_filename, file_bytes=file_bytes)
        self._jobs[job.id] = job
        self._q.put_nowait(job)
        return job

    def get_active(self) -> list[Job]:
        """Return jobs that are still pending or processing (not done/error)."""
        return [j for j in self._jobs.values() if j.status in (JobStatus.pending, JobStatus.processing)]

    async def worker(self) -> None:
        """Background coroutine — consumes one job at a time, forever."""
        from app.pipeline import process_upload  # late import avoids circular dep
        while True:
            job = await self._q.get()
            try:
                job.status = JobStatus.processing
                _, filename, preview_b64 = await process_upload(job.file_bytes, job.original_filename)
                job.filename    = filename
                job.preview_b64 = preview_b64
                job.status      = JobStatus.done
            except Exception as exc:
                job.status = JobStatus.error
                job.error  = str(exc)
            finally:
                job.file_bytes = b""  # free memory immediately
                self._q.task_done()


job_queue = JobQueue()
