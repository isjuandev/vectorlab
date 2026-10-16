"""Métricas de fidelidad entre la imagen original y el SVG renderizado.

Todas las comparaciones se hacen sobre representaciones comparables: mismas dimensiones (la de
comparación), composición sobre blanco para métricas de color/estructura, y canal alfa evaluado
por separado. Ninguna métrica individual demuestra fidelidad absoluta.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from scipy import ndimage
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity

from app.preprocessing.color import nearest_index, rgb_to_lab, to_hex
from app.preprocessing.labels import components
from app.preprocessing.outlines import OutlinePolicy, dark_mask

DELTA_E_SAMPLE = 600_000
MIN_COMPONENT_AREA = 2
MAX_LOSS_REPORT = 25

# Pesos de la puntuación de selección de candidatos (documentados en docs/metrics.md).
SCORE_WEIGHTS = {"ssim": 0.35, "region_agreement": 0.30, "edge_f1": 0.20, "color": 0.15}
LOST_PENALTY = 0.10


@dataclass
class ComparisonData:
    original: np.ndarray  # HxWx4 uint8 (imagen decodificada, sin preprocesar)
    target_labels: np.ndarray  # HxW int32 (-1 transparente): lo que recibió el motor
    palette: np.ndarray  # Kx3 uint8
    scale: float  # tamaño de comparación / tamaño original
    check_alpha: bool
    outline_emphasis: int


def over_white(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    return (rgba[..., :3].astype(np.float32) * a + 255.0 * (1.0 - a)).round().astype(np.uint8)


def _iou(a: np.ndarray, b: np.ndarray) -> float | None:
    union = int((a | b).sum())
    return None if union == 0 else round(float((a & b).sum()) / union, 4)


def _label_render(render: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Asigna cada píxel renderizado opaco al color de paleta más cercano (−1 si transparente)."""
    out = np.full(render.shape[:2], -1, np.int32)
    opaque = render[..., 3] >= 128
    if not opaque.any() or len(palette) == 0:
        return out
    px = render[..., :3][opaque]
    packed = (px[:, 0].astype(np.int64) << 16) | (px[:, 1].astype(np.int64) << 8) | px[:, 2]
    uniq, inv = np.unique(packed, return_inverse=True)
    uniq_rgb = np.stack([(uniq >> 16) & 255, (uniq >> 8) & 255, uniq & 255], 1).astype(np.uint8)
    lut = nearest_index(rgb_to_lab(uniq_rgb[:, None, :]).reshape(-1, 3),
                        rgb_to_lab(palette[:, None, :]).reshape(-1, 3))
    out[opaque] = lut[inv.reshape(-1)]
    return out


def _edge_metrics(gray_o: np.ndarray, gray_r: np.ndarray) -> dict:
    e_o = cv2.Canny(gray_o, 50, 150) > 0
    e_r = cv2.Canny(gray_r, 50, 150) > 0
    if not e_o.any() or not e_r.any():
        return {"edge_mean_distance_px": None, "edge_recall_1_5px": None, "edge_precision_1_5px": None,
                "edge_f1": None}
    dt_r = cv2.distanceTransform((~e_r).astype(np.uint8), cv2.DIST_L2, 5)
    dt_o = cv2.distanceTransform((~e_o).astype(np.uint8), cv2.DIST_L2, 5)
    d_or = dt_r[e_o]
    d_ro = dt_o[e_r]
    recall = float((d_or <= 1.5).mean())
    precision = float((d_ro <= 1.5).mean())
    f1 = 0.0 if recall + precision == 0 else 2 * recall * precision / (recall + precision)
    return {"edge_mean_distance_px": round(float((d_or.mean() + d_ro.mean()) / 2), 3),
            "edge_recall_1_5px": round(recall, 4), "edge_precision_1_5px": round(precision, 4),
            "edge_f1": round(f1, 4)}


def _delta_e(comp_o: np.ndarray, comp_r: np.ndarray, valid: np.ndarray, interior: np.ndarray) -> dict:
    idx = np.flatnonzero(valid)
    if idx.size == 0:
        return {"delta_e_mean": None, "delta_e_p95": None, "delta_e_interior_mean": None, "delta_e_sampled": False}
    sampled = idx.size > DELTA_E_SAMPLE
    if sampled:
        idx = np.random.default_rng(0).choice(idx, DELTA_E_SAMPLE, replace=False)
    a = rgb2lab(comp_o.reshape(-1, 3)[idx][:, None, :] / 255.0)
    b = rgb2lab(comp_r.reshape(-1, 3)[idx][:, None, :] / 255.0)
    de = deltaE_ciede2000(a, b).reshape(-1)
    inner = interior.reshape(-1)[idx]
    return {"delta_e_mean": round(float(de.mean()), 3), "delta_e_p95": round(float(np.percentile(de, 95)), 3),
            "delta_e_interior_mean": round(float(de[inner].mean()), 3) if inner.any() else None,
            "delta_e_sampled": sampled}


