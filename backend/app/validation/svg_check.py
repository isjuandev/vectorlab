"""Validación estructural del SVG producido: geometría real, sin ráster incrustado ni contenido activo."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

from app.errors import SvgValidationError

SVG_NS = "{http://www.w3.org/2000/svg}"
FORBIDDEN_TAGS = {"image", "script", "foreignObject", "iframe", "use", "a", "style"}
_NUM = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")
_CMD = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")


@dataclass
class SvgReport:
    width: int
    height: int
    has_viewbox: bool
    paths: int
    nodes: int  # vértices/puntos de control (pares de coordenadas)
    segments: int  # comandos de dibujo
    fill_colors: int
    bytes: int
    raster_embedded: bool

    def to_dict(self) -> dict:
        return asdict(self)


def inspect_svg(svg: str, expected_size: tuple[int, int] | None = None) -> SvgReport:
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise SvgValidationError(f"El SVG generado no es XML válido: {exc}") from exc
    if root.tag != f"{SVG_NS}svg":
        raise SvgValidationError("El elemento raíz no es <svg>.")
    raster = False
    paths = nodes = segments = 0
    fills: set[str] = set()
    for el in root.iter():
        local = el.tag.replace(SVG_NS, "")
        if local in FORBIDDEN_TAGS:
            if local == "image":
                raster = True
            raise SvgValidationError(f"El SVG contiene un elemento no permitido: <{local}>.",
                                     {"raster_embedded": raster})
        for attr, value in el.attrib.items():
            if "href" in attr or value.strip().lower().startswith(("data:", "javascript:")):
                raise SvgValidationError("El SVG contiene referencias externas o URIs de datos.")
            if attr.startswith("on"):
                raise SvgValidationError("El SVG contiene atributos de evento.")
        if local == "path":
            d = el.get("d", "")
            paths += 1
            segments += len(_CMD.findall(d))
            nodes += len(_NUM.findall(d)) // 2
            fills.add(el.get("fill", "").lower())
    width = int(float(root.get("width", "0")))
    height = int(float(root.get("height", "0")))
    if expected_size and (width, height) != expected_size:
        raise SvgValidationError(f"Dimensiones del SVG {width}x{height} ≠ entrada {expected_size[0]}x"
                                 f"{expected_size[1]}.")
    if paths == 0:
        raise SvgValidationError("El SVG no contiene rutas vectoriales.")
    return SvgReport(width=width, height=height, has_viewbox=root.get("viewBox") is not None, paths=paths,
                     nodes=nodes, segments=segments, fill_colors=len(fills), bytes=len(svg.encode()),
                     raster_embedded=raster)
