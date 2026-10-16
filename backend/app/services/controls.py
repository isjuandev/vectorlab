"""Perfil cartoon_fidelity_v1: traducción de controles de producto a operaciones reales.

`derive_engine_config` produce los parámetros nativos de VTracer y registra el origen de cada
valor ("perfil", "derivado de …" o "override del usuario"), para que nada se cambie en silencio.
`CONTROL_SPECS` es la especificación de cada control expuesta en /capabilities (sección 14).
"""

from __future__ import annotations

from typing import Any

from app.schemas import VectorizeParams


def derive_engine_config(p: VectorizeParams, curve_mode: str,
                         factor: int = 1) -> tuple[dict[str, Any], dict[str, str]]:
    """`factor` = sobremuestreo: los tamaños en píxeles (filter_speckle) se expresan en píxeles del original."""
    d = p.detail_preservation / 100.0
    derived: dict[str, Any] = {
        # Calibrado en la Fase 1: con filter_speckle=0 se conservan parches de 2 px; con 1 ya se pierden.
        "filter_speckle": int(round(4 * (1 - d))),
        # La entrada ya llega cuantizada: 8 bits evita que VTracer vuelva a fusionar colores de la paleta.
        "color_precision": 8,
        "layer_difference": int(round(1 + 15 * (1 - d))),
        "corner_threshold": int(round(60 - 15 * d)),
        "length_threshold": round(3.5 + 0.5 * (1 - d), 2),
        "splice_threshold": 45,
        "max_iterations": 10,
        "path_precision": 3,
        "hierarchical": "stacked",
    }
    sources = {
        "filter_speckle": "derivado de detail_preservation",
        "color_precision": "perfil (entrada precuantizada)",
        "layer_difference": "derivado de detail_preservation",
        "corner_threshold": "derivado de detail_preservation",
        "length_threshold": "derivado de detail_preservation",
        "splice_threshold": "perfil (valor por defecto de VTracer)",
        "max_iterations": "perfil (valor por defecto de VTracer)",
        "path_precision": "perfil (redondeo de exportación, no fidelidad)",
        "hierarchical": "perfil",
    }
    for key, value in p.advanced.model_dump().items():
        if value is not None:
            derived[key] = value.value if hasattr(value, "value") else value
            sources[key] = "override del usuario"
    if factor > 1 and derived["filter_speckle"]:
        derived["filter_speckle"] = min(128, derived["filter_speckle"] * factor)
        sources["filter_speckle"] += f" (×{factor} por sobremuestreo)"
    derived["mode"] = curve_mode
    sources["mode"] = "curve_mode"
    return derived, sources


def _spec(**kw: Any) -> dict[str, Any]:
    return kw