def _components(target: np.ndarray, rendered: np.ndarray, palette: np.ndarray, scale: float) -> dict:
    """Componentes conexas del mapa objetivo y si sobreviven en el render (≥50 % de sus píxeles)."""
    comp, n = components(target)
    small_limit = max(16, int(0.0005 * target.size))
    if n == 0:
        return {"components_total": 0, "components_preserved": 0, "components_lost": 0,
                "small_components_total": 0, "small_components_lost": 0,
                "small_component_max_area_px": int(round(small_limit / scale / scale)), "lost_components": []}
    area = np.bincount(comp.ravel(), minlength=n + 1)
    matched = np.bincount(comp[(target == rendered) & (comp > 0)], minlength=n + 1)
    ids = np.arange(n + 1)
    evaluable = (ids > 0) & (area >= MIN_COMPONENT_AREA)
    lost = evaluable & (matched < 0.5 * area)
    small = evaluable & (area <= small_limit)
    slices = ndimage.find_objects(comp)
    inv = 1.0 / scale
    losses: list[dict] = []
    for i in np.flatnonzero(lost):
        sl = slices[i - 1]
        y, x = sl[0].start, sl[1].start
        h, w = sl[0].stop - y, sl[1].stop - x
        k = int(target[sl][comp[sl] == i][0])
        losses.append({"color": to_hex(palette[k]), "area_px": int(round(area[i] * inv * inv)),
                       "bbox": [int(x * inv), int(y * inv), max(1, int(w * inv)), max(1, int(h * inv))],
                       "matched_share": round(float(matched[i] / area[i]), 3), "small": bool(small[i])})
    losses.sort(key=lambda r: -r["area_px"])
    total = int(evaluable.sum())
    return {"components_total": total, "components_preserved": total - int(lost.sum()),
            "components_lost": int(lost.sum()), "small_components_total": int(small.sum()),
            "small_components_lost": int((small & lost).sum()),
            "small_component_max_area_px": int(round(small_limit * inv * inv)),
            "lost_components": losses[:MAX_LOSS_REPORT]}


def compute_metrics(data: ComparisonData, render: np.ndarray) -> dict:
    comp_o = over_white(data.original)
    comp_r = over_white(render)
    gray_o = cv2.cvtColor(comp_o, cv2.COLOR_RGB2GRAY)
    gray_r = cv2.cvtColor(comp_r, cv2.COLOR_RGB2GRAY)
    alpha_o = data.original[..., 3] >= 128
    alpha_r = render[..., 3] >= 128

    out: dict = {"comparison_size": [int(gray_o.shape[1]), int(gray_o.shape[0])],
                 "comparison_scale": round(data.scale, 4)}
    out["ssim"] = round(float(structural_similarity(gray_o, gray_r, data_range=255)), 4)
    out["alpha_iou"] = _iou(alpha_o, alpha_r) if data.check_alpha else None

    edges = cv2.Canny(gray_o, 50, 150) > 0
    band = cv2.dilate(edges.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    valid = (alpha_o & alpha_r) if data.check_alpha else np.ones_like(alpha_o)
    out.update(_delta_e(comp_o, comp_r, valid, ~band))
    out.update(_edge_metrics(gray_o, gray_r))

    rendered_labels = _label_render(render, data.palette)
    considered = (data.target_labels >= 0) | (rendered_labels >= 0)
    if considered.any():
        agree = data.target_labels[considered] == rendered_labels[considered]
        out["region_agreement"] = round(float(agree.mean()), 4)
        ious = [_iou(data.target_labels == k, rendered_labels == k)
                for k in np.unique(data.target_labels) if k >= 0 and (data.target_labels == k).sum() >= 16]
        ious = [v for v in ious if v is not None]
        out["region_mean_iou"] = round(float(np.mean(ious)), 4) if ious else None
    else:
        out["region_agreement"] = out["region_mean_iou"] = None

    if data.outline_emphasis > 0:
        everywhere = np.ones_like(alpha_o)
        l_o = rgb_to_lab(comp_o)[..., 0]
        opq_o = alpha_o if data.check_alpha else everywhere
        policy = OutlinePolicy.for_image(data.outline_emphasis, l_o, opq_o)  # misma política para ambos
        m_o = dark_mask(l_o, opq_o, policy)
        m_r = dark_mask(rgb_to_lab(comp_r)[..., 0], alpha_r if data.check_alpha else everywhere, policy)
        out["outline_iou"] = _iou(m_o, m_r)
    else:
        out["outline_iou"] = None

    out.update(_components(data.target_labels, rendered_labels, data.palette, data.scale))
    out["score"] = selection_score(out)
    return out


def selection_score(m: dict) -> float:
    """Puntuación compuesta SOLO para ordenar candidatos de un mismo trabajo."""
    ssim = m.get("ssim") or 0.0
    region = m.get("region_agreement") or 0.0
    f1 = m.get("edge_f1") or 0.0
    de = m.get("delta_e_mean")
    color = 0.0 if de is None else 1.0 - min(1.0, de / 10.0)
    total = max(1, m.get("components_total") or 0)
    lost_ratio = (m.get("components_lost") or 0) / total
    s = (SCORE_WEIGHTS["ssim"] * ssim + SCORE_WEIGHTS["region_agreement"] * region
         + SCORE_WEIGHTS["edge_f1"] * f1 + SCORE_WEIGHTS["color"] * color - LOST_PENALTY * lost_ratio)
    return round(max(0.0, min(1.0, s)), 4)
