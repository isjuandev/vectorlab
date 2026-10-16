# Métricas de calidad

Implementación: `backend/app/validation/metrics.py`. El SVG se renderiza con **resvg** a la resolución de
comparación (la original, o reducida para que no supere `VECTORLAB_METRICS_MAX_PIXELS`; el original se
reduce con `INTER_AREA` y las etiquetas con vecino más cercano). Con sobremuestreo (D19) el SVG se sigue
renderizando al tamaño original: las métricas no se benefician de la resolución ×k. Las regiones y componentes
se comparan con el mapa de etiquetas a 1×, de modo que un borde colocado con precisión de subpíxel puede contar
como desacuerdo en el píxel fronterizo (la concordancia de regiones apenas sube aunque el SSIM sí lo haga).

Representaciones comparables: color y estructura sobre la imagen **compuesta sobre blanco**; transparencia
por separado (IoU de alfa ≥ 128). Se compara contra el **original decodificado** (sRGB, EXIF aplicado), salvo
las métricas de regiones/componentes, que se comparan contra la imagen **preprocesada** (lo que recibió el
motor) para medir la pérdida del trazado.

| Métrica | Definición | Lectura |
| --- | --- | --- |
| `ssim` | SSIM de luminancia (scikit-image) | 1 = idéntico |
| `delta_e_mean`, `delta_e_p95` | CIEDE2000 por píxel en píxeles opacos en ambos (muestreo fijo de 600 000 px si hay más) | < 1 apenas perceptible |
| `delta_e_interior_mean` | ΔE fuera de una banda de 2 px alrededor de los bordes Canny | separa error de color del antialiasing |
| `edge_mean_distance_px` | distancia media simétrica entre bordes Canny (50/150) | px |
| `edge_recall_1_5px`, `edge_precision_1_5px`, `edge_f1` | fracción de bordes con correspondencia a ≤ 1,5 px | |
| `region_agreement` | fracción de píxeles cuyo color de paleta (render → color de paleta más cercano en Lab) coincide con la imagen preprocesada | |
| `region_mean_iou` | IoU medio por color de paleta (colores con ≥ 16 px) | |
| `outline_iou` | IoU de la máscara de líneas oscuras (misma política que `outline_emphasis`) | `null` si e = 0 |
| `alpha_iou` | IoU de silueta opaca | `null` sin alfa |
| `components_*` | componentes conexas (8-vecindad, ≥ 2 px) de la imagen preprocesada; «conservada» si ≥ 50 % de sus píxeles tienen el mismo color en el render | |
| `small_components_*` | las de área ≤ max(16 px, 0,05 % de la imagen) | detalles faciales, pecas, brillos |
| `lost_components` | las 25 mayores pérdidas con color, área, caja y fracción coincidente | se pueden marcar en el visor |
| SVG | rutas, nodos (pares de coordenadas), segmentos, colores de relleno, bytes, ráster incrustado | |
| tiempos | por etapa y total | |

## Puntuación de selección

```
score = 0,35·ssim + 0,30·region_agreement + 0,20·edge_f1 + 0,15·(1 − min(1, ΔE_medio/10)) − 0,10·(perdidas/total)
```

Solo sirve para **ordenar candidatos del mismo trabajo** (misma entrada y mismo preprocesado). No es una
medida absoluta de fidelidad ni es comparable entre imágenes distintas. Los pesos son una elección de
diseño documentada, no calibrada contra juicios humanos.

## Limitaciones

- Componentes de 1–2 px de ancho pueden contarse como perdidos por el antialiasing del renderizador aunque
  sean visibles; por eso se informa la fracción coincidente.
- En imágenes con pérdida el conteo de componentes incluye restos de ruido de compresión.
- SSIM de luminancia no ve diferencias de tono con igual luminancia: lo cubre ΔE.
- Los conteos de componentes (y por tanto la penalización de la puntuación) se miden frente a la imagen
  preprocesada: no son comparables entre versiones del preprocesado. Para comparar versiones use SSIM, ΔE y
  bordes, que se miden frente al original.
- Para localizar en qué etapa se pierde un detalle, compare el recall de bordes original→`preprocessed.png`
  con el de `preprocessed.png`→SVG.
