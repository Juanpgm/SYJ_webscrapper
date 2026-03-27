from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    kind: str
    status: JobStatus
    created_at: datetime
    params: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "params": self.params,
            "stats": self.stats,
            "error": self.error,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, kind: str, params: dict[str, Any]) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            kind=kind,
            status=JobStatus.PENDING,
            created_at=datetime.now(),
            params=params,
        )
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return list(reversed(list(self._jobs.values())))

    def update(self, job: Job) -> None:
        self._jobs[job.id] = job


job_store = JobStore()
