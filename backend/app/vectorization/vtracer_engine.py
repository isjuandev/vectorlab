"""Adaptador de VTracer 0.6.15 (API Python `convert_raw_image_to_svg`).

Parámetros verificados en la versión instalada (vtracer.pyi y sondas de la Fase 1):
colormode, hierarchical, mode, filter_speckle, color_precision, layer_difference,
corner_threshold, length_threshold, max_iterations, splice_threshold, path_precision.
"""

from __future__ import annotations

import io
import time
from importlib.metadata import version
from typing import Any

import numpy as np
import vtracer
from PIL import Image

from app.errors import EngineError, IncompatibleParamsError
from app.vectorization.base import TraceResult

# rango válido por parámetro: (tipo, mínimo, máximo)
NATIVE_PARAMS: dict[str, tuple[type, float, float]] = {
    "filter_speckle": (int, 0, 128),
    "color_precision": (int, 1, 8),
    "layer_difference": (int, 1, 255),
    "corner_threshold": (int, 0, 180),
    "length_threshold": (float, 3.5, 10.0),
    "max_iterations": (int, 1, 50),
    "splice_threshold": (int, 0, 180),
    "path_precision": (int, 0, 8),
}
MODES = {"spline": "spline", "polygon": "polygon", "pixel": "none"}
HIERARCHIES = {"stacked", "cutout"}


class VTracerEngine:
    name = "vtracer"

    def __init__(self) -> None:
        self.version = version("vtracer")

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in config.items():
            if key == "mode":
                if value not in MODES:
                    raise IncompatibleParamsError(f"Modo de curva desconocido: {value}")
                out[key] = MODES[value]
            elif key == "hierarchical":
                if value not in HIERARCHIES:
                    raise IncompatibleParamsError(f"Jerarquía desconocida: {value}")
                out[key] = value
            elif key in NATIVE_PARAMS:
                typ, lo, hi = NATIVE_PARAMS[key]
                if not lo <= float(value) <= hi:
                    raise IncompatibleParamsError(f"{key}={value} fuera de rango [{lo}, {hi}] para VTracer.")
                out[key] = typ(value)
            else:
                raise IncompatibleParamsError(f"VTracer {self.version} no admite el parámetro '{key}'.")
        return out

    def trace(self, rgba: np.ndarray, config: dict[str, Any], binary: bool = False) -> TraceResult:
        native = self.validate_config(config)
        native["colormode"] = "binary" if binary else "color"
        if binary:
            native.pop("hierarchical", None)  # solo aplica al modo color
            native.pop("color_precision", None)
            native.pop("layer_difference", None)
        buf = io.BytesIO()
        Image.fromarray(np.ascontiguousarray(rgba), "RGBA").save(buf, "PNG", compress_level=1)
        t0 = time.perf_counter()
        try:
            svg = vtracer.convert_raw_image_to_svg(buf.getvalue(), img_format="png", **native)
        except Exception as exc:  # el binding nativo no tipa sus excepciones
            raise EngineError(f"VTracer falló: {exc}") from exc
        return TraceResult(svg=svg, seconds=time.perf_counter() - t0, engine=self.name,
                           engine_version=self.version, native_params=native)
