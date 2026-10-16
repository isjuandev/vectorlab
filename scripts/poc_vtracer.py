"""Fase 1 – Prueba de concepto de VTracer.

Convierte las imágenes de samples/ a SVG con varias configuraciones, renderiza
cada SVG con resvg, y registra tiempo, tamaño, nº de rutas y SSIM.
Además ejecuta sondas sobre el comportamiento real de la versión instalada:
transparencia, semántica de filter_speckle y agujeros en modo binario.

Uso:  backend/.venv/bin/python scripts/poc_vtracer.py
Salida: output/poc/ (SVG, PNG renderizados y report.json)
"""

from __future__ import annotations

import io
import json
import re
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import resvg_py
import vtracer
from PIL import Image
from skimage.metrics import structural_similarity

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples" / "synthetic"
OUT = ROOT / "output" / "poc"

CONFIGS: dict[str, dict] = {
    "defaults": {},
    "fidelity": dict(filter_speckle=1, color_precision=8, layer_difference=8,
                     corner_threshold=45, length_threshold=3.5, splice_threshold=45,
                     max_iterations=10, path_precision=3),
    "fidelity_fs2": dict(filter_speckle=2, color_precision=8, layer_difference=8,
                         corner_threshold=45, length_threshold=3.5, path_precision=3),
    "polygon": dict(mode="polygon", filter_speckle=2, color_precision=8, layer_difference=8),
    "cutout": dict(hierarchical="cutout", filter_speckle=2, color_precision=8,
                   layer_difference=8, path_precision=3),
}


def to_png_bytes(rgba: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG")
    return buf.getvalue()


def render(svg: str, w: int, h: int) -> np.ndarray:
    png = bytes(resvg_py.svg_to_bytes(svg_string=svg, width=w, height=h))
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


def over_white(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    return (rgba[..., :3].astype(np.float32) * a + 255.0 * (1 - a)).astype(np.uint8)


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    return float(structural_similarity(over_white(a), over_white(b), channel_axis=2, data_range=255))


def svg_stats(svg: str) -> dict:
    return {
        "paths": len(re.findall(r"<path\b", svg)),
        "fills": len(set(re.findall(r'fill="(#[0-9A-Fa-f]{6})"', svg))),
        "bytes": len(svg.encode()),
        "has_image_tag": "<image" in svg,
    }


def run_matrix() -> list[dict]:
    rows = []
    for src in sorted(SAMPLES.iterdir()):
        if src.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        rgba = np.asarray(Image.open(src).convert("RGBA"))
        h, w = rgba.shape[:2]
        data = to_png_bytes(rgba)  # WebP/JPG se normalizan a PNG RGBA antes del motor
        for name, cfg in CONFIGS.items():
            t0 = time.perf_counter()
            svg = vtracer.convert_raw_image_to_svg(data, img_format="png", **cfg)
            dt = time.perf_counter() - t0
            out = render(svg, w, h)
            stem = f"{src.stem}__{name}"
            (OUT / f"{stem}.svg").write_text(svg)
            Image.fromarray(out).save(OUT / f"{stem}.png")
            row = {"file": src.name, "config": name, "seconds": round(dt, 3),
                   "ssim_on_white": round(ssim(rgba, out), 4), **svg_stats(svg)}
            if rgba[..., 3].min() < 255:
                src_a = rgba[..., 3] > 127
                out_a = out[..., 3] > 127
                row["alpha_iou"] = round(float((src_a & out_a).sum() / max(1, (src_a | out_a).sum())), 4)
            rows.append(row)
            print(row)
    return rows


def probe_filter_speckle() -> dict:
    """¿filter_speckle se compara contra área (px²) o contra lado (px)?"""
    img = np.full((64, 64, 4), 255, np.uint8)
    # cuadrados negros de lado 1..6 px
    for i, side in enumerate(range(1, 7)):
        x = 4 + i * 10
        img[20:20 + side, x:x + side, :3] = 0
    data = to_png_bytes(img)
    result = {}
    for fs in (1, 2, 3, 4, 5):
        svg = vtracer.convert_raw_image_to_svg(data, img_format="png", filter_speckle=fs,
                                               color_precision=8, layer_difference=1)
        out = render(svg, 64, 64)
        kept = []
        for i, side in enumerate(range(1, 7)):
            x = 4 + i * 10
            region = out[20:20 + side, x:x + side, :3]
            kept.append(bool(region.mean() < 128))
        result[f"filter_speckle={fs}"] = {f"lado_{s}px": k for s, k in zip(range(1, 7), kept, strict=True)}
    return result


def probe_transparency() -> dict:
    img = np.zeros((64, 64, 4), np.uint8)  # todo transparente
    img[16:48, 16:48] = (200, 30, 30, 255)
    img[28:36, 28:36] = (0, 0, 0, 0)  # agujero transparente
    img[0:8, 0:64] = (0, 0, 255, 128)  # franja semitransparente
    svg = vtracer.convert_raw_image_to_svg(to_png_bytes(img), img_format="png", filter_speckle=1,
                                           color_precision=8)
    out = render(svg, 64, 64)
    return {
        "exterior_transparente": bool(out[60, 60, 3] == 0),
        "agujero_transparente": bool(out[32, 32, 3] == 0),
        "cuadrado_opaco": bool(out[20, 20, 3] == 255),
        "franja_alpha128_alpha_render": int(out[4, 30, 3]),
        "franja_alpha128_rgb_render": out[4, 30, :3].tolist(),
    }


def probe_binary_holes() -> dict:
    img = np.full((64, 64, 4), 255, np.uint8)
    yy, xx = np.mgrid[:64, :64]
    ring = ((yy - 32) ** 2 + (xx - 32) ** 2 <= 20 ** 2) & ((yy - 32) ** 2 + (xx - 32) ** 2 >= 12 ** 2)
    img[ring, :3] = 0
    svg = vtracer.convert_raw_image_to_svg(to_png_bytes(img), img_format="png", colormode="binary",
                                           filter_speckle=1)
    out = render(svg, 64, 64)
    (OUT / "probe_binary_ring.svg").write_text(svg)
    return {
        "centro_del_anillo_vacio": bool(out[32, 32, 3] == 0 or out[32, 32, :3].mean() > 200),
        "anillo_negro": bool(out[32, 32 + 16, :3].mean() < 60 and out[32, 48, 3] > 200),
        "fill_values": sorted(set(re.findall(r'fill="([^"]+)"', svg))),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "vtracer_version": version("vtracer"),
        "resvg_py_version": version("resvg-py"),
        "probes": {
            "filter_speckle": probe_filter_speckle(),
            "transparency": probe_transparency(),
            "binary_holes": probe_binary_holes(),
        },
    }
    print(json.dumps(report["probes"], indent=2))
    report["matrix"] = run_matrix()
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print("informe:", OUT / "report.json")


if __name__ == "__main__":
    main()
