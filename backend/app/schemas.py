"""Esquemas Pydantic de la API (entrada de parámetros y respuestas)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROFILE_ID = "cartoon_fidelity_v1"


class Strategy(StrEnum):
    """Modo de vectorización."""

    auto = "auto"  # evalúa candidatos (integral y por capas) y elige el mejor según métricas
    integral = "integral"  # un único trazado a color
    layered = "layered"  # rellenos + capa de contornos trazada por separado


class CurveMode(StrEnum):
    spline = "spline"
    polygon = "polygon"
    pixel = "pixel"  # VTracer mode="none": bordes de píxel exactos
    auto = "auto"  # prueba spline y polygon dentro del presupuesto de candidatos


class Hierarchy(StrEnum):
    stacked = "stacked"
    cutout = "cutout"


class BackgroundMode(StrEnum):
    keep = "keep"
    remove_uniform = "remove_uniform"


class AdvancedParams(BaseModel):
    """Overrides de parámetros nativos de VTracer. None = derivado del perfil."""

    model_config = ConfigDict(extra="forbid")

    filter_speckle: int | None = Field(default=None, ge=0, le=128)
    color_precision: int | None = Field(default=None, ge=1, le=8)
    layer_difference: int | None = Field(default=None, ge=1, le=255)
    corner_threshold: int | None = Field(default=None, ge=0, le=180)
    length_threshold: float | None = Field(default=None, ge=3.5, le=10.0)
    splice_threshold: int | None = Field(default=None, ge=0, le=180)
    max_iterations: int | None = Field(default=None, ge=1, le=50)
    path_precision: int | None = Field(default=None, ge=0, le=8)
    hierarchical: Hierarchy | None = None


class VectorizeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Literal["cartoon_fidelity_v1"] = PROFILE_ID
    strategy: Strategy = Strategy.auto
    curve_mode: CurveMode = CurveMode.spline
    max_colors: int = Field(default=64, ge=2, le=256)
    detail_preservation: int = Field(default=100, ge=0, le=100)
    outline_emphasis: int = Field(default=80, ge=0, le=100)
    preserve_alpha: bool = True
    alpha_threshold: int = Field(default=128, ge=1, le=255)
    background_mode: BackgroundMode = BackgroundMode.keep
    background_tolerance: float = Field(default=6.0, ge=0.5, le=40.0)
    denoise_lossy: bool = True
    visual_validation: bool = True
    candidate_budget: int = Field(default=2, ge=1, le=4)
    supersample: int = Field(default=0, ge=0, le=4)  # 0 = auto; 1 = sin sobremuestreo
    advanced: AdvancedParams = Field(default_factory=AdvancedParams)

    @model_validator(mode="after")
    def _check_compatibility(self) -> VectorizeParams:
        problems = incompatibilities(self)
        if problems:
            raise ValueError("; ".join(problems))
        return self


def incompatibilities(p: VectorizeParams) -> list[str]:
    """Combinaciones que no tienen sentido. Se rechazan en vez de corregirse en silencio."""
    out: list[str] = []
    if p.strategy is Strategy.layered and p.outline_emphasis == 0:
        out.append("strategy=layered requiere outline_emphasis > 0 (la capa de contornos estaría vacía)")
    if p.background_mode is BackgroundMode.remove_uniform and not p.preserve_alpha:
        out.append("background_mode=remove_uniform requiere preserve_alpha=true (el fondo eliminado es transparencia)")
    multi = p.strategy is Strategy.auto or p.curve_mode is CurveMode.auto
    if multi and not p.visual_validation and p.candidate_budget > 1:
        out.append("comparar varios candidatos requiere visual_validation=true (la selección usa métricas)")
    return out


class JobState(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ExportLinks(BaseModel):
    svg: str
    png: str
    preview: str
    metrics: str


class CandidateSummary(BaseModel):
    id: str
    strategy: str
    curve_mode: str
    score: float | None
    selected: bool
    svg_bytes: int
    paths: int
    ssim: float | None = None


class JobResponse(BaseModel):
    job_id: str
    state: JobState
    stage: str
    progress: float = Field(ge=0, le=100)
    created_at: str
    updated_at: str
    input: dict[str, Any] = Field(default_factory=dict)
    requested_params: VectorizeParams
    effective_params: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None
    exports: ExportLinks | None = None
    candidates: list[CandidateSummary] = Field(default_factory=list)
    metrics_summary: dict[str, Any] | None = None
