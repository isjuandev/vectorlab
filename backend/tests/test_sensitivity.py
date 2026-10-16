"""Pruebas de sensibilidad: cada control relevante debe modificar una operación real."""

from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.config import Settings
from app.preprocessing.outlines import detect_outlines
from app.schemas import VectorizeParams
from app.services.pipeline import PipelineRunner
from app.validation.render import render_svg
from app.vectorization.vtracer_engine import VTracerEngine
from tests.conftest import cartoon, encode


def run(tmp_path: Path, data: bytes, **params) -> tuple[dict, str]:
    wd = tmp_path / f"job{len(list(tmp_path.iterdir()))}"
    (wd / "candidates").mkdir(parents=True)
    runner = PipelineRunner(Settings(data_dir=tmp_path), VTracerEngine())
    rep = runner.run(data, VectorizeParams(**params), wd, lambda s, p: None, threading.Event())
    return rep, (wd / "result.svg").read_text()


def test_strategy_changes_structure(tmp_path: Path) -> None:
    data = encode(cartoon(240))
    _, integral = run(tmp_path, data, strategy="integral")
    _, layered = run(tmp_path, data, strategy="layered")
    assert '<g id="outlines">' not in integral
    assert '<g id="outlines">' in layered


def test_curve_mode_changes_geometry(tmp_path: Path) -> None:
    data = encode(cartoon())
    _, spline = run(tmp_path, data, strategy="integral", curve_mode="spline")
    _, polygon = run(tmp_path, data, strategy="integral", curve_mode="polygon")
    assert " C" in spline and " C" not in polygon


def test_curve_mode_auto_respects_budget(tmp_path: Path) -> None:
    data = encode(cartoon(240))
    rep, _ = run(tmp_path, data, curve_mode="auto", candidate_budget=4)
    assert {c["id"] for c in rep["candidates"]} == {"integral_spline", "layered_spline", "integral_polygon",
                                                    "layered_polygon"}
    rep, _ = run(tmp_path, data, curve_mode="auto", candidate_budget=1)
    assert len(rep["candidates"]) == 1 and any("Presupuesto" in w for w in rep["warnings"])


def test_max_colors_limits_palette(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    img = cartoon(200)
    noise = rng.integers(-25, 25, img[..., :3].shape)
    img[..., :3] = np.clip(img[..., :3].astype(int) + noise, 0, 255).astype(np.uint8)
    data = encode(img)
    few, _ = run(tmp_path, data, max_colors=6, strategy="integral")
    many, _ = run(tmp_path, data, max_colors=48, strategy="integral")
    pal_few = few["effective_params"]["preprocessing"]["palette"]["colors"]
    pal_many = many["effective_params"]["preprocessing"]["palette"]["colors"]
    assert pal_few <= 6 + 1  # +1 si el color de contorno se añadió con hueco (no ocurre con paleta llena)
    assert pal_few < pal_many <= 48 + 1
    assert few["svg"]["fill_colors"] <= 6  # límite estricto tras ajustar rellenos a la paleta
    assert many["svg"]["fill_colors"] <= 48


def test_detail_preserves_small_features(tmp_path: Path) -> None:
    img = np.full((120, 120, 4), 255, np.uint8)
    for i in range(6):  # puntos de 2–3 px de lado
        x = 15 + i * 16
        img[50:53, x:x + 3, :3] = (200, 30, 30)
        img[80:82, x:x + 2, :3] = (30, 60, 200)
    data = encode(img)
    hi, svg_hi = run(tmp_path, data, detail_preservation=100, outline_emphasis=0, strategy="integral")
    lo, svg_lo = run(tmp_path, data, detail_preservation=0, outline_emphasis=0, strategy="integral")
    assert hi["effective_params"]["native_params"]["integral_spline"]["filter_speckle"] == 0
    k = lo["effective_params"]["supersample_factor"]
    assert k > 1  # 120 px → sobremuestreo automático; filter_speckle se mide en píxeles del original
    assert lo["effective_params"]["native_params"]["integral_spline"]["filter_speckle"] == 4 * k

    def red_dots(svg: str) -> int:
        r = render_svg(svg, 120, 120)
        return sum(int(r[50:53, 15 + i * 16:18 + i * 16, 1].mean() < 150) for i in range(6))

    assert red_dots(svg_hi) == 6
    assert red_dots(svg_lo) < 6
    assert hi["metrics"]["components_lost"] < lo["metrics"]["components_lost"]


def test_outline_emphasis_changes_mask() -> None:
    rgb = np.full((240, 240, 3), 255, np.uint8)
    cv2.rectangle(rgb, (20, 20), (220, 220), (15, 15, 15), 4)
    cv2.rectangle(rgb, (60, 60), (180, 180), (70, 70, 70), 3)  # gris oscuro (L* ≈ 30)
    opaque = np.ones((240, 240), bool)
    counts = {e: int(detect_outlines(rgb, opaque, e).stats.get("pixels", 0)) for e in (0, 20, 80, 100)}
    assert counts[0] == 0
    assert counts[20] < counts[80] <= counts[100]  # el gris solo entra con énfasis alto


def test_outline_emphasis_zero_disables_layering(tmp_path: Path) -> None:
    rep, svg = run(tmp_path, encode(cartoon(240)), outline_emphasis=0)
    assert [c["strategy"] for c in rep["candidates"]] == ["integral"]
    assert rep["metrics"]["outline_iou"] is None


@pytest.mark.parametrize("flag", [True, False])
def test_denoise_lossy_reduces_paths(tmp_path: Path, flag: bool) -> None:
    data = encode(cartoon(240), "JPEG", quality=70)
    rep, _ = run(tmp_path, data, denoise_lossy=flag, strategy="integral")
    applied = any("mean-shift" in n for n in rep["notes"])
    assert applied is flag


def test_denoise_lossy_effect(tmp_path: Path) -> None:
    data = encode(cartoon(240), "JPEG", quality=70)
    on, _ = run(tmp_path, data, denoise_lossy=True, strategy="integral")
    off, _ = run(tmp_path, data, denoise_lossy=False, strategy="integral")
    assert on["svg"]["paths"] < off["svg"]["paths"]


def test_supersample_improves_small_image_and_keeps_document_size(tmp_path: Path) -> None:
    data = encode(cartoon(120))
    one, svg1 = run(tmp_path, data, supersample=1, strategy="integral")
    four, svg4 = run(tmp_path, data, supersample=4, strategy="integral")
    assert one["effective_params"]["supersample_factor"] == 1
    assert four["effective_params"]["supersample_factor"] == 4
    assert 'width="120" height="120" viewBox="0 0 120 120"' in svg1
    assert 'width="120" height="120" viewBox="0 0 480 480"' in svg4
    assert four["metrics"]["ssim"] > one["metrics"]["ssim"]
    assert four["svg"]["fill_colors"] <= one["effective_params"]["preprocessing"]["palette"]["colors"]
