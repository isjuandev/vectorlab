# Especificación de controles (perfil `cartoon_fidelity_v1`)

La fuente de verdad ejecutable es `backend/app/services/controls.py` (`CONTROL_SPECS`, servido en
`GET /api/v1/capabilities`) y `derive_engine_config`. Este documento añade las fórmulas y la calibración.

Reglas generales:

- Cada valor nativo de VTracer se registra con su origen: `perfil`, `derivado de <control>` u
  `override del usuario` (informe → `effective_params.native_param_sources`).
- Las combinaciones incompatibles se **rechazan** con 422 (`incompatible_params`), nunca se corrigen en
  silencio. La misma comprobación existe en el frontend (`lib/params.ts`) para bloquear el envío.
- Si un control no puede aplicarse a una imagen, el informe lo dice (advertencia o nota).

## Controles de producto

| id | Nombre | Tipo / rango | Defecto | Unidad | Etapa | Nativos relacionados | Operación personalizada | Sin efecto cuando | Prueba de sensibilidad |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `strategy` | Modo de vectorización | auto · integral · layered | auto | — | trazado | `colormode` | layered = rellenos + capa de contornos trazada en binario; auto = evalúa ambos y elige por puntuación | sin contornos utilizables (cobertura < 0,2 %): se usa integral y se avisa | `test_strategy_changes_structure` |
| `curve_mode` | Modo de curvas | spline · polygon · pixel · auto | spline | — | trazado | `mode` (pixel → `none`) | auto = prueba spline y polygon dentro del presupuesto | — | `test_curve_mode_changes_geometry`, `test_curve_mode_auto_respects_budget` |
| `max_colors` | Colores máximos | 2–256 | 64 | colores | paleta | `color_precision` (fijado a 8) | k-means CIELAB sobre píxeles planos + reserva para minorías + ajuste de rellenos del SVG a la paleta | la imagen ya tiene ≤ N colores exactos | `test_max_colors_limits_palette` |
| `detail_preservation` | Conservación de detalles | 0–100 | 100 | % | paleta + trazado | `filter_speckle`, `layer_difference`, `corner_threshold`, `length_threshold` | reserva de paleta, tolerancias de fusión, tamaño de astillas | parámetros sobrescritos en avanzados | `test_detail_preserves_small_features`, `test_minority_color_protected_by_detail` |
| `outline_emphasis` | Énfasis en contornos negros | 0–100 | 80 | % | contornos | ninguno (VTracer no tiene equivalente) | máscara de líneas oscuras; unifica su color; habilita la capa de contornos | imágenes sin líneas oscuras finas | `test_outline_emphasis_changes_mask`, `test_outline_emphasis_zero_disables_layering` |
| `preserve_alpha` | Preservar transparencia | bool | true | — | normalización | — | binarización de alfa | imágenes sin alfa | `test_transparency`, `test_transparency_disabled_composites_on_white` |
| `alpha_threshold` | Umbral de alfa | 1–255 | 128 | nivel | normalización | — | alfa < umbral → transparente | sin alfa parcial | `test_alpha_binarization` |
| `background_mode` | Tratamiento del fondo | keep · remove_uniform | keep | — | normalización | — | color dominante del borde; región conectada al borde dentro de tolerancia → transparente | borde no uniforme (< 60 % del borde cerca del color dominante) | `test_background_removal` |
| `background_tolerance` | Tolerancia del fondo | 0,5–40 | 6 | ΔE76 | normalización | — | umbral de similitud al fondo | `background_mode=keep` | — |
| `denoise_lossy` | Filtrar artefactos de compresión | bool | true | — | normalización | — | `cv2.pyrMeanShiftFiltering(sp=3, sr=18)` | PNG y WebP sin pérdida | `test_denoise_lossy_reduces_paths`, `test_denoise_lossy_effect` |
| `visual_validation` | Validación visual | bool | true | — | validación | — | render resvg + métricas | — | (incompatibilidad probada en `test_api`) |
| `supersample` | Sobremuestreo del trazado | 0–4 (0 = auto) | 0 | factor | trazado | `filter_speckle` (×k) | amplía ×k con interpolación cúbica; cada píxel ampliado toma la etiqueta vecina (3×3 original) de color más cercano; traza a ×k y emite `viewBox` ×k con el tamaño original | auto con lado mayor ≥ 1600 px (k = 1) | `test_supersample_improves_small_image_and_keeps_document_size`, `test_supersample_uses_only_existing_labels_and_moves_edges_subpixel` |
| `candidate_budget` | Presupuesto de candidatos | 1–4 | 2 | intentos | trazado | — | límite de configuraciones evaluadas | strategy y curve_mode fijos | `test_curve_mode_auto_respects_budget` |

Incompatibilidades rechazadas: `layered` con `outline_emphasis = 0`; `remove_uniform` sin `preserve_alpha`;
varios candidatos (`auto`) con `visual_validation = false`.

