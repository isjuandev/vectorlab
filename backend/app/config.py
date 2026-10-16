"""Configuración centralizada. Todas las variables admiten el prefijo VECTORLAB_."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VECTORLAB_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = PROJECT_ROOT / "output" / "jobs"

    # Límites de entrada (los archivos se tratan como datos no confiables)
    max_upload_mb: float = Field(default=25.0, gt=0)
    max_dimension: int = Field(default=6000, ge=16)
    min_dimension: int = Field(default=8, ge=1)
    max_pixels: int = Field(default=24_000_000, ge=256)

    # Las métricas se calculan a una resolución de comparación acotada para limitar memoria.
    metrics_max_pixels: int = Field(default=4_000_000, ge=10_000)

    # Gestión de trabajos
    worker_threads: int = Field(default=1, ge=1, le=4)
    job_ttl_hours: float = Field(default=24.0, gt=0)
    max_retained_jobs: int = Field(default=50, ge=1)
    max_candidate_budget: int = Field(default=4, ge=1, le=4)

    # CORS restringido al frontend local; nunca "*".
    # Acepta JSON (["https://a"]) o una lista separada por comas (https://a,https://b).
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return value

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()
