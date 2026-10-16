# Registro de decisiones técnicas

Cada entrada: contexto → decisión → evidencia.

## D1. Python 3.12 gestionado con uv
El sistema tiene Python 3.14.4; VTracer se instaló y probó sobre 3.12 (wheel nativo disponible). `uv venv
--python 3.12` crea un entorno reproducible sin tocar el Python del sistema. `scripts/setup.sh` admite
`python3.12` como alternativa.

## D2. VTracer 0.6.15 vía `convert_raw_image_to_svg`
API real inspeccionada en `vtracer.pyi` de la versión instalada: `convert_image_to_svg_py`,
`convert_raw_image_to_svg`, `convert_pixels_to_svg`, con los parámetros `colormode, hierarchical, mode,
filter_speckle, color_precision, layer_difference, corner_threshold, length_threshold, max_iterations,
splice_threshold, path_precision`. Se usa `convert_raw_image_to_svg` con PNG en memoria:
`convert_pixels_to_svg` exige una lista Python de tuplas por píxel (inviable para imágenes grandes).
El comentario que emite el binario dice «VTracer 0.6.12» aunque el paquete es 0.6.15; se registra la versión
del paquete (`importlib.metadata`). El adaptador rechaza parámetros desconocidos o fuera de rango.

## D3. Sondas sobre el comportamiento real (Fase 1, `scripts/poc_vtracer.py`)
| Sonda | Resultado | Consecuencia |
| --- | --- | --- |
| `filter_speckle` vs cuadrados de 1–6 px | fs=0 conserva ≥ 2 px (spline/polygon) y 1 px solo con `mode="none"`; fs=1 y 2 ya pierden 2 px; fs=k pierde lados ≤ k | detalle 100 % → fs = 0; modo «Píxel» documentado para rasgos de 1 px |
| alfa 128 | se renderiza totalmente opaco | el alfa se binariza explícitamente antes del motor |
| exterior y agujero alfa 0 | transparentes | la transparencia binaria funciona sin pasos extra |
| anillo en `colormode="binary"` | agujero conservado | el trazado binario sirve para la capa de contornos |
| JPEG q75 sin preprocesar | 1 003 colores de relleno, 1 071 rutas | la cuantización previa es imprescindible |

## D4. Renderizador resvg-py, no CairoSVG
CairoSVG necesita `libcairo` (ausente: falla al cargar). `resvg-py` 0.5.0 es autocontenido. Se verificó
además que los SVG abren en ImageMagick 7.1 y Quick Look de macOS, y que `xmllint` los valida.

## D5. Paleta propia antes de VTracer
VTracer agrupa colores pero no ofrece un límite de colores. La cuantización propia (k-means en CIELAB)
ajusta los centros solo sobre píxeles «planos» (variación 3×3 ≤ 12, o ≤ 24 con pérdida) para que el
antialiasing no cree grises intermedios, reserva cupo para colores minoritarios, fusiona centros casi
iguales y ajusta cada centro a un color real de la imagen (moda sin pérdida, media con pérdida).

## D6. Limpieza de astillas de antialiasing (revisada en D15)
Evidencia (512 px PNG): sin limpieza, 189 rutas y 281 «componentes» para ~25 regiones reales; con limpieza,
38 rutas y 37 componentes, SSIM igual (0,9764). Solo se reasignan componentes pequeños **sin ningún píxel
plano**, así que pecas, brillos y pupilas se conservan (prueba `test_sliver_cleanup_keeps_real_small_features`).
La regla original borraba también trozos de líneas finas; ver D15.

## D7. Rellenos fuera de paleta
VTracer promedia colores al fusionar clústeres y emitió, p. ej., `#ffe29c` con una paleta que no lo contenía
(7 colores con límite 6). La reconstrucción ajusta cada relleno al color de paleta más cercano y lo registra
(`off_palette_fills_snapped`). Con ello el límite de colores es estricto (`test_max_colors_limits_palette`).

## D8. Mean-shift para entradas con pérdida
Comparativa sobre JPEG q75 (integral): sin filtro SSIM 0,9596 / 415 rutas / 23 colores; bilateral 0,9623 /
295 / 18; mediana 3×3 0,9643 / 433 / 23; **mean-shift (3, 18) 0,9670 / 185 / 12**. Se adopta mean-shift como
control `denoise_lossy`, solo para entradas con pérdida.

