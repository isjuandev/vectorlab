"""Ejecuta el pipeline completo sobre las muestras y muestra métricas por candidato.

Uso:  backend/.venv/bin/python scripts/evaluate_samples.py [--json salida.json] [archivos…]
Sin archivos, usa samples/synthetic/ y samples/real/ (si existe).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.schemas import VectorizeParams  # noqa: E402
from app.services.pipeline import PipelineRunner  # noqa: E402
from app.vectorization.vtracer_engine import VTracerEngine  # noqa: E402

EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--params", type=str, default="{}", help="JSON de VectorizeParams")
    args = ap.parse_args()
    files = args.files or sorted(p for d in (ROOT / "samples" / "synthetic", ROOT / "samples" / "real")
                                 if d.exists() for p in d.iterdir() if p.suffix.lower() in EXTS)
    params = VectorizeParams.model_validate(json.loads(args.params))
    runner = PipelineRunner(Settings(), VTracerEngine())
    rows = []
    for f in files:
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            (wd / "candidates").mkdir()
            t0 = time.perf_counter()
            rep = runner.run(f.read_bytes(), params, wd, lambda s, p: None, threading.Event())
            elapsed = time.perf_counter() - t0
        print(f"== {f.name}  {elapsed:.2f}s  seleccionado={rep['selected_candidate']}")
        for c in rep["candidates"]:
            m, s = c["metrics"], c["svg_report"]
            print(f"   {c['id']:18s} score={m['score']} ssim={m['ssim']} ΔE={m['delta_e_mean']} "
                  f"edgeF1={m['edge_f1']} region={m['region_agreement']} outlineIoU={m['outline_iou']} "
                  f"alphaIoU={m['alpha_iou']} comp={m['components_preserved']}/{m['components_total']} "
                  f"small_lost={m['small_components_lost']} paths={s['paths']} fills={s['fill_colors']} "
                  f"kb={s['bytes'] / 1024:.0f}")
        for w in rep["warnings"]:
            print("   ⚠", w)
        rows.append({"file": f.name, "seconds": round(elapsed, 3), "selected": rep["selected_candidate"],
                     "candidates": [{"id": c["id"], "metrics": {k: v for k, v in c["metrics"].items()
                                                                 if k != "lost_components"},
                                     "svg": c["svg_report"]} for c in rep["candidates"]],
                     "warnings": rep["warnings"], "notes": rep["notes"]})
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
