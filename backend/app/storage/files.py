"""Almacenamiento de trabajos en disco con rutas controladas.

Cada trabajo vive en <data_dir>/<uuid hex>/. Los nombres de archivo nunca proceden del usuario:
solo se admiten los artefactos conocidos y los identificadores de candidato validados.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import time
from pathlib import Path

from app.errors import JobNotFoundError

_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_CANDIDATE_ID = re.compile(r"^[a-z]+_[a-z]+$")
ARTIFACTS = {"result.svg", "preview.png", "preprocessed.png", "report.json"}


class JobStorage:
    def __init__(self, base_dir: Path) -> None:
        self.base = base_dir.resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        if not _JOB_ID.match(job_id):
            raise JobNotFoundError("Identificador de trabajo no válido.")
        path = (self.base / job_id).resolve()
        if path.parent != self.base:
            raise JobNotFoundError("Identificador de trabajo no válido.")
        return path

    def create(self, job_id: str) -> Path:
        path = self.job_dir(job_id)
        (path / "candidates").mkdir(parents=True, exist_ok=False)
        return path

    def save_original(self, job_id: str, data: bytes, ext: str) -> Path:
        if ext not in {"png", "jpg", "webp"}:
            raise ValueError("extensión no permitida")
        path = self.job_dir(job_id) / f"original.{ext}"
        path.write_bytes(data)
        os.chmod(path, stat.S_IRUSR | stat.S_IRGRP)  # copia inmutable (solo lectura)
        return path

    def artifact(self, job_id: str, name: str) -> Path:
        if name not in ARTIFACTS:
            raise JobNotFoundError("Artefacto desconocido.")
        return self.job_dir(job_id) / name

    def candidate(self, job_id: str, candidate_id: str) -> Path:
        if not _CANDIDATE_ID.match(candidate_id):
            raise JobNotFoundError("Candidato no válido.")
        return self.job_dir(job_id) / "candidates" / f"{candidate_id}.svg"

    def delete(self, job_id: str) -> None:
        path = self.job_dir(job_id)
        if path.exists():
            for p in path.rglob("*"):
                if p.is_file():
                    os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
            shutil.rmtree(path, ignore_errors=True)

    def purge_older_than(self, seconds: float, keep: set[str] | None = None) -> int:
        keep = keep or set()
        now = time.time()
        removed = 0
        for entry in self.base.iterdir():
            if not entry.is_dir() or not _JOB_ID.match(entry.name) or entry.name in keep:
                continue
            if now - entry.stat().st_mtime > seconds:
                self.delete(entry.name)
                removed += 1
        return removed
