"""Gestor de trabajos en memoria para un único usuario local.

Un ThreadPoolExecutor ejecuta el pipeline fuera del bucle de eventos HTTP. La cancelación es
cooperativa: se comprueba entre etapas y entre candidatos (una llamada a VTracer en curso no se
puede interrumpir). Los archivos de trabajos cancelados o fallidos se eliminan.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.errors import JobCancelledError, JobNotFoundError, VectorLabError
from app.preprocessing.decode import EXTENSIONS, probe
from app.schemas import JobState, VectorizeParams
from app.services.pipeline import PipelineRunner
from app.storage.files import JobStorage
from app.vectorization.base import VectorizerEngine

log = logging.getLogger("vectorlab.jobs")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass
class Job:
    id: str
    params: VectorizeParams
    input_info: dict[str, Any]
    state: JobState = JobState.queued
    stage: str = "en cola"
    progress: float = 0.0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    created_ts: float = field(default_factory=time.time)
    warnings: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    report: dict[str, Any] | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None


class JobManager:
    def __init__(self, settings: Settings, engine: VectorizerEngine) -> None:
        self.settings = settings
        self.storage = JobStorage(settings.data_dir)
        self.runner = PipelineRunner(settings, engine)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=settings.worker_threads, thread_name_prefix="vectorlab")

    # -- ciclo de vida ---------------------------------------------------------------------
    def submit(self, data: bytes, params: VectorizeParams) -> Job:
        fmt, width, height = probe(data, self.settings)  # rechaza entradas inválidas antes de crear el trabajo
        self.cleanup()
        job_id = uuid.uuid4().hex
        self.storage.create(job_id)
        self.storage.save_original(job_id, data, EXTENSIONS[fmt])
        job = Job(id=job_id, params=params,
                  input_info={"format": fmt, "width": width, "height": height, "bytes": len(data)})
        with self._lock:
            self._jobs[job_id] = job
        job.future = self._pool.submit(self._execute, job, data)
        log.info("trabajo %s en cola (%s %dx%d, %d bytes)", job_id, fmt, width, height, len(data))
        return job

    def _execute(self, job: Job, data: bytes) -> None:
        if job.cancel_event.is_set():
            self._finish_cancelled(job)
            return
        self._update(job, state=JobState.running, stage="iniciando", progress=1)
        workdir = self.storage.job_dir(job.id)
        try:
            report = self.runner.run(data, job.params, workdir,
                                     lambda stage, pct: self._update(job, stage=stage, progress=pct),
                                     job.cancel_event)
        except JobCancelledError:
            self._finish_cancelled(job)
        except VectorLabError as exc:
            log.warning("trabajo %s falló: %s", job.id, exc.code)
            self._update(job, state=JobState.failed, stage="error", error=exc.to_dict())
        except Exception as exc:  # noqa: BLE001 - se registra y se expone como error interno
            log.exception("trabajo %s: error inesperado", job.id)
            self._update(job, state=JobState.failed, stage="error",
                         error={"code": "internal_error", "message": f"Error interno: {type(exc).__name__}",
                                "details": {}})
        else:
            self._update(job, state=JobState.completed, stage="completado", progress=100, report=report,
                         warnings=report["warnings"])

    def _finish_cancelled(self, job: Job) -> None:
        # Primero se borran los archivos: quien vea el estado «cancelado» no debe encontrarlos.
        self.storage.delete(job.id)
        self._update(job, state=JobState.cancelled, stage="cancelado")
        log.info("trabajo %s cancelado; archivos eliminados", job.id)

    def _update(self, job: Job, **changes: Any) -> None:
        with self._lock:
            for k, v in changes.items():
                setattr(job, k, v)
            job.updated_at = _now()

    # -- consultas ---------------------------------------------------------------------------
    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError("El trabajo no existe o ya fue eliminado.")
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.state in (JobState.queued, JobState.running):
            job.cancel_event.set()
            if job.future is not None and job.future.cancel():  # aún no había empezado
                self._finish_cancelled(job)
        return job

    def cleanup(self) -> None:
        ttl = self.settings.job_ttl_hours * 3600
        now = time.time()
        with self._lock:
            finished = [j for j in self._jobs.values()
                        if j.state not in (JobState.queued, JobState.running)]
            expired = {j.id for j in finished if now - j.created_ts > ttl}
            overflow = sorted(finished, key=lambda j: j.created_ts)
            excess = len(self._jobs) - self.settings.max_retained_jobs + 1
            if excess > 0:
                expired |= {j.id for j in overflow[:excess]}
            for jid in expired:
                self._jobs.pop(jid, None)
            active = set(self._jobs)
        for jid in expired:
            self.storage.delete(jid)
        self.storage.purge_older_than(ttl, keep=active)

    def shutdown(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel_event.set()
        self._pool.shutdown(wait=True, cancel_futures=True)
