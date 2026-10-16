from __future__ import annotations

import numpy as np
import pytest

from app.errors import IncompatibleParamsError, SvgValidationError
from app.schemas import AdvancedParams, VectorizeParams
from app.services.controls import derive_engine_config
from app.validation.metrics import ComparisonData, compute_metrics
from app.validation.render import render_svg
from app.validation.svg_check import inspect_svg
from app.vectorization.compose import compose_integral
from app.vectorization.vtracer_engine import VTracerEngine
from tests.conftest import cartoon

ENGINE = VTracerEngine()


def test_engine_version_pinned() -> None:
    assert ENGINE.version == "0.6.15"


def test_engine_rejects_unknown_and_out_of_range() -> None:
    with pytest.raises(IncompatibleParamsError):
        ENGINE.validate_config({"gradient_step": 3})
    with pytest.raises(IncompatibleParamsError):
        ENGINE.validate_config({"length_threshold": 2.0})
    with pytest.raises(IncompatibleParamsError):
        ENGINE.validate_config({"mode": "bezier"})
    assert ENGINE.validate_config({"mode": "pixel"}) == {"mode": "none"}


def test_derivation_and_overrides_recorded() -> None:
    cfg, src = derive_engine_config(VectorizeParams(), "spline")
    assert cfg["filter_speckle"] == 0 and cfg["color_precision"] == 8
    assert src["filter_speckle"] == "derivado de detail_preservation"
    p = VectorizeParams(advanced=AdvancedParams(filter_speckle=7, path_precision=1))
    cfg, src = derive_engine_config(p, "polygon")
    assert cfg["filter_speckle"] == 7 and src["filter_speckle"] == "override del usuario"
    assert cfg["mode"] == "polygon"
    ENGINE.validate_config(cfg)  # todos los nativos derivados son válidos para la versión instalada


def test_trace_produces_vector_paths() -> None:
    cfg, _ = derive_engine_config(VectorizeParams(), "spline")
    trace = ENGINE.trace(cartoon(), cfg)
    svg = compose_integral(trace, "test")
    rep = inspect_svg(svg, (160, 160))
    assert rep.paths > 3 and rep.nodes > rep.paths and rep.has_viewbox and not rep.raster_embedded


@pytest.mark.parametrize("bad", [
    '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><image href="data:image/png;base64,AA"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><script>alert(1)</script></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><path d="M0 0" onclick="x()"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"></svg>',
    "<html/>", "no es xml",
])
def test_svg_validation_rejects(bad: str) -> None:
    with pytest.raises(SvgValidationError):
        inspect_svg(bad)


def test_svg_validation_counts() -> None:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
           '<path d="M0 0 L10 0 L10 10 Z" fill="#ff0000"/><path d="M1 1 C2 2 3 3 4 4 Z" fill="#00ff00"/></svg>')
    rep = inspect_svg(svg, (10, 10))
    assert rep.paths == 2 and rep.fill_colors == 2 and rep.nodes == 3 + 4 and rep.segments == 4 + 3


def _cmp(original: np.ndarray, labels: np.ndarray, palette: np.ndarray) -> ComparisonData:
    return ComparisonData(original=original, target_labels=labels, palette=palette, scale=1.0,
                          check_alpha=False, outline_emphasis=80)


def test_metrics_identity_and_degradation() -> None:
    img = np.full((64, 64, 4), 255, np.uint8)
    img[16:48, 16:48, :3] = (200, 30, 30)
    labels = np.zeros((64, 64), np.int32)
    labels[16:48, 16:48] = 1
    palette = np.array([[255, 255, 255], [200, 30, 30]], np.uint8)
    same = compute_metrics(_cmp(img, labels, palette), img)
    assert same["ssim"] == 1.0 and same["delta_e_mean"] == 0 and same["edge_f1"] == 1.0
    assert same["region_agreement"] == 1.0 and same["components_lost"] == 0
    shifted = np.roll(img, 4, axis=1)
    worse = compute_metrics(_cmp(img, labels, palette), shifted)
    assert worse["ssim"] < same["ssim"] and worse["edge_f1"] < 1.0 and worse["score"] < same["score"]


def test_metrics_detect_lost_component() -> None:
    img = np.full((64, 64, 4), 255, np.uint8)
    img[10:14, 10:14, :3] = 0
    labels = np.zeros((64, 64), np.int32)
    labels[10:14, 10:14] = 1
    palette = np.array([[255, 255, 255], [0, 0, 0]], np.uint8)
    blank = np.full_like(img, 255)
    m = compute_metrics(_cmp(img, labels, palette), blank)
    assert m["components_lost"] == 1 and m["lost_components"][0]["bbox"] == [10, 10, 4, 4]


def test_render_matches_requested_size() -> None:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 10 10">'
           '<path d="M0 0 L10 0 L10 10 L0 10 Z" fill="#ff0000"/></svg>')
    out = render_svg(svg, 30, 30)
    assert out.shape == (30, 30, 4) and tuple(out[15, 15]) == (255, 0, 0, 255)
