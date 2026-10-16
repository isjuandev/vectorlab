"""Análisis y reducción de paleta con protección de colores minoritarios.

Política (documentada en docs/controls.md):
1. Si los colores exactos de la imagen ya caben en `max_colors`, no se cuantiza.
2. Los centros se ajustan solo sobre píxeles "planos" (variación local baja), de modo que los
   píxeles de antialiasing entre un contorno y un relleno no generen colores intermedios propios.
3. Una fracción del presupuesto (proporcional a la conservación de detalles) se reserva para
   colores minoritarios: regiones planas cuyo error respecto a la paleta principal supera un umbral.
4. Se fusionan centros casi idénticos (ΔE76 < merge_tol) para no gastar presupuesto en ruido.
5. Todos los píxeles opacos se asignan al centro más cercano en CIELAB.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.preprocessing.color import nearest_index, rgb_to_lab, to_hex
from app.preprocessing.labels import clean_slivers

SAMPLE_CAP = 250_000
BLEND_SAMPLE_CAP = 20_000  # colores únicos no planos analizados como posibles mezclas
LOSSY_MERGE_EXTRA = 4.0  # ΔE76 añadido a la tolerancia de fusión con entradas con pérdida


@dataclass
class PaletteResult:
    labels: np.ndarray  # HxW int32; -1 = transparente
    palette: np.ndarray  # Kx3 uint8 (sRGB)
    counts: np.ndarray  # K int64
    protected: np.ndarray  # K bool – colores añadidos por la protección de minorías
    method: str  # "exact" | "kmeans"
    source_colors: int
    notes: list[str] = field(default_factory=list)

    def image(self, opaque: np.ndarray) -> np.ndarray:
        """Imagen RGBA preprocesada (alfa binario)."""
        h, w = self.labels.shape
        out = np.zeros((h, w, 4), np.uint8)
        idx = np.clip(self.labels, 0, None)
        out[..., :3] = self.palette[idx]
        out[..., 3] = np.where(opaque, 255, 0)
        out[~opaque, :3] = 0
        return out

    def describe(self) -> list[dict]:
        order = np.argsort(-self.counts)
        total = max(1, int(self.counts.sum()))
        return [{"index": int(i), "hex": to_hex(self.palette[i]), "pixels": int(self.counts[i]),
                 "share": round(float(self.counts[i]) / total, 6), "protected": bool(self.protected[i])}
                for i in order]


def _pack(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., 0].astype(np.int64) << 16) | (rgb[..., 1].astype(np.int64) << 8) | rgb[..., 2]


def count_colors(rgb: np.ndarray, mask: np.ndarray) -> int:
    return int(np.unique(_pack(rgb[mask])).size) if mask.any() else 0


def flat_mask(rgb: np.ndarray, tol: int) -> np.ndarray:
    """Píxeles cuyo vecindario 3x3 varía como máximo `tol` niveles en cada canal."""
    k = np.ones((3, 3), np.uint8)
    rng = np.zeros(rgb.shape[:2], np.int16)
    for c in range(3):
        ch = rgb[..., c]
        rng = np.maximum(rng, cv2.dilate(ch, k).astype(np.int16) - cv2.erode(ch, k).astype(np.int16))
    return rng <= tol


def _kmeans(lab: np.ndarray, k: int, seed: int = 0) -> np.ndarray:
    k = max(1, min(k, len(lab)))
    cv2.setRNGSeed(seed)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.2)
    _, _, centers = cv2.kmeans(lab.astype(np.float32), k, None, criteria, 1, cv2.KMEANS_PP_CENTERS)
    return centers


def _blend_residual(rgb_points: np.ndarray, centers_lab: np.ndarray) -> np.ndarray:
    """ΔE76 entre cada color y la mezcla lineal (sRGB) más cercana de dos centros de la paleta.

    El antialiasing produce mezclas de los dos colores que separa; un color que no se explica como mezcla
    (p. ej. una línea roja de 1–2 px, sin ningún píxel «plano») es un color real que falta en la paleta.
    """
    centers = _lab_to_rgb(centers_lab).astype(np.float32)
    p = rgb_points.astype(np.float32)
    p_lab = rgb_to_lab(rgb_points[:, None, :]).reshape(-1, 3)
    best = np.full(len(p), np.inf, np.float32)
    k = len(centers)
    for i in range(k):
        a = centers[i]
        seg = centers[i + 1:] - a  # (m,3)
        if not len(seg):
            continue
        den = np.maximum((seg ** 2).sum(1), 1e-6)
        t = np.clip(((p - a) @ seg.T) / den, 0.0, 1.0)  # (n,m)
        q = a + t[..., None] * seg[None]  # (n,m,3)
        q_lab = rgb_to_lab(np.clip(np.round(q), 0, 255).astype(np.uint8))
        best = np.minimum(best, np.linalg.norm(q_lab - p_lab[:, None, :], axis=2).min(1))
    return best


def _merge_close(centers: np.ndarray, weights: np.ndarray, tol: float) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(-weights)
    kept: list[np.ndarray] = []
    kept_w: list[float] = []
    for i in order:
        c = centers[i]
        if kept:
            d = np.linalg.norm(np.array(kept) - c, axis=1)
            j = int(d.argmin())
            if d[j] < tol:
                kept_w[j] += float(weights[i])
                continue
        kept.append(c)
        kept_w.append(float(weights[i]))
    return np.array(kept, np.float32), np.array(kept_w)


def _lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    rgb = cv2.cvtColor(lab.reshape(-1, 1, 3).astype(np.float32), cv2.COLOR_LAB2RGB).reshape(-1, 3)
    return np.clip(np.round(rgb * 255.0), 0, 255).astype(np.uint8)


def _snap_to_source(rgb: np.ndarray, flat: np.ndarray, labels: np.ndarray, palette: np.ndarray,
                    lossy: bool) -> np.ndarray:
    """Sustituye cada centro por un color real de su región plana.

    Sin pérdida: el color exacto más frecuente (moda). Con pérdida: la media RGB, que atenúa el ruido.
    """
    sel = flat & (labels >= 0)
    if not sel.any():
        return palette
    lbl = labels[sel].astype(np.int64)
    out = palette.copy()
    if lossy:
        px = rgb[sel].astype(np.float64)
        n = np.bincount(lbl, minlength=len(palette))
        for c in range(3):
            s = np.bincount(lbl, weights=px[:, c], minlength=len(palette))
            ok = n > 0
            out[ok, c] = np.clip(np.round(s[ok] / n[ok]), 0, 255).astype(np.uint8)
        return out
    key = (lbl << 24) | _pack(rgb[sel])
    uniq, counts = np.unique(key, return_counts=True)
    owner = uniq >> 24
    order = np.lexsort((-counts, owner))
    first = np.ones(len(order), bool)
    first[1:] = owner[order][1:] != owner[order][:-1]
    for k in uniq[order][first]:
        i = int(k >> 24)
        v = int(k & 0xFFFFFF)
        out[i] = ((v >> 16) & 255, (v >> 8) & 255, v & 255)
    return out


def _merge_duplicates(palette: np.ndarray, labels: np.ndarray, opaque: np.ndarray,
                      protected: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fusiona entradas que acabaron con el mismo color exacto tras el ajuste al origen."""
    uniq, inv = np.unique(palette, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    if len(uniq) == len(palette):
        return palette, labels, protected
    out = labels.copy()
    out[opaque] = inv[labels[opaque]]
    prot = np.zeros(len(uniq), bool)
    np.logical_or.at(prot, inv, protected)
    return uniq.astype(np.uint8), out, prot


def _thin_color_candidates(rgb: np.ndarray, full_lab: np.ndarray, nonflat: np.ndarray, centers: np.ndarray,
                           tol: float, min_area: int) -> list[np.ndarray]:
    """Colores de estructuras finas (sin píxeles planos) que no son mezcla de dos colores de la paleta."""
    if not nonflat.any():
        return []
    far = np.zeros(nonflat.shape, bool)
    lab_nf = full_lab[nonflat]
    far[nonflat] = np.linalg.norm(lab_nf - centers[nearest_index(lab_nf, centers)], axis=1) > tol
    if not far.any():
        return []
    packed = _pack(rgb[far])
    uniq, inv = np.unique(packed, return_inverse=True)
    if len(uniq) > BLEND_SAMPLE_CAP:
        return []  # demasiada variedad (ruido o degradados): no se trata como estructura fina
    uniq_rgb = np.stack([(uniq >> 16) & 255, (uniq >> 8) & 255, uniq & 255], 1).astype(np.uint8)
    unexplained = _blend_residual(uniq_rgb, centers) > tol
    resid = np.zeros(nonflat.shape, np.uint8)
    resid[far] = unexplained[inv.reshape(-1)]
    n, comp, stats, _ = cv2.connectedComponentsWithStats(resid, connectivity=8)
    out = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < min_area:
            continue
        px = full_lab[comp == i]
        err = np.linalg.norm(px - centers[nearest_index(px, centers)], axis=1)
        out.append(px[err >= np.percentile(err, 75)].mean(0))  # núcleo de la línea, no sus bordes mezclados
    return out


def quantize(rgb: np.ndarray, opaque: np.ndarray, max_colors: int, detail: int, lossy: bool,
             seed: int = 0, lossy_merge_extra: float = LOSSY_MERGE_EXTRA) -> PaletteResult:
    h, w = opaque.shape
    labels = np.full((h, w), -1, np.int32)
    notes: list[str] = []
    source_colors = count_colors(rgb, opaque)
    if not opaque.any():
        return PaletteResult(labels, np.zeros((0, 3), np.uint8), np.zeros(0, np.int64), np.zeros(0, bool),
                             "exact", 0, ["La imagen es completamente transparente."])

    if source_colors <= max_colors:
        packed = _pack(rgb[opaque])
        uniq, inv, counts = np.unique(packed, return_inverse=True, return_counts=True)
        palette = np.stack([(uniq >> 16) & 255, (uniq >> 8) & 255, uniq & 255], 1).astype(np.uint8)
        labels[opaque] = inv.astype(np.int32)
        notes.append(f"La imagen tiene {source_colors} colores (≤ {max_colors}): no se cuantiza.")
        return PaletteResult(labels, palette, counts.astype(np.int64), np.zeros(len(palette), bool),
                             "exact", source_colors, notes)

    d = detail / 100.0
    rng = np.random.default_rng(seed)
    flat_tol = 24 if lossy else 12
    flat = flat_mask(rgb, flat_tol) & opaque
    true_flat = flat
    if flat.sum() < 0.05 * opaque.sum():
        flat = opaque
        notes.append("Pocas regiones planas: la paleta se ajusta con todos los píxeles opacos.")

    flat_idx = np.flatnonzero(flat)
    if len(flat_idx) > SAMPLE_CAP:
        flat_idx = rng.choice(flat_idx, SAMPLE_CAP, replace=False)
    sample_lab = rgb_to_lab(rgb.reshape(-1, 3)[flat_idx][:, None, :]).reshape(-1, 3)

    reserve = int(round(max_colors * 0.25 * d)) if max_colors >= 4 else 0
    k_main = max(1, max_colors - reserve)
    centers = _kmeans(sample_lab, k_main, seed)
    merge_tol = 2.0 + 6.0 * (1 - d) + (lossy_merge_extra if lossy else 0.0)
    assign = nearest_index(sample_lab, centers)
    centers, weights = _merge_close(centers, np.bincount(assign, minlength=len(centers)), merge_tol)

    protected_centers = np.zeros((0, 3), np.float32)
    if reserve > 0:
        protect_tol = 14.0 - 6.0 * d  # ΔE76: 8 con detalle 100, 14 con detalle 0
        min_area = 3
        full_lab = rgb_to_lab(rgb)
        flat_lab = full_lab[flat]
        err = np.full((h, w), 0.0, np.float32)
        nearest = nearest_index(flat_lab, centers)
        err[flat] = np.linalg.norm(flat_lab - centers[nearest], axis=1)
        residual = (err > protect_tol).astype(np.uint8)
        n, comp, stats, _ = cv2.connectedComponentsWithStats(residual, connectivity=8)
        means = [full_lab[comp == i].mean(0) for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_area]
        if not lossy:  # con pérdida, los artefactos de compresión tampoco son mezclas: se omitiría ruido como color
            means += _thin_color_candidates(rgb, full_lab, opaque & ~true_flat, centers, protect_tol, min_area)
        if means:
            cand = np.array(means, np.float32)
            k = min(reserve, len(cand))
            protected_centers = _kmeans(cand, k, seed) if len(cand) > k else cand
            protected_centers, _ = _merge_close(protected_centers, np.ones(len(protected_centers)), merge_tol)
            notes.append(f"Protección de detalles: {len(protected_centers)} colores minoritarios reservados "
                         f"(de {len(means)} regiones con ΔE > {protect_tol:.0f}).")

    all_centers = np.concatenate([centers, protected_centers]) if len(protected_centers) else centers
    is_protected = np.zeros(len(all_centers), bool)
    is_protected[len(centers):] = True

    packed = _pack(rgb[opaque])
    uniq, inv = np.unique(packed, return_inverse=True)
    uniq_rgb = np.stack([(uniq >> 16) & 255, (uniq >> 8) & 255, uniq & 255], 1).astype(np.uint8)
    uniq_lab = rgb_to_lab(uniq_rgb[:, None, :]).reshape(-1, 3)
    lut = nearest_index(uniq_lab, all_centers)
    lab_full = lut[inv.reshape(-1)]
    counts = np.bincount(lab_full, minlength=len(all_centers))

    # Elimina centros sin píxeles asignados y reindexa.
    used = np.flatnonzero(counts)
    remap = np.full(len(all_centers), -1, np.int32)
    remap[used] = np.arange(len(used), dtype=np.int32)
    labels[opaque] = remap[lab_full]
    sliver_max = int(round(6 + 18 * (1 - d)))
    labels, n_slivers = clean_slivers(labels, true_flat, opaque, sliver_max, label_l=all_centers[used][:, 0],
                                      pixel_lab=rgb_to_lab(rgb), label_lab=all_centers[used])
    if n_slivers:
        notes.append(f"{n_slivers:,} astillas de antialiasing (≤{sliver_max}px, sin interior plano y de tono "
                     "intermedio entre sus vecinas) reasignadas a la región vecina.")
    palette = _snap_to_source(rgb, flat, labels, _lab_to_rgb(all_centers[used]), lossy)
    notes.append(f"Paleta reducida de {source_colors:,} colores de origen a {len(used)} (límite {max_colors}).")
    palette, labels, protected = _merge_duplicates(palette, labels, opaque, is_protected[used])
    counts = np.bincount(labels[opaque], minlength=len(palette)).astype(np.int64)
    return PaletteResult(labels, palette, counts, protected, "kmeans",
                         source_colors, notes)