## D9. Énfasis en contornos como política de detección
VTracer no tiene un parámetro equivalente. Se implementa una máscara (oscuridad + black-top-hat + elongación
+ tono) que se usa para unificar el color de las líneas y, opcionalmente, trazarlas en una capa aparte. La
capa separada no se impone: se compara con el trazado integral y gana el de mayor puntuación.
Evidencia actual (sintéticas): integral gana en PNG/WebP sin pérdida (p. ej. 0,9754 vs 0,9652 a 512 px);
por capas gana en JPEG q75 (0,9501 vs 0,9229), WebP con pérdida y a 200 px.

## D10. Trabajos en memoria + ThreadPoolExecutor
Aplicación local de un usuario: sin Redis/Celery ni base de datos. Un hilo de trabajo por defecto (VTracer
y OpenCV ya usan varios núcleos internamente y la memoria es el recurso escaso). Cancelación cooperativa
entre etapas; el estado se pierde al reiniciar (archivos purgados por TTL).

## D11. Frontend → backend directo con CORS restringido
Se llama a `http://127.0.0.1:8000` desde el navegador con CORS limitado a `localhost:3000`/`127.0.0.1:3000`
en lugar de un proxy de Next.js, para no depender de límites de tamaño de cuerpo del proxy de desarrollo.

## D12. Dependencias de frontend
Next.js 16.4.2 (plantilla con Cache Components activo; la página es estática y todo el estado vive en un
componente cliente), React 19.3, Tailwind 4, shadcn/ui estilo `base-nova` (Base UI). Se descartó
`@vitejs/plugin-react` por conflicto de peer con Babel 8: Vitest transforma JSX sin él. `@types/node` se subió
a ^24 por requisito de Vitest 5. `npm audit` informa 5 vulnerabilidades altas en `braces`, dependencia de
desarrollo de `@next/eslint-plugin-next`; no forma parte del runtime.

## D13. Potrace no integrado
No está instalado y ninguna prueba ha mostrado que mejore la capa de contornos frente al modo binario de
VTracer. Queda como motor opcional implementable con el contrato `VectorizerEngine`.

---

# Calibración con imagen real (samples/real/brief 8.webp)

Imagen: hoja de 6 poses de una caricatura, 2560×1440, WebP con pérdida, alfa máximo 254, 51 891 colores,
traje azul marino muy oscuro, barba negra rellena, piel con sombreado suave, mechones finos. Es **una sola
imagen**: las conclusiones deben confirmarse con más ejemplos.

Método: atribuir la pérdida por etapa midiendo el recall de bordes Canny (≤ 1,5 px) original→preprocesada y
preprocesada→SVG (`scripts/diagnose_edges.py`), y ablación de un factor cada vez. Las métricas globales se
reproducen con `scripts/evaluate_samples.py`.

## D14. Grosor máximo de línea estimado de la imagen
La regla «3,4 % del lado menor» daba 49 px en esta hoja y marcaba como contorno la barba, el pelo y las
cejas (cobertura 19 %). Ahora W = clamp(g·(1+e), 3, tope anterior), con g = mediana de 2·distancia sobre el
esqueleto de los píxeles oscuros (≤ tope). Resultado: W = 12 px; SSIM 0,9444 → 0,9519 y ΔE 3,32 → 3,19
(modo integral); sintéticas sin cambios. Prueba: `test_multi_figure_sheet_does_not_treat_fills_as_outlines`,
`test_stroke_width_estimated_from_image`.

## D15. Astillas: conservar fragmentos de líneas finas
Hallazgo principal: el 80 % de la pérdida de bordes ocurría en el **preprocesado** (recall original→
preprocesada 0,805; preprocesada→SVG 0,94). La causa era D6: una línea fina (nariz, párpados) partida por la
cuantización en trozos ≤ 6 px sin píxeles planos se borraba como si fuera antialiasing. Sin la limpieza el
recall en rostros sube a 0,952, pero los componentes se disparan.
Probado y **descartado**: eximir píxeles con top-hat alto (recall 0,948, pero ×4 componentes; en la sintética
de 512 px, 37 → 143).
**Adoptado**: un fragmento se conserva si su L* es al menos 5 menor (o mayor) que la de **todas** sus regiones
vecinas — una línea es más oscura que ambos lados; una transición es intermedia. Rostros: recall 0,863 → 0,921
con +43 % de componentes; sintética 512 px sin cambio (37); 200 px: recall 0,975 → 0,992.
Prueba: `test_sliver_rule_keeps_broken_thin_lines_but_removes_transitions`.

## D16. Trazos aclarados por el antialiasing
Los trazos muy contrastados (top-hat ≥ umbral + 12) entran en la máscara con L* < umbral + 20·e. Efecto
pequeño y consistente (real: ΔE 3,14 → 3,10; 200 px: SSIM 0,9469 → 0,9498). El margen escala con e: con un
margen fijo, énfasis 20 ya incluía líneas grises y el control perdía sensibilidad (lo detectó
`test_outline_emphasis_changes_mask`).

