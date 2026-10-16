"""Sobremuestreo del mapa de etiquetas para trazar con precisión de subpíxel.

En imágenes pequeñas, una línea de 1–2 px queda en el límite de lo que VTracer puede seguir: el
suavizado de curvas desplaza bordes medio píxel y los parches de 1 px desaparecen en modo spline.
Aquí la imagen se amplía (interpolación con alfa premultiplicado, sin generar contenido nuevo) y cada
píxel ampliado recibe una etiqueta **ya existente** en la paleta: la más cercana en CIELAB entre las de
su vecindario 3×3 en la resolución original. Así:

* no aparecen colores nuevos (ni grises de antialiasing): solo se eligen etiquetas de los vecinos;
* el borde entre dos regiones se coloca donde el color interpolado cruza el punto medio, es decir,
  donde estaba el borde antialiasado del original (posición de subpíxel);
* el SVG conserva las dimensiones originales: el trazado se hace en coordenadas ×k y se expresa con
  `viewBox`.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.preprocessing.color import rgb_to_lab
from app.preprocessing.labels import nearest_fill


def upscale_rgba(rgba: np.ndarray, k: int) -> np.ndarray:
    """Amplía ×k con interpolación cúbica sobre alfa premultiplicado (float32, RGB en 0–255)."""
    h, w = rgba.shape[:2]
    f = rgba.astype(np.float32)
    a = f[..., 3:4] / 255.0
    pm = np.concatenate([f[..., :3] * a, f[..., 3:4]], axis=2)
    up = np.clip(cv2.resize(pm, (w * k, h * k), interpolation=cv2.INTER_CUBIC), 0, 255)
    a2 = up[..., 3:4] / 255.0
    rgb = np.where(a2 > 1e-3, up[..., :3] / np.maximum(a2, 1e-3), 0.0)
    return np.concatenate([np.clip(rgb, 0, 255), up[..., 3:4]], axis=2)


def supersample_labels(labels: np.ndarray, palette: np.ndarray, rgba_up: np.ndarray, k: int,
                       alpha_threshold: int | None) -> np.ndarray:
    """Etiquetas ×k: para cada píxel ampliado, la etiqueta vecina (3×3 original) más cercana en color.

    `alpha_threshold=None` → la opacidad se hereda del píxel original (transparencia desactivada).
    """
    h, w = labels.shape
    hk, wk = h * k, w * k
    pal_lab = rgb_to_lab(palette[:, None, :]).reshape(-1, 3) if len(palette) else np.zeros((1, 3), np.float32)
    up_lab = rgb_to_lab(np.clip(rgba_up[..., :3].round(), 0, 255).astype(np.uint8))

    padded = np.pad(labels, 1, constant_values=-1)
    ys = np.arange(hk) // k
    xs = np.arange(wk) // k
    best = np.full((hk, wk), -1, np.int32)
    best_d = np.full((hk, wk), np.inf, np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            cand = padded[(ys + 1 + dy)[:, None], (xs + 1 + dx)[None, :]]
            ok = cand >= 0
            d = np.full((hk, wk), np.inf, np.float32)
            d[ok] = np.linalg.norm(up_lab[ok] - pal_lab[cand[ok]], axis=1)
            if dy or dx:
                d += 1e-3  # a igualdad de color, gana la etiqueta del propio píxel
            better = d < best_d
            best[better] = cand[better]
            best_d[better] = d[better]

    if alpha_threshold is None:
        opaque = (labels >= 0)[ys[:, None], xs[None, :]]
    else:
        opaque = rgba_up[..., 3] >= alpha_threshold
    best[~opaque] = -1
    # Píxeles que pasan a ser opacos sin ningún vecino opaco en el original (raro): etiqueta más cercana.
    orphan = opaque & (best < 0)
    if orphan.any() and (best >= 0).any():
        best = nearest_fill(best, orphan)
    return best
