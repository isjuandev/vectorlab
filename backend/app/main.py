"""Aplicación FastAPI de VectorLab. Ejecutar: uvicorn app.main:app --host 127.0.0.1 --port 8000"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import router
from app.config import Settings, get_settings
from app.errors import VectorLabError
from app.services.jobs import JobManager
from app.vectorization.vtracer_engine import VTracerEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = VTracerEngine()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.jobs = JobManager(settings, engine)
        app.state.jobs.cleanup()
        yield
        app.state.jobs.shutdown()

    app = FastAPI(title="VectorLab API", version=__version__, lifespan=lifespan,
                  description="Vectorización local de ilustraciones y caricaturas a SVG editable.")
    app.state.settings = settings
    app.state.engine = engine
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["*"], expose_headers=["Content-Disposition"])

    @app.exception_handler(VectorLabError)
    async def _domain_error(_: Request, exc: VectorLabError) -> JSONResponse:
        return JSONResponse({"error": exc.to_dict()}, status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": {"code": "validation_error", "message": "Solicitud no válida.",
                                       "details": {"errors": jsonable_encoder(exc.errors())}}}, status_code=422)

    app.include_router(router)
    return app


app = create_app()