## D17. Experimentos descartados
| Variante | Resultado en la imagen real | Motivo |
| --- | --- | --- |
| Sin filtro mean-shift | recall 0,773 (peor), +48 % rutas | se mantiene D8 |
| Tolerancia de fusión con pérdida +0 (en vez de +4) | ΔE 3,33 → 3,16, pero rutas 4 191 → 7 519 | coste desproporcionado; se mantiene `LOSSY_MERGE_EXTRA = 4` |
| Proteger trazos finos en la reserva de paleta | sin mejora de bordes, 3,5 s → 12,6 s; en sintéticas la paleta pasa de 8 a 24 colores de antialiasing | descartado y eliminado |

## D18. Alfa con ruido de codificación
El 31 % de los píxeles tenía alfa 250–254 (WebP con pérdida) y la advertencia decía «1 161 876 píxeles con alfa
parcial». Ahora el alfa 1–7 y 248–254 se considera ruido: se redondea y se informa como nota, no como
advertencia. La semitransparencia real (34 816 px) sigue avisándose.

## Resultado global en la imagen real (perfil por defecto)
| | Antes | Después |
| --- | --- | --- |
| SSIM | 0,9453 | 0,9551 |
| ΔE2000 medio | 3,33 | 3,11 |
| Recall de bordes | 0,782 | 0,807 |
| Rutas / tamaño | 4 191 / 1,1 MB | 5 087 / 1,3 MB |
| Tiempo | 3,2 s | 3,9 s |

Pérdidas que **persisten**: contorno de la nariz (línea marrón de 1–2 px sobre piel sombreada, se funde con la
sombra), mechones blancos del cabello y degradados de la piel (se convierten en bandas). Los conteos de
componentes no son comparables entre versiones del preprocesado, porque la referencia cambia.

---

# Segunda imagen real (samples/real/APLAUSOS.png)

Imagen: pegatina de caricatura, 417×487 PNG sin pérdida, fondo transparente (2 378 px de alfa parcial),
4 605 colores, contornos negros de 1–3 px, sombreado plano, mechones de 1 px, bandera de 3 franjas de ~3 px.
A diferencia de la primera, es **pequeña**: casi todos sus detalles miden 1–3 px.
Control de regresión: la primera imagen (`brief 8.webp`, recuperada de un trabajo guardado, ya no está en
`samples/real`) y las sintéticas.

Línea base (perfil por defecto): SSIM 0,9216, ΔE 2,48, bordes F1 0,947, IoU de contornos 0,63, 613 rutas.
Atribución: original→preprocesada 0,938 de recall de bordes; preprocesada→SVG 0,968. A diferencia de la primera
imagen, la mayor pérdida visible estaba en el **trazado**: con curvas «Píxel» (bordes exactos de la imagen
preprocesada) el SSIM sube a 0,947, así que el suavizado spline sobre detalles de 1–2 px costaba ~0,025.
Pérdidas visibles: la franja roja de la bandera salía naranja, la línea roja junto a la nariz desaparecía, los
párpados y arrugas finas se cortaban.

## D19. Sobremuestreo del trazado (`supersample`, auto por defecto)
Se amplía la imagen ×k (cúbica sobre alfa premultiplicado) y **cada píxel ampliado toma una etiqueta ya
existente**: la de color más cercano entre las de su vecindario 3×3 en la resolución original. El borde entre
dos regiones queda donde el color interpolado cruza el punto medio, es decir, donde estaba el borde
antialiasado; no se crean colores. VTracer traza a ×k y el SVG conserva `width`/`height` originales con
`viewBox` ×k. `filter_speckle` se multiplica por k para seguir midiendo en píxeles del original.
Auto: k = ⌊1600 / lado mayor⌋ limitado a 1–4 y a 4 MP trazados.

| APLAUSOS, código final (por capas, spline) | SSIM | ΔE | Bordes F1 | IoU contornos | Rutas | Tamaño | Tiempo |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ×1 | 0,9289 | 2,25 | 0,950 | 0,66 | 619 | 0,24 MB | 0,5 s |
| ×2 | 0,9625 | 1,52 | 0,972 | 0,77 | 924 | 0,46 MB | 1,1 s |
| ×3 (auto) | 0,9713 | 1,30 | 0,975 | 0,81 | 943 | 0,64 MB | 1,9 s |
| ×4 | 0,9745 | 1,21 | 0,974 | 0,82 | 979 | 0,84 MB | 3,0 s |

