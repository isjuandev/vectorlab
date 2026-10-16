"""Reconstrucción del SVG final: viewBox, grupos por capa y orden de apilamiento."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.preprocessing.color import nearest_index, rgb_to_lab, to_hex
from app.vectorization.base import TraceResult, VectorizerEngine

SVG_NS = "http://www.w3.org/2000/svg"
_SAFE_ATTR = re.compile(r"^[0-9A-Za-z#.,\-\s()]*$")


@dataclass
class PathElement:
    d: str
    fill: str
    transform: str | None


def parse_paths(svg: str) -> tuple[int, int, list[PathElement]]:
    root = ET.fromstring(svg)
    width = int(float(root.get("width", "0")))
    height = int(float(root.get("height", "0")))
    paths: list[PathElement] = []
    for el in root.iter(f"{{{SVG_NS}}}path"):
        d = el.get("d", "").strip()
        if not d:
            continue
        paths.append(PathElement(d=d, fill=el.get("fill", "#000000"), transform=el.get("transform")))
    return width, height, paths


def _path_xml(p: PathElement, fill: str | None = None) -> str:
    attrs = {"d": p.d, "fill": fill or p.fill}
    if p.transform and p.transform != "translate(0,0)":
        attrs["transform"] = p.transform
    for value in attrs.values():
        if not _SAFE_ATTR.match(value):
            raise ValueError("Atributo de ruta con caracteres inesperados")
    return "<path " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + "/>"


def build_svg(width: int, height: int, layers: list[tuple[str, list[str]]], comment: str,
              out_size: tuple[int, int] | None = None) -> str:
    """`width`/`height` son las coordenadas del trazado (viewBox); `out_size`, el tamaño del documento.

    Con sobremuestreo ×k el trazado está en coordenadas ×k y el documento conserva el tamaño original.
    """
    safe_comment = comment.replace("--", "-")
    ow, oh = out_size or (width, height)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<!-- {safe_comment} -->",
        f'<svg xmlns="{SVG_NS}" version="1.1" width="{ow}" height="{oh}" '
        f'viewBox="0 0 {width} {height}">',
    ]
    for layer_id, elements in layers:
        parts.append(f'<g id="{layer_id}">')
        parts.extend(elements)
        parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def compose_integral(trace: TraceResult, comment: str, out_size: tuple[int, int] | None = None) -> str:
    w, h, paths = parse_paths(trace.svg)
    return build_svg(w, h, [("fills", [_path_xml(p) for p in paths])], comment, out_size)


def compose_layered(engine: VectorizerEngine, fill_rgba: np.ndarray, outline_mask: np.ndarray,
                    outline_color: tuple[int, int, int], config: dict[str, Any],
                    comment: str, out_size: tuple[int, int] | None = None) -> tuple[str, list[TraceResult]]:
    fill_trace = engine.trace(fill_rgba, config)
    line_img = np.full(fill_rgba.shape, 255, np.uint8)
    line_img[outline_mask, :3] = 0
    line_trace = engine.trace(line_img, config, binary=True)
    w, h, fill_paths = parse_paths(fill_trace.svg)
    _, _, line_paths = parse_paths(line_trace.svg)
    color = to_hex(outline_color)
    svg = build_svg(w, h, [
        ("fills", [_path_xml(p) for p in fill_paths]),
        ("outlines", [_path_xml(p, fill=color) for p in line_paths]),
    ], comment, out_size)
    return svg, [fill_trace, line_trace]


_FILL = re.compile(r'fill="(#[0-9A-Fa-f]{6})"')


def snap_fills_to_palette(svg: str, palette: np.ndarray) -> tuple[str, dict[str, str]]:
    """Ajusta los rellenos fuera de paleta (promedios de VTracer) al color de paleta más cercano.

    Devuelve el SVG corregido y el mapa {color original: color asignado} para el informe.
    """
    allowed = {to_hex(c) for c in palette}
    found = {m.lower() for m in _FILL.findall(svg)}
    stray = sorted(found - allowed)
    if not stray or len(palette) == 0:
        return svg, {}
    rgb = np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in stray], np.uint8)
    idx = nearest_index(rgb_to_lab(rgb[:, None, :]).reshape(-1, 3), rgb_to_lab(palette[:, None, :]).reshape(-1, 3))
    mapping = {h: to_hex(palette[i]) for h, i in zip(stray, idx, strict=True)}
    return _FILL.sub(lambda m: f'fill="{mapping.get(m.group(1).lower(), m.group(1).lower())}"', svg), mapping
