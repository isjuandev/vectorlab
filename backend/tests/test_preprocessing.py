from __future__ import annotations

import cv2
import numpy as np

from app.preprocessing.background import apply_alpha_policy, detect_background, remove_uniform_background
from app.preprocessing.labels import clean_slivers, nearest_fill
from app.preprocessing.outlines import detect_outlines
from app.preprocessing.palette import flat_mask, quantize
from tests.conftest import cartoon


def _gradient_with_dot(size: int = 120) -> np.ndarray:
    """Degradado (muchos colores) + un punto rojo pequeño y distintivo."""
    x = np.linspace(0, 1, size)
    rgb = np.zeros((size, size, 3), np.uint8)
    rgb[..., 0] = (40 + 60 * x)[None, :]
    rgb[..., 1] = (120 + 100 * x)[None, :]
    rgb[..., 2] = (200 - 50 * x)[:, None]
    cv2.circle(rgb, (60, 60), 3, (230, 20, 30), -1)
    return rgb


def test_palette_exact_when_few_colors() -> None:
    rgb = np.zeros((20, 20, 3), np.uint8)
    rgb[:10] = (255, 0, 0)
    res = quantize(rgb, np.ones((20, 20), bool), 64, 100, False)
    assert res.method == "exact"
    assert len(res.palette) == 2


def test_palette_respects_limit() -> None:
    rgb = _gradient_with_dot()
    for k in (4, 16, 48):
        res = quantize(rgb, np.ones(rgb.shape[:2], bool), k, 100, False)
        assert res.method == "kmeans"
        assert len(res.palette) <= k


def test_minority_color_protected_by_detail() -> None:
    rgb = _gradient_with_dot()
    opaque = np.ones(rgb.shape[:2], bool)
    res = quantize(rgb, opaque, 8, 100, False)
    dot_color = res.palette[res.labels[60, 60]].astype(int)
    assert abs(dot_color[0] - 230) < 25 and dot_color[1] < 60, dot_color  # el rojo sobrevive
    assert res.protected.any()


def test_sliver_cleanup_keeps_real_small_features() -> None:
    labels = np.zeros((30, 30), np.int32)
    labels[:, 15:] = 1
    labels[5:10, 3:8] = 2  # rasgo real 5x5 con interior plano
    labels[20, 14] = 3  # astilla de 1 px en la frontera
    flat = np.ones_like(labels, bool)
    flat[:, 13:17] = False  # frontera = transición
    flat[20, 14] = False
    out, n = clean_slivers(labels, flat, np.ones_like(flat), 6)
    assert n == 1
    assert out[20, 14] in (0, 1)
    assert (out[5:10, 3:8] == 2).all()


def test_nearest_fill_matches_brute_force() -> None:
    rng = np.random.default_rng(3)
    labels = rng.integers(0, 9, (25, 31)).astype(np.int32)
    mask = rng.random((25, 31)) < 0.35
    out = nearest_fill(labels, mask)
    ys, xs = np.nonzero(~mask)
    for y, x in zip(*np.nonzero(mask), strict=True):
        d = (ys - y) ** 2 + (xs - x) ** 2
        assert out[y, x] in set(labels[ys[d == d.min()], xs[d == d.min()]])


def test_flat_mask_excludes_edges() -> None:
    rgb = np.zeros((10, 10, 3), np.uint8)
    rgb[:, 5:] = 255
    m = flat_mask(rgb, 12)
    assert m[:, 0].all() and not m[:, 4].any() and not m[:, 5].any()


def test_alpha_binarization() -> None:
    rgba = np.zeros((4, 4, 4), np.uint8)
    rgba[..., 3] = [[0, 100, 127, 128]] * 4
    res = apply_alpha_policy(rgba, True, 128)
    assert res.opaque[:, 3].all() and not res.opaque[:, :3].any()
    assert res.partial_alpha_pixels == 12
    flat = apply_alpha_policy(rgba, False, 128)
    assert flat.opaque.all() and flat.rgb[0, 0].tolist() == [255, 255, 255]


def test_background_detection_and_removal() -> None:
    rgba = cartoon()
    rgb, opaque = rgba[..., :3].copy(), np.ones(rgba.shape[:2], bool)
    info = detect_background(rgb, opaque, 6.0)
    assert info.uniform and info.color == (255, 255, 255)
    new_opaque, removed = remove_uniform_background(rgb, opaque, info, 6.0)
    assert removed > 0 and not new_opaque[0, 0] and new_opaque[80, 80]
    # Los blancos de los ojos no tocan el borde: deben conservarse.
    assert new_opaque[70, 60]