×4 aporta +0,003 de SSIM por +60 % de tiempo y +30 % de bytes: el modo auto se queda en ⌊1600/487⌋ = 3; ×4
puede pedirse explícitamente. Sintéticas con auto: 512 px SSIM 0,976 → 0,993 y 37/37 componentes;
200 px 0,950 → 0,990; JPEG q75 0,967 → 0,983. A partir de 1600 px el factor es 1 y nada cambia.
Probado y **descartado**: ampliar la imagen y vectorizarla tal cual (Lanczos): SSIM 0,970 a ×3 pero 8 938 rutas,
porque el antialiasing ampliado se convierte en bandas de colores intermedios; vecindario 5×5 en lugar de 3×3:
SSIM +0,002 y +43 % de rutas.
Coste: más tiempo (512 px: 0,4 → 2,4 s) y archivos 2–3× mayores (las coordenadas son ×k con 3 decimales).

## D20. Colores de líneas finas en la paleta
La paleta se ajusta con píxeles «planos»; una línea roja de 1–2 px no tiene ninguno, así que su color no
existía y se asignaba al naranja de la sombra (bandera, línea de la nariz). Ahora, en entradas **sin pérdida**,
los píxeles no planos lejanos a la paleta (ΔE > tolerancia de minorías) se comprueban contra todas las mezclas
lineales de dos colores de la paleta: si no son una mezcla (antialiasing), su color entra en el cupo reservado
para minorías (núcleo de la componente: el 25 % más alejado). En APLAUSOS se añaden 6 colores (rojo #bd2026,
marrones de pliegues); 89 px rojos pasan de 0 a 51 con color rojo. En la sintética sin la línea no se protege
nada (prueba `test_thin_line_color_enters_palette_unless_it_is_a_blend`). Con pérdida se omite: los artefactos
de compresión tampoco son mezclas y añadían colores de ruido (WebP con pérdida: 9 → 15 rellenos).

## D21. Astillas reasignadas por color, no por distancia
Una astilla de antialiasing iba al vecino más cercano en posición. Ahora va a la etiqueta vecina (3×3, no
astilla) de color más parecido al del píxel: un píxel entre un mechón claro y pelo negro va con el que más
cubría. APLAUSOS ×1: SSIM 0,9218 → 0,9289, ΔE 2,46 → 2,25; ×3: bordes F1 0,965 → 0,975 y 1 063 → 943 rutas.
Primera imagen: SSIM 0,9551 → 0,9574, ΔE 3,11 → 2,96. Prueba: `test_sliver_pixels_go_to_the_most_similar_neighbour`.

## D22. Otros resultados del barrido (APLAUSOS)
| Variante | Resultado | Decisión |
| --- | --- | --- |
| `max_colors` 128 / 256 (×1) | ΔE 2,48 → 2,36, puntuación peor (más regiones pequeñas) | se mantiene 64 |
| Curvas «Píxel» (×1) | SSIM 0,947, bordes en escalera | útil para pixel art, no por defecto |
| `corner_threshold` 30, `splice_threshold` 30, `length_threshold` 5 (×3) | diferencias ≤ 0,001 | sin cambio |
| Énfasis 100 / 60 (×3) | 100 empeora (0,965); 60 igual (0,971) | se mantiene 80 |

## D23. Carrera en la cancelación
`test_not_ready_then_cancel_cleans_files` falló una vez con el pipeline más lento: el trabajo se marcaba
«cancelado» antes de borrar sus archivos. Ahora se borran primero.

## Resultado en las dos imágenes reales (perfil por defecto)
| | APLAUSOS antes | APLAUSOS ahora | brief 8 antes | brief 8 ahora |
| --- | --- | --- | --- | --- |
| Sobremuestreo | — | ×3 | — | ×1 (2560 px) |
| SSIM | 0,9216 | 0,9713 | 0,9551 | 0,9574 |
| ΔE2000 medio | 2,48 | 1,30 | 3,11 | 2,96 |
| Bordes F1 | 0,947 | 0,975 | 0,873 | 0,879 |
| IoU de contornos | 0,63 | 0,81 | 0,60 | 0,70 |
| Rutas | 613 | 943 | 5 087 | 6 096 |
| Tamaño | 238 KB | 636 KB | 1,3 MB | 1,9 MB |

Pérdidas que **persisten** en APLAUSOS: mechones de 1 px color piel sobre la zona gris del pelo (se cortan o
salen grises), el arco marrón junto a la ceja (más tenue), y el borde semitransparente de la silueta (alfa
binarizado).
