from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest

from app.config import Settings
from app.errors import JobCancelledError
from app.schemas import VectorizeParams
from app.services.pipeline import PipelineRunner
from app.validation.render import render_svg
from app.vectorization.vtracer_engine import VTracerEngine
from tests.conftest import cartoon, encode


def _run(tmp_path: Path, data: bytes, **params) -> tuple[dict, str, Path]:
    wd = tmp_path / "job"
    (wd / "candidates").mkdir(parents=True)
    runner = PipelineRunner(Settings(data_dir=tmp_path), VTracerEngine())
    rep = runner.run(data, VectorizeParams(**params), wd, lambda s, p: None, threading.Event())
    return rep, (wd / "result.svg").read_text(), wd


def test_transparency(tmp_path: Path) -> None:
    rep, svg, _ = _run(tmp_path, encode(cartoon(200, transparent=True)))
    out = render_svg(svg, 200, 200)
    assert out[2, 2, 3] == 0 and out[100, 100, 3] == 255
    assert rep["metrics"]["alpha_iou"] > 0.97
    assert any("alfa parcial" in w for w in rep["warnings"])


def test_transparency_disabled_composites_on_white(tmp_path: Path) -> None:
    _, svg, _ = _run(tmp_path, encode(cartoon(200, transparent=True)), preserve_alpha=False)
    out = render_svg(svg, 200, 200)
    assert out[2, 2, 3] == 255 and out[2, 2, :3].min() > 245


def test_background_removal(tmp_path: Path) -> None:
    rep, svg, _ = _run(tmp_path, encode(cartoon(200)), background_mode="remove_uniform")
    out = render_svg(svg, 200, 200)
    assert out[2, 2, 3] == 0 and out[100, 100, 3] == 255
    assert rep["effective_params"]["preprocessing"]["background"]["removed_pixels"] > 0


def test_artifacts_and_report(tmp_path: Path) -> None:
    rep, svg, wd = _run(tmp_path, encode(cartoon()))
    for name in ("result.svg", "preview.png", "preprocessed.png", "report.json"):
        assert (wd / name).exists()
    factor = rep["effective_params"]["supersample_factor"]
    assert "<image" not in svg and 'width="160" height="160"' in svg
    assert f'viewBox="0 0 {160 * factor} {160 * factor}"' in svg
    eff = rep["effective_params"]
    assert eff["engine"] == {"name": "vtracer", "version": "0.6.15"}
    assert eff["native_params"][rep["selected_candidate"]]["colormode"] == "color"
    assert rep["requested_params"]["profile"] == "cartoon_fidelity_v1"


def test_cancellation_between_stages(tmp_path: Path) -> None:
    wd = tmp_path / "job"
    (wd / "candidates").mkdir(parents=True)
    cancel = threading.Event()

    def progress(stage: str, pct: float) -> None:
        if stage == "paleta":
            cancel.set()

    runner = PipelineRunner(Settings(data_dir=tmp_path), VTracerEngine())
    with pytest.raises(JobCancelledError):
        runner.run(encode(cartoon()), VectorizeParams(), wd, progress, cancel)


def test_selection_uses_best_score(tmp_path: Path) -> None:
    rep, _, _ = _run(tmp_path, encode(cartoon(240)), strategy="auto", candidate_budget=2)
    scores = {c["id"]: c["metrics"]["score"] for c in rep["candidates"]}
    assert rep["selected_candidate"] == max(scores, key=scores.get)


def test_large_image_metrics_downscaled(tmp_path: Path) -> None:
    wd = tmp_path / "job"
    (wd / "candidates").mkdir(parents=True)
    runner = PipelineRunner(Settings(data_dir=tmp_path, metrics_max_pixels=40_000), VTracerEngine())
    rep = runner.run(encode(cartoon(400)), VectorizeParams(strategy="integral"), wd, lambda s, p: None,
                     threading.Event())
    assert rep["metrics"]["comparison_scale"] == pytest.approx(0.5, abs=0.01)
    assert rep["metrics"]["comparison_size"] == [200, 200]
    assert np.isfinite(rep["metrics"]["ssim"])
