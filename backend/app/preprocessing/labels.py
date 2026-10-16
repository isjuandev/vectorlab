"""Operaciones sobre mapas de etiquetas de paleta (−1 = transparente)."""

from __future__ import annotations

import cv2
import numpy as np
from skimage.measure import label as cc_label


def nearest_fill(labels: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Sustituye los píxeles de `mask` por la etiqueta del píxel fuera de `mask` más cercano.

    Usa la transformada de distancia con etiquetas (vecino exacto, sin mezclar colores).
    """
    if not mask.any() or mask.all():
        return labels
    # OpenCV mide la distancia de cada píxel no nulo al píxel nulo más cercano y numera los píxeles
    # nulos 1..N en orden de barrido por filas.
    _, nearest = cv2.distanceTransformWithLabels(mask.astype(np.uint8), cv2.DIST_L2, 5,
                                                 labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(~mask)
    out = labels.copy()
    out[mask] = labels[ys, xs][nearest[mask] - 1]
    return out


def components(labels: np.ndarray) -> tuple[np.ndarray, int]:
    """Componentes conexas (8-vecindad) de píxeles con la misma etiqueta. 0 = transparente."""
    comp = cc_label(labels + 1, background=0, connectivity=2)
    return comp.astype(np.int32), int(comp.max())


EXTREMUM_MARGIN = 5.0  # L*: un fragmento debe ser al menos así de más oscuro/claro que todos sus vecinos


def _extremum_fragments(comp: np.ndarray, candidates: np.ndarray, labels: np.ndarray, label_l: np.ndarray,
                        n: int) -> np.ndarray:
    """Componentes candidatas cuya L* es extrema (menor o mayor) frente a TODAS sus vecinas opacas."""
    lo = np.full(n + 1, np.inf)
    hi = np.full(n + 1, -np.inf)
    h, w = comp.shape
    ys, xs = np.nonzero(candidates)
    cid = comp[ys, xs]
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == dx == 0:
                continue
            ny, nx = ys + dy, xs + dx
            ok = (ny >= 0) & (ny < h) & (nx >= 0) & (nx < w)
            ny, nx, c = ny[ok], nx[ok], cid[ok]
            nl = labels[ny, nx]
            other = (comp[ny, nx] != c) & (nl >= 0)
            vals = label_l[nl[other]]
            np.minimum.at(lo, c[other], vals)
            np.maximum.at(hi, c[other], vals)
    own = np.full(n + 1, np.nan)
    own[cid] = label_l[labels[ys, xs]]
    has_nb = np.isfinite(lo)
    darker = own < lo - EXTREMUM_MARGIN
    lighter = own > hi + EXTREMUM_MARGIN
    return has_nb & (darker | lighter)


def _reassign_by_color(labels: np.ndarray, sliver: np.ndarray, pixel_lab: np.ndarray,
                       label_lab: np.ndarray) -> np.ndarray:
    """Cada píxel de astilla toma, entre las etiquetas vecinas (3×3) que no son astilla, la de color más
    parecido al suyo. Un píxel de antialiasing entre un mechón claro y pelo negro va con el que más
    cubría. Devuelve las etiquetas con −2 donde no había vecino válido."""
    h, w = labels.shape
    ys, xs = np.nonzero(sliver)
    own = pixel_lab[ys, xs]
    best = np.full(len(ys), -2, np.int32)
    best_d = np.full(len(ys), np.inf, np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == dx == 0:
                continue
            ny, nx = np.clip(ys + dy, 0, h - 1), np.clip(xs + dx, 0, w - 1)
            cand = labels[ny, nx]
            ok = (cand >= 0) & ~sliver[ny, nx]
            d = np.full(len(ys), np.inf, np.float32)
            d[ok] = np.linalg.norm(own[ok] - label_lab[cand[ok]], axis=1)
            better = d < best_d
            best[better] = cand[better]
            best_d[better] = d[better]
    out = labels.copy()
    out[ys, xs] = best
    return out


def clean_slivers(labels: np.ndarray, flat: np.ndarray, opaque: np.ndarray, max_area: int,
                  label_l: np.ndarray | None = None, pixel_lab: np.ndarray | None = None,
                  label_lab: np.ndarray | None = None) -> tuple[np.ndarray, int]:
    """Reasigna astillas de antialiasing a la región vecina.

    Una astilla es una componente de ≤ max_area píxeles sin ningún píxel «plano» y con un tono
    intermedio entre sus vecinas: es una transición entre regiones. Se conservan:
    * los rasgos pequeños con interior plano (pecas, brillos, pupilas);
    * los fragmentos más oscuros o más claros que todas sus vecinas (si se da `label_l`, la L* de cada
      etiqueta): son trozos de una línea fina partida por la cuantización (nariz, párpados, mechones).
    """
    if max_area <= 0:
        return labels, 0
    comp, n = components(labels)
    if n == 0:
        return labels, 0
    area = np.bincount(comp.ravel(), minlength=n + 1)
    has_flat = np.bincount(comp[flat & opaque], minlength=n + 1) > 0
    sliver_ids = (area <= max_area) & ~has_flat
    sliver_ids[0] = False
    if label_l is not None and sliver_ids.any():
        sliver_ids &= ~_extremum_fragments(comp, sliver_ids[comp], labels, label_l, n)
    sliver = sliver_ids[comp]
    if not sliver.any():
        return labels, 0
    pending = sliver
    if pixel_lab is not None and label_lab is not None:
        labels = _reassign_by_color(labels, sliver, pixel_lab, label_lab)
        pending = labels == -2
    # Resto (sin vecino válido): vecino opaco no-astilla más cercano; la transparencia se restaura después.
    out = nearest_fill(labels, pending | ~opaque)
    out[~opaque] = -1
    return out, int(sliver_ids.sum())