def test_outlines_lines_vs_filled_regions() -> None:
    rgb = np.full((200, 200, 3), 255, np.uint8)
    cv2.rectangle(rgb, (20, 20), (180, 180), (15, 15, 15), 3)  # contorno fino
    cv2.rectangle(rgb, (60, 60), (140, 140), (15, 15, 15), -1)  # región oscura rellena grande
    res = detect_outlines(rgb, np.ones((200, 200), bool), 80)
    assert res.mask is not None
    assert res.mask[20, 100] and res.mask[180, 100]
    assert not res.mask[100, 100]  # el relleno no es contorno
    assert res.usable_for_layering


def test_outlines_disabled_at_zero() -> None:
    res = detect_outlines(np.zeros((50, 50, 3), np.uint8), np.ones((50, 50), bool), 0)
    assert not res.enabled and res.mask is None


def test_outlines_other_hue_kept_out_of_mask() -> None:
    rgb = np.full((200, 200, 3), 255, np.uint8)
    cv2.rectangle(rgb, (20, 20), (180, 180), (10, 10, 10), 3)
    cv2.line(rgb, (40, 100), (160, 100), (10, 20, 110), 3)  # línea azul marino oscura
    res = detect_outlines(rgb, np.ones((200, 200), bool), 100)
    assert res.mask[20, 100]
    assert not res.mask[100, 100]


def test_sliver_rule_keeps_broken_thin_lines_but_removes_transitions() -> None:
    # Etiquetas: 0 piel (L*≈80), 1 negro (L*≈5), 2 marrón medio (L*≈40), 3 marrón oscuro de línea (L*≈25).
    label_l = np.array([80.0, 5.0, 40.0, 25.0])
    labels = np.zeros((20, 40), np.int32)
    labels[:, 30:] = 1  # región negra a la derecha
    labels[10, 5:8] = 3  # fragmento de línea fina dentro de la piel: más oscuro que todo su entorno
    labels[4:6, 29] = 2  # astilla de transición piel→negro: tono intermedio
    flat = np.ones_like(labels, bool)
    flat[10, 5:8] = False
    flat[:, 28:31] = False
    out, n = clean_slivers(labels, flat, np.ones_like(flat), 6, label_l=label_l)
    assert (out[10, 5:8] == 3).all()  # la línea partida se conserva
    assert (out[4:6, 29] != 2).all() and n == 1  # la transición se reasigna
    # Sin información de tono se comporta como antes (ambas se eliminan).
    _, n_old = clean_slivers(labels, flat, np.ones_like(flat), 6)
    assert n_old == 2


def test_stroke_width_estimated_from_image() -> None:
    from app.preprocessing.color import rgb_to_lab
    from app.preprocessing.outlines import estimate_stroke_width

    rgb = np.full((300, 600, 3), 255, np.uint8)
    for x in range(40, 560, 60):
        cv2.line(rgb, (x, 20), (x, 280), (10, 10, 10), 6)
    cv2.rectangle(rgb, (250, 100), (330, 200), (10, 10, 10), -1)  # relleno oscuro que no debe dominar
    w = estimate_stroke_width(rgb_to_lab(rgb)[..., 0], np.ones((300, 600), bool), 35.0, 60)
    assert w is not None and 5 <= w <= 8


def test_multi_figure_sheet_does_not_treat_fills_as_outlines() -> None:
    # Hoja ancha con varias figuras: trazos de 4 px y un bloque oscuro de 60 px (barba/pelo).
    rgb = np.full((720, 1280, 3), 255, np.uint8)
    for cx in (200, 640, 1080):
        cv2.ellipse(rgb, (cx, 300), (150, 200), 0, 0, 360, (12, 12, 12), 4)
        cv2.rectangle(rgb, (cx - 30, 330), (cx + 30, 420), (12, 12, 12), -1)
    res = detect_outlines(rgb, np.ones((720, 1280), bool), 80)
    assert res.policy is not None and res.policy.max_line_width < 20  # antes: 24 px por el lado de la imagen
    assert res.mask[100, 200] or res.mask[101, 200]  # el contorno sí
    assert not res.mask[375, 640]  # el bloque relleno no


def test_alpha_codec_noise_is_not_reported_as_semitransparency() -> None:
    rgba = np.zeros((4, 4, 4), np.uint8)
    rgba[..., 3] = [[0, 3, 250, 254]] * 4
    res = apply_alpha_policy(rgba, True, 128)
    assert res.partial_alpha_pixels == 0
    assert res.opaque[:, 2:].all() and not res.opaque[:, :2].any()
    assert any("ruido de codificación" in n for n in res.info) and not res.notes


