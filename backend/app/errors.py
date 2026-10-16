"""Errores tipados del dominio. Cada error lleva un código estable y un estado HTTP."""

from __future__ import annotations

from typing import Any


class VectorLabError(Exception):
    code = "internal_error"
    http_status = 500

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class InvalidImageError(VectorLabError):
    code = "invalid_image"
    http_status = 415


class CorruptImageError(VectorLabError):
    code = "corrupt_image"
    http_status = 422


class LimitExceededError(VectorLabError):
    code = "limit_exceeded"
    http_status = 413


class IncompatibleParamsError(VectorLabError):
    code = "incompatible_params"
    http_status = 422


class JobNotFoundError(VectorLabError):
    code = "job_not_found"
    http_status = 404


class JobNotReadyError(VectorLabError):
    code = "job_not_ready"
    http_status = 409


class EngineError(VectorLabError):
    code = "engine_error"
    http_status = 500


class SvgValidationError(VectorLabError):
    code = "svg_validation_failed"
    http_status = 500


class JobCancelledError(VectorLabError):
    code = "job_cancelled"
    http_status = 409
