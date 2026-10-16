"""Genera imágenes SINTÉTICAS de prueba con rasgos de caricatura.

Estas imágenes sirven para pruebas funcionales y de sensibilidad (contornos
negros gruesos y finos, colores planos, sombras en bloque, rasgos pequeños,
transparencia, artefactos JPEG). NO son evidencia de fidelidad sobre
ilustraciones reales: para eso deben añadirse imágenes reales en samples/real/.

Uso:  backend/.venv/bin/python scripts/make_samples.py
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "samples" / "synthetic"

INK = (20, 20, 22)  # casi negro, en RGB
SKIN = (246, 205, 170)
SKIN_SHADOW = (222, 170, 135)
HAIR = (120, 70, 35)
SHIRT = (40, 110, 200)
SHIRT_SHADOW = (28, 80, 150)
RED = (205, 35, 45)
WHITE = (255, 255, 255)


def _bgr(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return (rgb[2], rgb[1], rgb[0])


def draw_character(size: int, bg: tuple[int, int, int] | None) -> np.ndarray:
    """Dibuja un personaje plano con contornos. Devuelve RGBA uint8."""
    s = size / 512.0
    canvas = np.zeros((size, size, 3), np.uint8)
    canvas[:] = _bgr(bg) if bg else (255, 255, 255)
    alpha = np.zeros((size, size), np.uint8)

    def p(x: float, y: float) -> tuple[int, int]:
        return (int(round(x * s)), int(round(y * s)))

    def r(v: float) -> int:
        return max(1, int(round(v * s)))

    aa = cv2.LINE_AA
    thick = r(7)
    thin = max(1, r(2))

    def fill_and_mark(draw):  # noqa: ANN001 - helper interno
        draw(canvas)
        mask = np.zeros_like(alpha)
        draw_mask = mask[..., None].repeat(3, axis=2)
        draw(draw_mask, mask_mode=True)
        alpha[:] = np.maximum(alpha, draw_mask[..., 0])

    # Cuerpo / camisa con sombra en bloque
    def body(img, mask_mode=False):  # noqa: ANN001
        c = (255, 255, 255) if mask_mode else _bgr(SHIRT)
        pts = np.array([p(140, 512), p(170, 380), p(342, 380), p(372, 512)], np.int32)
        cv2.fillPoly(img, [pts], c, aa)
        if not mask_mode:
            sh = np.array([p(300, 380), p(342, 380), p(372, 512), p(320, 512)], np.int32)
            cv2.fillPoly(img, [sh], _bgr(SHIRT_SHADOW), aa)
            cv2.polylines(img, [pts], True, _bgr(INK), thick, aa)
        else:
            cv2.polylines(img, [pts], True, c, thick, aa)

    # Cabeza
    def head(img, mask_mode=False):  # noqa: ANN001
        c = (255, 255, 255) if mask_mode else _bgr(SKIN)
        cv2.ellipse(img, p(256, 230), (r(120), r(140)), 0, 0, 360, c, -1, aa)
        if not mask_mode:
            # sombra plana del lado derecho
            cv2.ellipse(img, p(256, 230), (r(120), r(140)), 0, -60, 60, _bgr(SKIN_SHADOW), -1, aa)
            cv2.ellipse(img, p(236, 230), (r(112), r(140)), 0, 0, 360, _bgr(SKIN), -1, aa)
        cv2.ellipse(img, p(256, 230), (r(120), r(140)), 0, 0, 360,
                    (255, 255, 255) if mask_mode else _bgr(INK), thick, aa)

    # Cabello: bloque oscuro relleno (no es contorno)
    def hair(img, mask_mode=False):  # noqa: ANN001
        c = (255, 255, 255) if mask_mode else _bgr(HAIR)
        pts = np.array([p(130, 200), p(150, 110), p(256, 70), p(360, 110),
                        p(382, 200), p(330, 150), p(256, 140), p(180, 150)], np.int32)
        cv2.fillPoly(img, [pts], c, aa)
        cv2.polylines(img, [pts], True, (255, 255, 255) if mask_mode else _bgr(INK), thick, aa)

    fill_and_mark(body)
    fill_and_mark(head)
    fill_and_mark(hair)

    # Rasgos faciales (pequeños) – no cambian la silueta
    for ex in (205, 305):
        cv2.ellipse(canvas, p(ex, 225), (r(24), r(16)), 0, 0, 360, _bgr(WHITE), -1, aa)
        cv2.ellipse(canvas, p(ex, 225), (r(24), r(16)), 0, 0, 360, _bgr(INK), r(3), aa)
        cv2.circle(canvas, p(ex + 4, 227), r(8), _bgr(INK), -1, aa)
        cv2.circle(canvas, p(ex + 7, 223), max(1, r(2.5)), _bgr(WHITE), -1, aa)  # brillo
        # ceja fina
        cv2.line(canvas, p(ex - 22, 196), p(ex + 22, 190), _bgr(INK), thin, aa)
    # nariz (línea fina) y boca roja con contorno
    cv2.line(canvas, p(256, 240), p(246, 280), _bgr(INK), thin, aa)
    cv2.line(canvas, p(246, 280), p(262, 282), _bgr(INK), thin, aa)
    cv2.ellipse(canvas, p(256, 320), (r(40), r(18)), 0, 0, 180, _bgr(RED), -1, aa)
    cv2.ellipse(canvas, p(256, 320), (r(40), r(18)), 0, 0, 180, _bgr(INK), r(3), aa)
    cv2.line(canvas, p(216, 320), p(296, 320), _bgr(INK), r(3), aa)
    # pecas: detalles de 2-3 px
    for fx, fy in ((200, 270), (212, 278), (300, 270), (312, 278)):
        cv2.circle(canvas, p(fx, fy), max(1, r(2)), _bgr(SKIN_SHADOW), -1, aa)
    # botón negro relleno (región oscura pequeña)
    cv2.circle(canvas, p(256, 450), r(10), _bgr(INK), -1, aa)

    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    if bg is None:
        a = alpha
    else:
        a = np.full_like(alpha, 255)
    return np.dstack([rgb, a])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    variants = {
        "char_white_512.png": (512, (255, 255, 255), "PNG", {}),
        "char_transparent_512.png": (512, None, "PNG", {}),
        "char_color_bg_512.png": (512, (250, 230, 120), "PNG", {}),
        "char_white_512_q75.jpg": (512, (255, 255, 255), "JPEG", {"quality": 75}),
        "char_white_512_lossy.webp": (512, (255, 255, 255), "WEBP", {"quality": 80}),
        "char_transparent_512_lossless.webp": (512, None, "WEBP", {"lossless": True}),
        "char_white_1600.png": (1600, (255, 255, 255), "PNG", {}),
        "char_white_200.png": (200, (255, 255, 255), "PNG", {}),
    }
    for name, (size, bg, fmt, opts) in variants.items():
        rgba = draw_character(size, bg)
        img = Image.fromarray(rgba, "RGBA")
        if fmt == "JPEG":
            img = img.convert("RGB")
        img.save(OUT / name, fmt, **opts)
        print("escrito", OUT / name)


if __name__ == "__main__":
    main()
