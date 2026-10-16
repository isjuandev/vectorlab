"""Atribuye la pérdida de bordes a cada etapa: original → preprocesada (paleta) → SVG.

Uso:  backend/.venv/bin/python scripts/diagnose_edges.py IMAGEN [--params JSON] [--crop y0,y1,x0,x1] [--out mapa.png]

Imprime el recall de bordes Canny (≤ 1,5 px) en cada transición y, con --out, guarda un mapa:
original | preprocesada | bordes perdidos (magenta = en la cuantización, azul = en el trazado).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import Settings  # noqa: E402
from app.schemas import VectorizeParams  # noqa: E402
from app.services.pipeline import PipelineRunner  # noqa: E402
from app.validation.render import render_svg  # noqa: E402
from app.vectorization.vtracer_engine import VTracerEngine  # noqa: E402


def over_white(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    return (rgba[..., :3] * a + 255.0 * (1 - a)).astype(np.uint8)


def edges(rgb: np.ndarray) -> np.ndarray:
    return cv2.Canny(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), 50, 150) > 0


def far_from(target_edges: np.ndarray) -> np.ndarray:
    return cv2.distanceTransform((~target_edges).astype(np.uint8), cv2.DIST_L2, 5) > 1.5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("--params", default="{}")
    ap.add_argument("--crop", help="y0,y1,x0,x1 para limitar la medición y el mapa")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        wd = Path(tmp)
        (wd / "candidates").mkdir()
        params = VectorizeParams.model_validate(json.loads(args.params))
        rep = PipelineRunner(Settings(), VTracerEngine()).run(args.image.read_bytes(), params, wd,
                                                              lambda s, p: None, threading.Event())
        w, h = rep["input"]["width"], rep["input"]["height"]
        original = over_white(np.asarray(Image.open(args.image).convert("RGBA")))
        pre = over_white(np.asarray(Image.open(wd / "preprocessed.png").convert("RGBA")))
        svg = over_white(render_svg((wd / "result.svg").read_text(), w, h))

    y0, y1, x0, x1 = (int(v) for v in args.crop.split(",")) if args.crop else (0, h, 0, w)
    eo, ep, es = (edges(x)[y0:y1, x0:x1] for x in (original, pre, svg))
    far_p, far_s = far_from(ep), far_from(es)

    def recall(src: np.ndarray, far: np.ndarray) -> float:
        return float((~far[src]).mean()) if src.any() else float("nan")

    print(f"candidato elegido: {rep['selected_candidate']}")
    print(f"recall original→preprocesada {recall(eo, far_p):.3f}")
    print(f"recall preprocesada→SVG      {recall(ep, far_s):.3f}")
    print(f"recall original→SVG          {recall(eo, far_s):.3f}")
    if args.out:
        o = original[y0:y1, x0:x1]
        vis = (o * 0.45 + 140).astype(np.uint8)
        vis[eo & far_p] = (230, 0, 180)
        vis[eo & ~far_p & far_s] = (0, 160, 255)
        sep = np.full((o.shape[0], 4, 3), 255, np.uint8)
        Image.fromarray(np.hstack([o, sep, pre[y0:y1, x0:x1], sep, vis])).save(args.out)
        print("mapa:", args.out)


if __name__ == "__main__":
    main()