CONTROL_SPECS: list[dict[str, Any]] = [
    _spec(id="strategy", label="Modo de vectorización", type="enum", values=["auto", "integral", "layered"],
          default="auto", unit=None, stage="trazado",
          native_params=["colormode"],
          custom_operation="auto evalúa trazado integral y por capas y elige por métricas; layered traza "
                           "rellenos y contornos por separado",
          validation="layered requiere outline_emphasis>0",
          expected_effect="Cambia la estructura del SVG (grupo único o grupos fills/outlines).",
          no_effect_cases="layered/auto sin contornos detectables: se usa integral y se avisa.",
          sensitivity_test="tests/test_sensitivity.py::test_strategy_changes_structure"),
    _spec(id="curve_mode", label="Modo de curvas", type="enum", values=["spline", "polygon", "pixel", "auto"],
          default="spline", unit=None, stage="trazado", native_params=["mode"], custom_operation=None,
          validation="enum", expected_effect="spline: curvas Bézier suaves; polygon: segmentos rectos; "
                                              "pixel: bordes de píxel exactos; auto: compara spline y polygon.",
          no_effect_cases="Ninguno.",
          sensitivity_test="tests/test_sensitivity.py::test_curve_mode_changes_geometry"),
    _spec(id="max_colors", label="Colores máximos", type="int", min=2, max=256, default=64, unit="colores",
          stage="paleta", native_params=["color_precision"],
          custom_operation="k-means en CIELAB sobre regiones planas + reserva para colores minoritarios",
          validation="2–256", expected_effect="Limita la paleta de la imagen preprocesada.",
          no_effect_cases="Imágenes con ≤ max_colors colores exactos (no se cuantizan).",
          sensitivity_test="tests/test_sensitivity.py::test_max_colors_limits_palette"),
    _spec(id="detail_preservation", label="Conservación de detalles", type="int", min=0, max=100, default=100,
          unit="%", stage="paleta + trazado",
          native_params=["filter_speckle", "layer_difference", "corner_threshold", "length_threshold"],
          custom_operation="reserva de paleta para minorías, tolerancia de fusión de colores",
          validation="0–100", expected_effect="Más alto = menos filtrado de manchas y fusión de colores.",
          no_effect_cases="Parámetros sobrescritos en ajustes avanzados.",
          sensitivity_test="tests/test_sensitivity.py::test_detail_preserves_small_features"),
    _spec(id="outline_emphasis", label="Énfasis en contornos negros", type="int", min=0, max=100, default=80,
          unit="%", stage="análisis de contornos", native_params=[],
          custom_operation="máscara de líneas oscuras (umbral L*, black-top-hat, elongación); unifica su color "
                           "y habilita la capa de contornos",
          validation="0–100", expected_effect="Más alto = umbral de oscuridad y grosor máximo mayores. "
                                               "No engrosa trazos.",
          no_effect_cases="Imágenes sin líneas oscuras finas (cobertura < 0,2 %).",
          sensitivity_test="tests/test_sensitivity.py::test_outline_emphasis_changes_mask"),
    _spec(id="preserve_alpha", label="Preservar transparencia", type="bool", default=True, unit=None,
          stage="normalización", native_params=[], custom_operation="binarización de alfa con alpha_threshold",
          validation="bool", expected_effect="Las zonas transparentes no generan rutas.",
          no_effect_cases="Imágenes sin canal alfa.", sensitivity_test="tests/test_pipeline.py::test_transparency"),
    _spec(id="alpha_threshold", label="Umbral de alfa", type="int", min=1, max=255, default=128, unit="nivel 0–255",
          stage="normalización", native_params=[], custom_operation="píxeles con alfa < umbral → transparentes",
          validation="1–255", expected_effect="Controla dónde se corta el borde semitransparente.",
          no_effect_cases="Imágenes sin alfa parcial.", sensitivity_test=None),
    _spec(id="background_mode", label="Tratamiento del fondo", type="enum", values=["keep", "remove_uniform"],
          default="keep", unit=None, stage="normalización", native_params=[],
          custom_operation="detecta color dominante del borde y vuelve transparente la región conectada",
          validation="requiere preserve_alpha", expected_effect="Elimina un fondo liso.",
          no_effect_cases="Fondo no uniforme (<60 % del borde dentro de tolerancia).",
          sensitivity_test="tests/test_pipeline.py::test_background_removal"),
    _spec(id="background_tolerance", label="Tolerancia del fondo", type="float", min=0.5, max=40, default=6,
          unit="ΔE76", stage="normalización", native_params=[], custom_operation="umbral de similitud al fondo",
          validation="0.5–40", expected_effect="Mayor = elimina tonos más alejados del fondo.",
          no_effect_cases="background_mode=keep.", sensitivity_test=None),
    _spec(id="denoise_lossy", label="Filtrar artefactos de compresión", type="bool", default=True, unit=None,
          stage="normalización", native_params=[],
          custom_operation="cv2.pyrMeanShiftFiltering(sp=3, sr=18) antes de la paleta",
          validation="bool", expected_effect="Menos rutas y colores espurios en JPEG/WebP con pérdida.",
          no_effect_cases="PNG y WebP sin pérdida (no se aplica).",
          sensitivity_test="tests/test_sensitivity.py::test_denoise_lossy_reduces_paths"),
    _spec(id="visual_validation", label="Validación visual", type="bool", default=True, unit=None,
          stage="validación", native_params=[], custom_operation="render + métricas",
          validation="obligatoria si se comparan varios candidatos",
          expected_effect="Calcula métricas y elige candidato.", no_effect_cases="Ninguno.",
          sensitivity_test=None),
    _spec(id="supersample", label="Sobremuestreo del trazado", type="int", min=0, max=4, default=0,
          unit="factor (0 = auto)", stage="trazado", native_params=["filter_speckle"],
          custom_operation="amplía la imagen ×k (interpolación cúbica, alfa premultiplicado) y asigna a cada píxel "
                           "la etiqueta de paleta vecina (3×3 original) de color más cercano; traza a ×k y expresa "
                           "el SVG con viewBox ×k; filter_speckle se multiplica por k",
          validation="0–4; limitado por max_pixels (explícito) o 4 MP trazados (auto)",
          expected_effect="Bordes con precisión de subpíxel y parches de 1 px conservados en imágenes pequeñas; "
                          "más tiempo y bytes. No añade colores.",
          no_effect_cases="auto en imágenes con lado mayor ≥ 1600 px (factor 1).",
          sensitivity_test="tests/test_sensitivity.py::test_supersample_improves_small_image_and_keeps_document_size"),
    _spec(id="candidate_budget", label="Presupuesto de candidatos", type="int", min=1, max=4, default=2,
          unit="intentos", stage="trazado", native_params=[], custom_operation="límite de configuraciones evaluadas",
          validation="1–4", expected_effect="Más candidatos = más tiempo, posible mejor selección.",
          no_effect_cases="strategy y curve_mode fijos (un solo candidato posible).", sensitivity_test=None),
]

ADVANCED_SPECS: list[dict[str, Any]] = [
    {"id": "filter_speckle", "unit": "px (lado aprox.)", "min": 0, "max": 128,
     "effect": "Descarta manchas menores. 0 = conservar todo (Fase 1: con 1 ya se pierden parches de 2 px)."},
    {"id": "color_precision", "unit": "bits por canal", "min": 1, "max": 8,
     "effect": "Bits significativos por canal RGB en el agrupamiento de VTracer."},
    {"id": "layer_difference", "unit": "diferencia de color", "min": 1, "max": 255,
     "effect": "Diferencia mínima entre capas de color; menor = más capas."},
    {"id": "corner_threshold", "unit": "grados", "min": 0, "max": 180,
     "effect": "Ángulo mínimo para considerar una esquina; menor = más esquinas."},
    {"id": "length_threshold", "unit": "px", "min": 3.5, "max": 10,
     "effect": "Longitud mínima de segmento al simplificar; menor = más fiel."},
    {"id": "splice_threshold", "unit": "grados", "min": 0, "max": 180,
     "effect": "Ángulo mínimo para dividir un spline."},
    {"id": "max_iterations", "unit": "iteraciones", "min": 1, "max": 50,
     "effect": "Iteraciones de ajuste de curvas."},
    {"id": "path_precision", "unit": "decimales", "min": 0, "max": 8,
     "effect": "Redondeo de coordenadas exportadas. No recupera información perdida en el trazado."},
    {"id": "hierarchical", "unit": None, "values": ["stacked", "cutout"],
     "effect": "stacked apila formas; cutout genera formas disjuntas (con agujeros)."},
]
