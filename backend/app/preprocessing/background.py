"""Tratamiento del canal alfa y del fondo."""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.preprocessing.color import rgb_to_lab

ALPHA_NOISE = 8


@dataclass
class AlphaResult:
    rgb: np.ndarray  # HxWx3 uint8
    opaque: np.ndarray  # HxW bool
    partial_alpha_pixels: int
    notes: list[str]  # advertencias
    info: list[str] = field(default_factory=list)  # decisiones informativas


def apply_alpha_policy(rgba: np.ndarray, preserve_alpha: bool, threshold: int) -> AlphaResult:
    """Binariza el alfa.

    VTracer 0.6.15 trata como opaco cualquier píxel con alfa > 0 (verificado en la PoC: un píxel
    con alfa 128 se renderiza totalmente opaco). Por eso el alfa se binariza explícitamente aquí.
    """
    alpha = rgba[..., 3]
    # El alfa 1–7 y 248–254 suele ser ruido de codificación (p. ej. WebP con pérdida), no semitransparencia.
    partial = int(((alpha >= ALPHA_NOISE) & (alpha <= 255 - ALPHA_NOISE)).sum())
    near = int(((alpha > 0) & (alpha < 255)).sum()) - partial
    notes: list[str] = []
    info: list[str] = []
    if near and preserve_alpha:
        info.append(f"{near:,} píxeles con alfa casi opaco o casi transparente (ruido de codificación) se "
                     "redondearon.")
    if not preserve_alpha:
        a = alpha[..., None].astype(np.float32) / 255.0
        rgb = (rgba[..., :3].astype(np.float32) * a + 255.0 * (1 - a)).round().astype(np.uint8)
        if alpha.min() < 255:
            notes.append("Transparencia desactivada: la imagen se compuso sobre blanco.")
        return AlphaResult(rgb, np.ones(alpha.shape, bool), partial, notes)
    opaque = alpha >= threshold
    if partial:
        notes.append(
            f"{partial:,} píxeles con alfa parcial se binarizaron con umbral {threshold} "
            "(el SVG resultante usa formas opacas; los bordes semitransparentes no se conservan).")
    rgb = rgba[..., :3].copy()
    rgb[~opaque] = 0
    return AlphaResult(rgb, opaque, partial, notes, info)


def denoise_lossy(rgb: np.ndarray) -> np.ndarray:
    """Filtro mean-shift que aplana el ruido de compresión preservando bordes.

    Calibrado en la Fase 3 sobre JPEG q75 y WebP con pérdida (ver docs/phase-reports.md).
    """
    return cv2.pyrMeanShiftFiltering(np.ascontiguousarray(rgb), 3, 18)


@dataclass
class BackgroundInfo:
    color: tuple[int, int, int] | None
    border_share: float  # fracción de píxeles opacos del borde cercanos al color dominante
    uniform: bool


def detect_background(rgb: np.ndarray, opaque: np.ndarray, tolerance: float) -> BackgroundInfo:
    border = np.zeros(opaque.shape, bool)
    border[0, :] = border[-1, :] = border[:, 0] = border[:, -1] = True
    sel = border & opaque
    if sel.sum() < 4:
        return BackgroundInfo(None, 0.0, False)
    colors = rgb[sel]
    packed = (colors[:, 0].astype(np.int64) << 16) | (colors[:, 1].astype(np.int64) << 8) | colors[:, 2]
    vals, counts = np.unique(packed, return_counts=True)
    top = int(vals[counts.argmax()])
    color = ((top >> 16) & 255, (top >> 8) & 255, top & 255)
    lab = rgb_to_lab(colors.reshape(-1, 1, 3)).reshape(-1, 3)
    ref = rgb_to_lab(np.array([[color]], np.uint8)).reshape(3)
    share = float((np.linalg.norm(lab - ref, axis=1) <= tolerance).mean())
    return BackgroundInfo(color, share, share >= 0.6)


def remove_uniform_background(rgb: np.ndarray, opaque: np.ndarray, info: BackgroundInfo,
                              tolerance: float) -> tuple[np.ndarray, int]:
    """Vuelve transparente el fondo uniforme conectado con el borde. Devuelve (opaco, px eliminados)."""
    if not info.uniform or info.color is None:
        return opaque, 0
    lab = rgb_to_lab(rgb)
    ref = rgb_to_lab(np.array([[info.color]], np.uint8)).reshape(3)
    near = (np.linalg.norm(lab - ref, axis=2) <= tolerance) & opaque
    n, labels = cv2.connectedComponents(near.astype(np.uint8), connectivity=4)
    edge_labels = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    edge_labels = edge_labels[edge_labels != 0]
    bg = np.isin(labels, edge_labels)
    out = opaque & ~bg
    return out, int(bg.sum())
