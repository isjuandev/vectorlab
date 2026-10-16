"""Renderizado del SVG con resvg (sin dependencias del sistema)."""

from __future__ import annotations

import io

import numpy as np
import resvg_py
from PIL import Image

from app.errors import SvgValidationError


def render_svg(svg: str, width: int, height: int) -> np.ndarray:
    """Renderiza a RGBA uint8 del tamaño indicado (fondo transparente)."""
    try:
        png = bytes(resvg_py.svg_to_bytes(svg_string=svg, width=width, height=height,
                                          skip_system_fonts=True))
    except ValueError as exc:
        raise SvgValidationError(f"resvg no pudo renderizar el SVG: {exc}") from exc
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    if img.size != (width, height):
        img = img.resize((width, height), Image.Resampling.LANCZOS)
    return np.asarray(img)


def encode_png(rgba: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=False, compress_level=6)
    return buf.getvalue()