## `detail_preservation` (d = valor/100)

| Nativo VTracer | Fórmula | d = 1 | d = 0 | Por qué |
| --- | --- | --- | --- | --- |
| `filter_speckle` | round(4·(1−d)) | 0 | 4 | Fase 1: con 1 ya se pierden parches de 2 px; con 0 se conservan |
| `layer_difference` | round(1 + 15·(1−d)) | 1 | 16 | menor = no fusionar colores de la paleta |
| `corner_threshold` | round(60 − 15·d) | 45 | 60 | menor = más esquinas conservadas |
| `length_threshold` | 3,5 + 0,5·(1−d) | 3,5 | 4,0 | mínimo admitido por VTracer = 3,5 |

Operaciones propias controladas por d: reserva de paleta para minorías = round(0,25·N·d) colores;
tolerancia de minoría ΔE76 = 14 − 6·d; fusión de centros ΔE76 = 2 + 6·(1−d) (+4 si la entrada tiene pérdida);
astillas de antialiasing reasignadas si ≤ round(6 + 18·(1−d)) px, sin ningún píxel plano **y** con L*
intermedia entre sus vecinas (los fragmentos más oscuros o claros que todas sus vecinas son trozos de líneas
finas y se conservan; D15); cada píxel de astilla va a la etiqueta vecina de color más parecido (D21).
En entradas sin pérdida, la reserva de minorías incluye además los colores de estructuras finas que no son
mezcla lineal de dos colores de la paleta (D20).

Fijos del perfil: `color_precision = 8` (la entrada llega cuantizada), `splice_threshold = 45`,
`max_iterations = 10`, `path_precision = 3` (solo redondeo de exportación; **no** es fidelidad),
`hierarchical = stacked`.

100 % significa la política más conservadora disponible, no reproducción píxel a píxel.

## `outline_emphasis` (e = valor/100)

No es un aumento de grosor. Controla una política de **detección**:

| Paso | Regla |
| --- | --- |
| Oscuridad | L* < 18 + 22·e (e = 0,8 → 35,6); además L* < umbral + 20·e si el top-hat ≥ contraste + 12 (trazos aclarados por el antialiasing) |
| Contraste local | black-top-hat(L*) ≥ 30 − 15·e, con kernel elíptico de W+2 px; separa líneas finas de regiones oscuras rellenas (que desaparecen del top-hat) |
| Grosor máximo | W = clamp(g·(1+e), 3, lado_menor·(0,01 + 0,03·e)), con g = grosor típico de trazo estimado en la imagen (mediana de 2·distancia sobre el esqueleto oscuro); si no hay trazos suficientes, el tope |
| Continuidad | componentes < 4 px descartados; elongación = longitud de esqueleto / grosor medio ≥ 2,5 → trazo; las manchas compactas solo entran si e ≥ 0,6 |
| Tono | se excluyen píxeles con distancia cromática a*b* > 15 respecto al color mediano (líneas marrones o azul marino conservan su color) |
| Uso | integral: los píxeles de la máscara toman el color de contorno de la paleta (líneas sin fragmentar en grises); por capas: los rellenos se extienden bajo la máscara (vecino exacto) y la máscara se traza en binario encima |
| Desactivación | e = 0, o cobertura < 0,2 % (no se intenta la capa separada) |

La máscara nunca se dilata (evita engrosar líneas). Cada decisión se registra en `notes` del informe.

Calibración: la primera versión usaba W = lado·(0,008 + 0,012·e) y no detectaba contornos de 6 px en una
imagen de 240 px; se amplió tras `test_strategy_changes_structure`. Con la primera imagen real (hoja de 6
figuras) el tope relativo al lado daba 49 px y marcaba la barba como contorno; de ahí la estimación de g
(docs/decisions.md, D14).

## `supersample` (k)

| Valor | Factor efectivo |
| --- | --- |
| 0 (auto) | k = clamp(⌊1600 / lado mayor⌋, 1, 4), reducido hasta que el trazado tenga ≤ 4 MP |
| 1–4 | el pedido, reducido solo si superaría `VECTORLAB_MAX_PIXELS` |

El paso no inventa contenido: solo decide, a resolución ×k, cuál de las etiquetas ya presentes alrededor de cada
píxel corresponde, usando el color interpolado del original. El informe registra `supersample_factor` y una
nota. Evidencia en docs/decisions.md (D19).

## Ajustes avanzados

Los nueve nativos (`filter_speckle`, `color_precision`, `layer_difference`, `corner_threshold`,
`length_threshold`, `splice_threshold`, `max_iterations`, `path_precision`, `hierarchical`) pueden
sobrescribirse; rangos validados contra los admitidos por VTracer 0.6.15 (`length_threshold` ∈ [3,5; 10]).
Con sobremuestreo ×k, `filter_speckle` (derivado u override) se multiplica por k: se expresa siempre en píxeles
de la imagen original. Los demás nativos se aplican tal cual a la imagen ×k.