def _thin_red_line_on_skin() -> np.ndarray:
    """Piel con contorno negro y una línea roja antialiasada de ~1,5 px (sin ningún píxel «plano»)."""
    img = np.zeros((120, 120, 3), np.uint8)
    img[:] = (253, 210, 155)
    cv2.rectangle(img, (10, 10), (110, 110), (15, 20, 20), 3, cv2.LINE_AA)
    cv2.line(img, (25, 40), (95, 80), (190, 30, 38), 1, cv2.LINE_AA)
    cv2.line(img, (25, 41), (95, 81), (190, 30, 38), 1, cv2.LINE_AA)
    noise = np.random.default_rng(0).integers(-3, 4, img.shape)  # > 64 colores: fuerza k-means
    return np.clip(img.astype(int) + noise, 0, 255).astype(np.uint8)


def test_thin_line_color_enters_palette_unless_it_is_a_blend() -> None:
    from app.preprocessing.color import rgb_to_lab

    rgb = _thin_red_line_on_skin()
    assert not (flat_mask(rgb, 12) & (rgb_to_lab(rgb)[..., 1] > 45)).any()  # el rojo no tiene píxeles planos
    res = quantize(rgb, np.ones(rgb.shape[:2], bool), 64, 100, False)
    lab = rgb_to_lab(res.palette[:, None, :]).reshape(-1, 3)
    assert (lab[:, 1] > 40).any(), "el rojo de la línea fina debe estar en la paleta"
    # Sin la línea, las mezclas piel/contorno del antialiasing no añaden colores protegidos.
    plain = _thin_red_line_on_skin()
    plain[30:90, 20:100] = plain[95:96, 50:51]
    res2 = quantize(plain, np.ones(plain.shape[:2], bool), 64, 100, False)
    assert not res2.protected.any()


def test_sliver_pixels_go_to_the_most_similar_neighbour() -> None:
    from app.preprocessing.color import rgb_to_lab

    # Región 0 (negro) | astilla (etiqueta 2) | región 1 (piel). El píxel de la astilla es casi piel.
    labels = np.zeros((9, 9), np.int32)
    labels[:, 5:] = 1
    labels[4, 4] = 2
    rgb = np.zeros((9, 9, 3), np.uint8)
    rgb[:, 5:] = (250, 210, 160)
    rgb[4, 4] = (225, 190, 145)
    flat = np.ones((9, 9), bool)
    flat[4, 4] = False
    centers = rgb_to_lab(np.array([[[0, 0, 0]], [[250, 210, 160]], [[125, 105, 80]]], np.uint8)).reshape(-1, 3)
    opaque = np.ones((9, 9), bool)
    by_distance, _ = clean_slivers(labels, flat, opaque, 6)
    by_color, n = clean_slivers(labels, flat, opaque, 6, label_l=centers[:, 0], pixel_lab=rgb_to_lab(rgb),
                                label_lab=centers)
    assert n == 1
    assert by_distance[4, 4] == 0  # el vecino más cercano por posición es el negro (empate resuelto así)
    assert by_color[4, 4] == 1


def test_supersample_uses_only_existing_labels_and_moves_edges_subpixel() -> None:
    from app.preprocessing.supersample import supersample_labels, upscale_rgba

    # Borde vertical antialiasado: la columna 5 es 25 % negra / 75 % blanca.
    rgba = np.full((10, 10, 4), 255, np.uint8)
    rgba[:, :5, :3] = 0
    rgba[:, 5, :3] = 191
    labels = np.where(np.arange(10)[None, :] < 5, 0, 1).repeat(10, 0).astype(np.int32)
    labels[:, 5] = 1
    palette = np.array([[0, 0, 0], [255, 255, 255]], np.uint8)
    up = supersample_labels(labels, palette, upscale_rgba(rgba, 4), 4, 128)
    assert up.shape == (40, 40)
    assert set(np.unique(up)) <= {0, 1}
    row = up[20]
    edge = int(np.argmax(row == 1))  # primera columna blanca en la escala ×4
    assert 20 <= edge <= 22, edge  # el borde se desplaza dentro del píxel antialiasado (×4: 20 = sin desplazar)
    assert up[:, :18].max() == 0 and up[:, 24:].min() == 1


def test_supersample_factor_rules() -> None:
    from app.services.pipeline import supersample_factor

    assert supersample_factor(0, 417, 487, 24_000_000) == 3
    assert supersample_factor(0, 200, 200, 24_000_000) == 4
    assert supersample_factor(0, 1600, 900, 24_000_000) == 1
    assert supersample_factor(0, 1500, 300, 24_000_000) == 1
    assert supersample_factor(0, 790, 790, 24_000_000) == 2
    assert supersample_factor(4, 3000, 3000, 24_000_000) == 1  # explícito, limitado por max_pixels
    assert supersample_factor(1, 100, 100, 24_000_000) == 1
