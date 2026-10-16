"""Detección de contornos oscuros (control personalizado «énfasis en contornos negros»).

VTracer no tiene un parámetro nativo equivalente. Este módulo genera una máscara de contornos
candidatos con una política explícita, controlada por `emphasis` (0–100):

* Umbral de oscuridad   L* < 18 + 0.22·e          (e=80 → L* < 35.6)
* Contraste local       black-top-hat(L*) ≥ 30 − 0.15·e   (e=80 → ≥ 18)
  El black-top-hat (cierre morfológico − original) con un kernel algo mayor que el grosor máximo
  de línea solo responde a estructuras oscuras finas: las regiones oscuras rellenas grandes
  (cabello negro, sombras macizas) desaparecen del top-hat y no se tratan como contorno.
* Trazos aclarados  además L* < umbral + 20·e si el top-hat ≥ contraste + 12 (líneas finas suavizadas).
* Grosor máximo de línea W = clamp(g·(1 + e), 3, lado_menor·(0.01 + 0.03·e)), donde g es el grosor típico
  de trazo estimado en la propia imagen (mediana de 2·distancia sobre el esqueleto de los píxeles oscuros).
  Si no hay trazos suficientes se usa el tope relativo al lado (necesario en hojas con varias figuras).
* Componentes: se descartan los menores de 4 px. Las manchas compactas (elongación < 2.5, p. ej.
  pupilas pequeñas) solo se incluyen si e ≥ 60.
* La máscara nunca se dilata (evita engrosar líneas); se toma de los píxeles originales.

e = 0 desactiva el módulo por completo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from skimage.morphology import skeletonize

from app.preprocessing.color import rgb_to_lab

MIN_COMPONENT_AREA = 4
MIN_COVERAGE = 0.002  # fracción de píxeles opacos por debajo de la cual no se intenta la capa de contornos
LINE_COLOR_TOLERANCE = 15.0  # distancia cromática máxima (plano a*b*) respecto al color de contorno
MIN_WIDTH_SAMPLES = 50
RELAXED_DARKNESS = 20.0  # L* adicional (×e) admitido para trazos muy contrastados
STRONG_CONTRAST_EXTRA = 12.0


@dataclass
class OutlinePolicy:
    emphasis: int
    dark_threshold: float
    min_contrast: float
    max_line_width: int
    include_spots: bool
    stroke_width_estimate: float | None = None
    relaxed_threshold: float | None = None  # trazos muy contrastados aclarados por el antialiasing
    strong_contrast: float | None = None

    @classmethod
    def from_emphasis(cls, emphasis: int, height: int, width: int,
                      stroke_width: float | None = None) -> OutlinePolicy:
        e = emphasis / 100.0
        cap = max(3, int(round(min(height, width) * (0.01 + 0.03 * e))))
        max_w = cap if stroke_width is None else int(np.clip(round(stroke_width * (1 + e)), 3, cap))
        dark = 18.0 + 22.0 * e
        contrast = 30.0 - 15.0 * e
        return cls(emphasis=emphasis, dark_threshold=dark, min_contrast=contrast, max_line_width=max_w,
                   include_spots=emphasis >= 60, stroke_width_estimate=stroke_width,
                   relaxed_threshold=dark + RELAXED_DARKNESS * e, strong_contrast=contrast + STRONG_CONTRAST_EXTRA)

    @classmethod
    def for_image(cls, emphasis: int, lab_l: np.ndarray, opaque: np.ndarray) -> OutlinePolicy:
        h, w = opaque.shape
        base = cls.from_emphasis(emphasis, h, w)
        width = estimate_stroke_width(lab_l, opaque, base.dark_threshold, base.max_line_width)
        return cls.from_emphasis(emphasis, h, w, width)


def estimate_stroke_width(lab_l: np.ndarray, opaque: np.ndarray, dark_threshold: float, cap: int) -> float | None:
    """Grosor típico de trazo: mediana de 2·distancia sobre el esqueleto de los píxeles oscuros.

    Solo cuentan los grosores ≤ cap (los rellenos oscuros grandes no pesan). None si no hay trazos suficientes.
    """
    dark = (np.where(opaque, lab_l, 100.0) < dark_threshold).astype(np.uint8)
    if dark.sum() < MIN_WIDTH_SAMPLES:
        return None
    dt = cv2.distanceTransform(dark, cv2.DIST_L2, 5)
    widths = 2.0 * dt[skeletonize(dark.astype(bool))]
    widths = widths[widths <= cap]
    return float(np.median(widths)) if widths.size >= MIN_WIDTH_SAMPLES else None


@dataclass
class OutlineResult:
    enabled: bool
    mask: np.ndarray | None  # HxW bool
    color: tuple[int, int, int] | None
    policy: OutlinePolicy | None
    stats: dict = field(default_factory=dict)
    decisions: list[str] = field(default_factory=list)

    @property
    def usable_for_layering(self) -> bool:
        return bool(self.enabled and self.mask is not None and self.stats.get("coverage", 0) >= MIN_COVERAGE)


def dark_mask(lab_l: np.ndarray, opaque: np.ndarray, policy: OutlinePolicy) -> np.ndarray:
    k = policy.max_line_width + 2
    k += 1 - k % 2
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    # Las zonas transparentes se tratan como claras para que el borde de la silueta tenga contraste.
    l_img = np.where(opaque, lab_l, 100.0).astype(np.float32)
    blackhat = cv2.morphologyEx(l_img, cv2.MORPH_BLACKHAT, kernel)
    out = (l_img < policy.dark_threshold) & (blackhat >= policy.min_contrast)
    if policy.relaxed_threshold is not None and policy.strong_contrast is not None:
        # Trazos finos muy contrastados que el antialiasing o la compresión han aclarado.
        out |= (l_img < policy.relaxed_threshold) & (blackhat >= policy.strong_contrast)
    return out & opaque


def detect_outlines(rgb: np.ndarray, opaque: np.ndarray, emphasis: int) -> OutlineResult:
    if emphasis <= 0:
        return OutlineResult(False, None, None, None, {}, ["Énfasis en contornos = 0: detección desactivada."])
    lab = rgb_to_lab(rgb)
    policy = OutlinePolicy.for_image(emphasis, lab[..., 0], opaque)
    raw = dark_mask(lab[..., 0], opaque, policy)

    n, comp, stats, _ = cv2.connectedComponentsWithStats(raw.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    lines = spots = tiny = 0
    skel_counts = np.bincount(comp[skeletonize(raw)], minlength=n)
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < MIN_COMPONENT_AREA:
            tiny += 1
            continue
        skel_len = max(1, int(skel_counts[i]))
        thickness = area / skel_len
        elongation = skel_len / max(1.0, thickness)
        if elongation >= 2.5:
            keep[i] = True
            lines += 1
        elif policy.include_spots:
            keep[i] = True
            spots += 1
    mask = keep[comp]
    coverage = float(mask.sum() / max(1, opaque.sum()))
    decisions = [
        f"Política e={emphasis}: L*<{policy.dark_threshold:.1f}, contraste top-hat ≥{policy.min_contrast:.1f}, "
        f"grosor máx. {policy.max_line_width}px, manchas {'incluidas' if policy.include_spots else 'excluidas'}.",
        f"{lines} trazos lineales y {spots} manchas oscuras aceptados; {tiny} fragmentos < "
        f"{MIN_COMPONENT_AREA}px descartados.",
    ]
    color = None
    excluded = 0
    if mask.any():
        med = np.median(rgb[mask].reshape(-1, 3), axis=0)
        color = tuple(int(round(v)) for v in med)
        # Las líneas oscuras de otro tono (p. ej. marrón o azul marino) no se recolorean como contorno.
        ref = rgb_to_lab(np.array([[color]], np.uint8)).reshape(3)
        far = np.zeros_like(mask)
        far[mask] = np.linalg.norm(lab[mask][:, 1:] - ref[1:], axis=1) > LINE_COLOR_TOLERANCE
        excluded = int(far.sum())
        mask &= ~far
        coverage = float(mask.sum() / max(1, opaque.sum()))
        if excluded:
            hex_color = "#{:02x}{:02x}{:02x}".format(*color)
            decisions.append(f"{excluded:,} px oscuros de otro tono (distancia cromática a*b* > "
                             f"{LINE_COLOR_TOLERANCE:.0f} respecto a {hex_color}) se conservan con su color "
                             "y no forman parte del contorno.")
    if coverage < MIN_COVERAGE:
        decisions.append(f"Cobertura de contornos {coverage:.2%} < {MIN_COVERAGE:.1%}: no se usará capa separada.")
    return OutlineResult(True, mask, color, policy,
                         {"coverage": round(coverage, 5), "line_components": lines, "spot_components": spots,
                          "discarded_fragments": tiny, "pixels": int(mask.sum()),
                          "excluded_other_hue_pixels": excluded}, decisions)
