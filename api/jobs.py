"""File de calculs pour les traitements longs (CP-SAT, recherche de cadence).

MVP : exécuteur en mémoire (ThreadPoolExecutor ; OR-Tools libère le GIL).
Interface `JobQueue` volontairement minimale pour être remplacée en production
par une file persistante (Redis + arq/RQ, ou table Postgres) sans toucher
aux routes.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Job:
    id: str
    kind: str
    owner: str
    status: str = "queued"  # queued | running | done | failed
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[dict[str, Any]] = None
    error: str = ""


class JobQueue:
    def __init__(self, workers: int = 2, max_jobs: int = 1000) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="tlb-job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_jobs = max_jobs

    def submit(self, kind: str, owner: str, fn: Callable[[], dict[str, Any]]) -> Job:
        job = Job(id=uuid.uuid4().hex, kind=kind, owner=owner)
        with self._lock:
            self._evict()
            self._jobs[job.id] = job
        self._pool.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: Callable[[], dict[str, Any]]) -> None:
        job.status, job.started_at = "running", time.time()
        try:
            job.result = fn()
            job.status = "done"
        except Exception as e:  # noqa: BLE001 — remonté au client
            job.status, job.error = "failed", str(e)
        finally:
            job.finished_at = time.time()

    def get(self, job_id: str, owner: str) -> Optional[Job]:
        job = self._jobs.get(job_id)
        return job if job and job.owner == owner else None

    def _evict(self) -> None:
        if len(self._jobs) < self._max_jobs:
            return
        finished = sorted((j for j in self._jobs.values() if j.finished_at), key=lambda j: j.finished_at)
        for j in finished[: max(1, len(finished) // 2)]:
            self._jobs.pop(j.id, None)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
