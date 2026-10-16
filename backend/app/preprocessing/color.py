"""Conversión de color compartida (sRGB uint8 ↔ CIELAB float32)."""

from __future__ import annotations

import cv2
import numpy as np


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB uint8 (…x3) → CIELAB float32 con L en [0,100] (OpenCV, iluminante D65)."""
    shape = rgb.shape
    flat = rgb.reshape(-1, 1, 3).astype(np.float32) / 255.0
    lab = cv2.cvtColor(flat, cv2.COLOR_RGB2LAB)
    return lab.reshape(shape).astype(np.float32)


def to_hex(color: np.ndarray | tuple[int, int, int]) -> str:
    r, g, b = (int(c) for c in color)
    return f"#{r:02x}{g:02x}{b:02x}"


def nearest_index(lab_points: np.ndarray, lab_centers: np.ndarray, chunk: int = 200_000) -> np.ndarray:
    """Índice del centro más cercano (distancia euclídea en Lab = ΔE76) para cada punto."""
    out = np.empty(len(lab_points), np.int32)
    c2 = (lab_centers ** 2).sum(1)
    for i in range(0, len(lab_points), chunk):
        p = lab_points[i:i + chunk]
        d = c2[None, :] - 2.0 * p @ lab_centers.T
        out[i:i + chunk] = d.argmin(1)
    return out
