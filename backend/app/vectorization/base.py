"""Contrato de motor de vectorización (desacopla el pipeline de VTracer)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


@dataclass
class TraceResult:
    svg: str
    seconds: float
    engine: str
    engine_version: str
    native_params: dict[str, Any]


class VectorizerEngine(Protocol):
    name: str
    version: str

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Devuelve la configuración nativa normalizada o lanza IncompatibleParamsError."""
        ...

    def trace(self, rgba: np.ndarray, config: dict[str, Any], binary: bool = False) -> TraceResult:
        """Traza una imagen RGBA uint8. `binary=True` traza solo píxeles oscuros en un color."""
        ...
