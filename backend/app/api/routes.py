"""Rutas HTTP v1. Sin lógica de negocio: delegan en JobManager y en los servicios."""

from __future__ import annotations

import json
from importlib.metadata import version
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import ValidationError

from app import __version__
from app.errors import IncompatibleParamsError, JobNotReadyError, LimitExceededError
from app.preprocessing.decode import FORMATS
from app.schemas import (
    CandidateSummary,
    ExportLinks,
    JobResponse,
    JobState,
    VectorizeParams,
)
from app.services.controls import ADVANCED_SPECS, CONTROL_SPECS
from app.services.jobs import Job, JobManager
from app.validation.render import encode_png, render_svg

router = APIRouter(prefix="/api/v1")

SVG_HEADERS = {
    # El SVG se sirve como documento inerte: sin scripts ni recursos externos.
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
}


def _manager(request: Request) -> JobManager:
    return request.app.state.jobs


def _to_response(job: Job) -> JobResponse:
    base = f"/api/v1/jobs/{job.id}"
    report = job.report or {}
    exports = None
    candidates: list[CandidateSummary] = []
    summary = None
    if job.state is JobState.completed and report:
        exports = ExportLinks(svg=f"{base}/download.svg", png=f"{base}/download.png", preview=f"{base}/preview",
                              metrics=f"{base}/metrics")
        for c in report["candidates"]:
            candidates.append(CandidateSummary(
                id=c["id"], strategy=c["strategy"], curve_mode=c["curve_mode"], score=c["metrics"].get("score"),
                selected=c["selected"], svg_bytes=c["svg_report"]["bytes"], paths=c["svg_report"]["paths"],
                ssim=c["metrics"].get("ssim")))
        m = report["metrics"]
        summary = {k: m.get(k) for k in ("score", "ssim", "delta_e_mean", "edge_f1", "region_agreement",
                                          "alpha_iou", "outline_iou", "components_lost", "components_total")}
        summary["total_seconds"] = report["timings_s"].get("total")
    return JobResponse(
        job_id=job.id, state=job.state, stage=job.stage, progress=round(job.progress, 1),
        created_at=job.created_at, updated_at=job.updated_at, input=job.input_info,
        requested_params=job.params, effective_params=report.get("effective_params"),
        warnings=job.warnings, error=job.error, exports=exports, candidates=candidates,
        metrics_summary=summary)


def _completed(job: Job) -> Job:
    if job.state is not JobState.completed:
        raise JobNotReadyError(f"El trabajo está en estado '{job.state.value}'; el resultado aún no existe.")
    return job


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/capabilities")
def capabilities(request: Request) -> dict:
    s = request.app.state.settings
    engine = request.app.state.engine
    return {
        "formats": list(FORMATS.values()),
        "limits": {"max_upload_bytes": s.max_upload_bytes, "max_dimension": s.max_dimension,
                   "min_dimension": s.min_dimension, "max_pixels": s.max_pixels,
                   "metrics_max_pixels": s.metrics_max_pixels, "max_candidate_budget": s.max_candidate_budget},
        "engines": [{"name": engine.name, "version": engine.version, "default": True}],
        "renderer": {"name": "resvg-py", "version": version("resvg-py")},
        "profiles": [{"id": "cartoon_fidelity_v1",
                      "defaults": VectorizeParams().model_dump(mode="json")}],
        "controls": CONTROL_SPECS,
        "advanced_controls": ADVANCED_SPECS,
        "metrics": ["ssim", "delta_e_mean", "delta_e_p95", "delta_e_interior_mean", "edge_mean_distance_px",
                    "edge_f1", "region_agreement", "region_mean_iou", "alpha_iou", "outline_iou",
                    "components_preserved", "components_lost", "nodes", "paths", "bytes", "seconds"],
    }


@router.post("/jobs", status_code=202, response_model=JobResponse)
async def create_job(request: Request, file: Annotated[UploadFile, File()],
                     params: Annotated[str | None, Form()] = None) -> JobResponse:
    settings = request.app.state.settings
    try:
        parsed = VectorizeParams.model_validate(json.loads(params)) if params else VectorizeParams()
    except (ValidationError, json.JSONDecodeError) as exc:
        details = json.loads(exc.json()) if isinstance(exc, ValidationError) else {"json": str(exc)}
        raise IncompatibleParamsError("Parámetros no válidos.", {"errors": details}) from exc
    data = await file.read(settings.max_upload_bytes + 1)
    await file.close()
    if len(data) > settings.max_upload_bytes:
        raise LimitExceededError(f"El archivo supera el límite de {settings.max_upload_mb:g} MB.")
    job = _manager(request).submit(data, parsed)
    return _to_response(job)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(request: Request, job_id: str) -> JobResponse:
    return _to_response(_manager(request).get(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(request: Request, job_id: str) -> JobResponse:
    return _to_response(_manager(request).cancel(job_id))


@router.get("/jobs/{job_id}/metrics")
def get_metrics(request: Request, job_id: str) -> JSONResponse:
    job = _completed(_manager(request).get(job_id))
    return JSONResponse(job.report)


def _svg_path(manager: JobManager, job: Job, candidate: str | None):  # noqa: ANN202
    if candidate:
        path = manager.storage.candidate(job.id, candidate)
        if not path.exists():
            raise JobNotReadyError("Ese candidato no existe en este trabajo.")
        return path
    return manager.storage.artifact(job.id, "result.svg")


@router.get("/jobs/{job_id}/download.svg")
def download_svg(request: Request, job_id: str, candidate: str | None = None,
                 disposition: Literal["attachment", "inline"] = "attachment") -> FileResponse:
    manager = _manager(request)
    job = _completed(manager.get(job_id))
    suffix = f"-{candidate}" if candidate else ""
    return FileResponse(_svg_path(manager, job, candidate), media_type="image/svg+xml",
                        filename=f"vectorlab-{job.id[:8]}{suffix}.svg", content_disposition_type=disposition,
                        headers=SVG_HEADERS)


@router.get("/jobs/{job_id}/preview")
def preview(request: Request, job_id: str) -> FileResponse:
    manager = _manager(request)
    job = _completed(manager.get(job_id))
    return FileResponse(manager.storage.artifact(job.id, "preview.png"), media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@router.get("/jobs/{job_id}/download.png")
def download_png(request: Request, job_id: str,
                 candidate: Annotated[str | None, Query()] = None) -> Response:
    manager = _manager(request)
    job = _completed(manager.get(job_id))
    name = f"vectorlab-{job.id[:8]}{'-' + candidate if candidate else ''}.png"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    if not candidate:
        return FileResponse(manager.storage.artifact(job.id, "preview.png"), media_type="image/png",
                            headers=headers)
    svg = _svg_path(manager, job, candidate).read_text()
    info = job.input_info
    return Response(encode_png(render_svg(svg, info["width"], info["height"])), media_type="image/png",
                     headers=headers)
