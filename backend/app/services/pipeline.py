"""Orquestación del pipeline de vectorización.

Etapas: decodificación → normalización (alfa/fondo) → análisis → paleta → contornos →
trazado de candidatos → validación SVG → render + métricas → selección → exportación.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app import __version__
from app.config import Settings
from app.errors import JobCancelledError
from app.preprocessing.background import (
    apply_alpha_policy,
    denoise_lossy,
    detect_background,
    remove_uniform_background,
)
from app.preprocessing.color import rgb_to_lab, to_hex
from app.preprocessing.decode import DecodedImage, decode
from app.preprocessing.labels import nearest_fill
from app.preprocessing.outlines import OutlineResult, detect_outlines
from app.preprocessing.palette import PaletteResult, quantize
from app.preprocessing.supersample import supersample_labels, upscale_rgba
from app.schemas import BackgroundMode, CurveMode, Strategy, VectorizeParams
from app.services.controls import derive_engine_config
from app.validation.metrics import ComparisonData, compute_metrics
from app.validation.render import encode_png, render_svg
from app.validation.svg_check import inspect_svg
from app.vectorization.base import VectorizerEngine
from app.vectorization.compose import compose_integral, compose_layered, snap_fills_to_palette

log = logging.getLogger("vectorlab.pipeline")

ProgressFn = Callable[[str, float], None]
OUTLINE_SNAP_MAX_DE = 12.0
SUPERSAMPLE_TARGET_SIDE = 1600  # auto: ampliar hasta que el lado mayor trazado alcance ~este valor
SUPERSAMPLE_MAX_FACTOR = 4
SUPERSAMPLE_MAX_PIXELS = 4_000_000  # píxeles trazados como máximo en modo auto


def supersample_factor(requested: int, width: int, height: int, max_pixels: int) -> int:
    """Factor de sobremuestreo efectivo. 0 = auto; un valor explícito solo se limita por `max_pixels`."""
    n = width * height
    if requested == 0:
        k = min(SUPERSAMPLE_MAX_FACTOR, max(1, math.floor(SUPERSAMPLE_TARGET_SIDE / max(width, height))))
        while k > 1 and n * k * k > SUPERSAMPLE_MAX_PIXELS:
            k -= 1
        return k
    k = requested
    while k > 1 and n * k * k > max_pixels:
        k -= 1
    return k


@dataclass
class TraceInputs:
    """Lo que recibe el motor, a la resolución de trazado (×k si hay sobremuestreo)."""

    target_rgba: np.ndarray
    base_labels: np.ndarray
    outline_mask: np.ndarray | None
    opaque: np.ndarray
    factor: int
    out_size: tuple[int, int]  # tamaño del documento SVG (el de la entrada)


@dataclass(frozen=True)
class Candidate:
    strategy: str
    curve_mode: str

    @property
    def id(self) -> str:
        return f"{self.strategy}_{self.curve_mode}"


def plan_candidates(p: VectorizeParams, outlines: OutlineResult) -> tuple[list[Candidate], list[str]]:
    warnings: list[str] = []
    curves = ["spline", "polygon"] if p.curve_mode is CurveMode.auto else [p.curve_mode.value]
    if p.strategy is Strategy.integral:
        strategies = ["integral"]
    elif p.strategy is Strategy.layered:
        if outlines.usable_for_layering:
            strategies = ["layered"]
        else:
            strategies = ["integral"]
            warnings.append("Se solicitó trazado por capas pero no se detectaron contornos suficientes; "
                            "se aplicó trazado integral.")
    else:
        strategies = ["integral"] + (["layered"] if outlines.usable_for_layering else [])
    combos = [Candidate(s, c) for c in curves for s in strategies]
    if len(combos) > p.candidate_budget:
        skipped = ", ".join(c.id for c in combos[p.candidate_budget:])
        warnings.append(f"Presupuesto de {p.candidate_budget} candidato(s): no se evaluaron {skipped}.")
        combos = combos[:p.candidate_budget]
    return combos, warnings


def _snap_outline_color(palette: PaletteResult, outlines: OutlineResult, max_colors: int,
                        notes: list[str]) -> int | None:
    """Índice de paleta para el color de contorno (existente o añadido si hay hueco)."""
    if outlines.color is None:
        return None
    pal_lab = rgb_to_lab(palette.palette[:, None, :]).reshape(-1, 3)
    c_lab = rgb_to_lab(np.array([[outlines.color]], np.uint8)).reshape(3)
    dist = np.linalg.norm(pal_lab - c_lab, axis=1)
    best = int(dist.argmin())
    if dist[best] <= OUTLINE_SNAP_MAX_DE or len(palette.palette) >= max_colors:
        if dist[best] > OUTLINE_SNAP_MAX_DE:
            notes.append(f"Paleta llena: el color de contorno {to_hex(outlines.color)} se aproxima a "
                         f"{to_hex(palette.palette[best])} (ΔE {dist[best]:.1f}).")
        return best
    palette.palette = np.vstack([palette.palette, np.array(outlines.color, np.uint8)])
    palette.counts = np.append(palette.counts, 0)
    palette.protected = np.append(palette.protected, True)
    notes.append(f"Color de contorno {to_hex(outlines.color)} añadido a la paleta.")
    return len(palette.palette) - 1


class PipelineRunner:
    def __init__(self, settings: Settings, engine: VectorizerEngine) -> None:
        self.settings = settings
        self.engine = engine

    def run(self, data: bytes, params: VectorizeParams, workdir: Path, progress: ProgressFn,
            cancel: threading.Event) -> dict[str, Any]:
        timings: dict[str, float] = {}
        warnings: list[str] = []
        notes: list[str] = []
        t_start = time.perf_counter()

        def stage(name: str, pct: float) -> float:
            if cancel.is_set():
                raise JobCancelledError("Trabajo cancelado por el usuario.")
            progress(name, pct)
            return time.perf_counter()

        t = stage("decodificación", 5)
        img: DecodedImage = decode(data, self.settings)
        notes.extend(img.notes)
        timings["decode"] = time.perf_counter() - t

        t = stage("normalización", 10)
        alpha = apply_alpha_policy(img.rgba, params.preserve_alpha, params.alpha_threshold)
        warnings.extend(alpha.notes)
        notes.extend(alpha.info)
        opaque = alpha.opaque
        if img.lossy and params.denoise_lossy:
            alpha.rgb = denoise_lossy(alpha.rgb)
            notes.append("Entrada con pérdida: filtro mean-shift (radio 3 px, color 18) para atenuar artefactos.")
        bg = detect_background(alpha.rgb, opaque, params.background_tolerance)
        removed = 0
        if params.background_mode is BackgroundMode.remove_uniform:
            if bg.uniform:
                opaque, removed = remove_uniform_background(alpha.rgb, opaque, bg, params.background_tolerance)
                notes.append(f"Fondo {to_hex(bg.color)} eliminado ({removed:,} px).")  # type: ignore[arg-type]
            else:
                warnings.append(f"No se eliminó el fondo: el borde no es uniforme "
                                f"({bg.border_share:.0%} cerca del color dominante; se requiere ≥60 %).")
        timings["normalize"] = time.perf_counter() - t

        t = stage("paleta", 20)
        palette = quantize(alpha.rgb, opaque, params.max_colors, params.detail_preservation, img.lossy)
        notes.extend(palette.notes)
        timings["palette"] = time.perf_counter() - t

        t = stage("contornos", 32)
        outlines = detect_outlines(alpha.rgb, opaque, params.outline_emphasis)
        notes.extend(outlines.decisions)
        base_labels = palette.labels
        target_labels = base_labels
        outline_rgb: tuple[int, int, int] | None = None
        if outlines.mask is not None and outlines.mask.any():
            idx = _snap_outline_color(palette, outlines, params.max_colors, notes)
            if idx is not None:
                target_labels = base_labels.copy()
                target_labels[outlines.mask] = idx
                outline_rgb = tuple(int(v) for v in palette.palette[idx])  # type: ignore[assignment]
        timings["outlines"] = time.perf_counter() - t

        target_rgba = PaletteResult(target_labels, palette.palette, palette.counts, palette.protected,
                                    palette.method, palette.source_colors).image(opaque)
        (workdir / "preprocessed.png").write_bytes(encode_png(target_rgba))

        t = stage("sobremuestreo", 36)
        factor = supersample_factor(params.supersample, img.width, img.height, self.settings.max_pixels)
        inputs = TraceInputs(target_rgba, base_labels, outlines.mask, opaque, 1, (img.width, img.height))
        if factor > 1:
            inputs = self._supersample(img, alpha.rgb, opaque, params, palette, target_labels, base_labels,
                                       outlines.mask, outline_rgb, factor)
            notes.append(f"Sobremuestreo ×{factor}: trazado a {img.width * factor}×{img.height * factor} px con "
                         "etiquetas de la paleta elegidas por color entre las vecinas; el SVG conserva "
                         f"{img.width}×{img.height} (viewBox ×{factor}).")
        timings["supersample"] = time.perf_counter() - t

        candidates, plan_warnings = plan_candidates(params, outlines)
        warnings.extend(plan_warnings)
        comparison = self._comparison_data(img, target_labels, palette.palette, params)

        results: list[dict[str, Any]] = []
        span = 55.0 / max(1, len(candidates))
        for i, cand in enumerate(candidates):
            t = stage(f"trazado {cand.id}", 40 + i * span)
            results.append(self._run_candidate(cand, params, img, inputs, palette, outline_rgb, comparison,
                                               workdir, cancel))
            timings[f"candidate_{cand.id}"] = time.perf_counter() - t

        t = stage("selección y exportación", 96)
        chosen = max(results, key=lambda r: r["metrics"]["score"]) if params.visual_validation else results[0]
        for r in results:
            r["selected"] = r is chosen
        svg_text = (workdir / "candidates" / f"{chosen['id']}.svg").read_text()
        (workdir / "result.svg").write_text(svg_text)
        preview = render_svg(svg_text, img.width, img.height)
        (workdir / "preview.png").write_bytes(encode_png(preview))
        timings["export"] = time.perf_counter() - t
        timings["total"] = time.perf_counter() - t_start

        if chosen["off_palette_fills_snapped"]:
            notes.append(f"{len(chosen['off_palette_fills_snapped'])} colores de relleno promediados por el motor "
                         "se ajustaron al color de paleta más cercano.")
        warnings.extend(self._quality_warnings(chosen, params, palette))
        effective = {
            "profile": params.profile,
            "engine": {"name": self.engine.name, "version": self.engine.version},
            "vectorlab_version": __version__,
            "selected_candidate": chosen["id"],
            "supersample_factor": factor,
            "native_params": {r["id"]: r["native_params"] for r in results},
            "native_param_sources": results[0]["native_param_sources"],
            "preprocessing": {
                "alpha": {"preserve_alpha": params.preserve_alpha, "threshold": params.alpha_threshold,
                          "partial_alpha_pixels": alpha.partial_alpha_pixels},
                "background": {"mode": params.background_mode.value,
                               "detected_color": to_hex(bg.color) if bg.color else None,
                               "border_share": round(bg.border_share, 4), "uniform": bg.uniform,
                               "removed_pixels": removed},
                "palette": {"method": palette.method, "colors": len(palette.palette),
                            "limit": params.max_colors, "entries": palette.describe()},
                "outlines": {"enabled": outlines.enabled, "color": to_hex(outlines.color) if outlines.color else None,
                             "usable_for_layering": outlines.usable_for_layering, **outlines.stats,
                             "policy": outlines.policy.__dict__ if outlines.policy else None},
            },
        }
        report = {
            "input": {"format": img.format, "width": img.width, "height": img.height, "has_alpha": img.has_alpha,
                      "lossy": img.lossy, "bytes": len(data), "source_colors": palette.source_colors},
            "requested_params": params.model_dump(mode="json"),
            "effective_params": effective,
            "candidates": results,
            "selected_candidate": chosen["id"],
            "metrics": chosen["metrics"],
            "svg": chosen["svg_report"],
            "timings_s": {k: round(v, 3) for k, v in timings.items()},
            "warnings": warnings,
            "notes": notes,
        }
        (workdir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        log.info("pipeline completado candidato=%s score=%s total=%.2fs", chosen["id"],
                 chosen["metrics"].get("score"), timings["total"])
        return report

    def _comparison_data(self, img: DecodedImage, labels: np.ndarray, palette: np.ndarray,
                         params: VectorizeParams) -> ComparisonData:
        n = img.width * img.height
        scale = min(1.0, math.sqrt(self.settings.metrics_max_pixels / n))
        original = np.asarray(img.rgba)
        if scale < 1.0:
            size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
            original = cv2.resize(original, size, interpolation=cv2.INTER_AREA)
            labels = cv2.resize(labels, size, interpolation=cv2.INTER_NEAREST)
        return ComparisonData(original=original, target_labels=labels, palette=palette, scale=scale,
                              check_alpha=img.has_alpha and params.preserve_alpha,
                              outline_emphasis=params.outline_emphasis)

    @staticmethod
    def _supersample(img: DecodedImage, rgb: np.ndarray, opaque: np.ndarray, params: VectorizeParams,
                     palette: PaletteResult, target_labels: np.ndarray, base_labels: np.ndarray,
                     outline_mask: np.ndarray | None, outline_rgb: tuple[int, int, int] | None,
                     k: int) -> TraceInputs:
        src = np.array(img.rgba)
        # Color normalizado (y filtrado si hubo pérdida) en lo opaco; el original en los bordes semitransparentes.
        src[..., :3] = np.where(opaque[..., None], rgb, src[..., :3])
        if params.preserve_alpha:
            src[..., 3] = np.where(opaque | (src[..., 3] < params.alpha_threshold), src[..., 3], 0)  # fondo eliminado
            threshold: int | None = params.alpha_threshold
        else:
            src[..., 3] = 255
            threshold = None
        up = upscale_rgba(src, k)
        pal = palette.palette
        has_lines = outline_mask is not None and outline_rgb is not None and bool(outline_mask.any())
        if has_lines:
            # El contorno es una etiqueta propia (K) para poder recuperar su máscara a resolución ×k.
            pal = np.vstack([pal, np.array(outline_rgb, np.uint8)])
            line_label = len(palette.palette)
            aug = np.where(outline_mask, line_label, target_labels).astype(np.int32)
        else:
            aug = target_labels
        aug_up = supersample_labels(aug, pal, up, k, threshold)
        mask_up = (aug_up == line_label) if has_lines else None
        target_up = aug_up
        if mask_up is not None:
            target_up = aug_up.copy()
            outline_idx = int(target_labels[outline_mask][0])
            target_up[mask_up] = outline_idx
        base_up = supersample_labels(base_labels, palette.palette, up, k, threshold) if has_lines else target_up
        opaque_up = target_up >= 0
        base_up = np.where(opaque_up, base_up, -1)
        rgba_up = PaletteResult(target_up, palette.palette, palette.counts, palette.protected,
                                palette.method, palette.source_colors).image(opaque_up)
        return TraceInputs(rgba_up, base_up, mask_up, opaque_up, k, (img.width, img.height))

    def _run_candidate(self, cand: Candidate, params: VectorizeParams, img: DecodedImage, inputs: TraceInputs,
                       palette: PaletteResult, outline_rgb: tuple[int, int, int] | None,
                       comparison: ComparisonData, workdir: Path, cancel: threading.Event) -> dict[str, Any]:
        config, sources = derive_engine_config(params, cand.curve_mode, inputs.factor)
        comment = (f"VectorLab {__version__} | {params.profile} | {self.engine.name} {self.engine.version} | "
                   f"candidato {cand.id}")
        t0 = time.perf_counter()
        mask = inputs.outline_mask
        if cand.strategy == "layered" and mask is not None and outline_rgb is not None:
            fill_labels = nearest_fill(inputs.base_labels, mask)
            fill_rgba = PaletteResult(fill_labels, palette.palette, palette.counts, palette.protected,
                                      palette.method, palette.source_colors).image(inputs.opaque | mask)
            # Bajo los contornos de la silueta el relleno vecino puede ser transparente: se respeta.
            fill_rgba[fill_labels < 0, 3] = 0
            svg, traces = compose_layered(self.engine, fill_rgba, mask, outline_rgb, config, comment,
                                          inputs.out_size)
        else:
            trace = self.engine.trace(inputs.target_rgba, config)
            svg = compose_integral(trace, comment, inputs.out_size)
            traces = [trace]
        trace_s = time.perf_counter() - t0
        svg, snapped = snap_fills_to_palette(svg, palette.palette)
        if cancel.is_set():
            raise JobCancelledError("Trabajo cancelado por el usuario.")
        svg_report = inspect_svg(svg, (img.width, img.height))
        (workdir / "candidates" / f"{cand.id}.svg").write_text(svg)

        metrics: dict[str, Any] = {"score": None}
        if params.visual_validation:
            cw, ch = comparison.original.shape[1], comparison.original.shape[0]
            render = render_svg(svg, cw, ch)
            metrics = compute_metrics(comparison, render)
        return {"id": cand.id, "strategy": cand.strategy, "curve_mode": cand.curve_mode,
                "native_params": traces[0].native_params, "native_param_sources": sources,
                "trace_seconds": round(trace_s, 3), "svg_report": svg_report.to_dict(), "metrics": metrics,
                "off_palette_fills_snapped": snapped,
                "selected": False}

    @staticmethod
    def _quality_warnings(chosen: dict[str, Any], params: VectorizeParams, palette: PaletteResult) -> list[str]:
        out: list[str] = []
        svg = chosen["svg_report"]
        if svg["fill_colors"] > params.max_colors:
            out.append(f"El SVG usa {svg['fill_colors']} colores de relleno, más que el límite "
                       f"{params.max_colors}: VTracer no garantiza un límite estricto.")
        m = chosen["metrics"]
        if m.get("small_components_lost"):
            out.append(f"Se perdieron {m['small_components_lost']} de {m['small_components_total']} detalles "
                       "pequeños (ver lista de pérdidas).")
        if m.get("ssim") is not None and m["ssim"] < 0.85:
            out.append(f"SSIM bajo ({m['ssim']}): revise la comparación visual.")
        return out
