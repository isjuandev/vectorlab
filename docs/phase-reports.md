# Informes de fase

Fecha de ejecución: 2026-10-15. Entorno: macOS 27.0 (arm64), Node 26.4.0, npm 10.9.4, Python 3.12.13 (uv 0.11.17).

---

## Fase 0 — Auditoría y plan técnico

**Implementado.** Inspección del entorno: directorio vacío (proyecto nuevo, sin git). Herramientas: Node, npm,
pnpm, uv, Homebrew, ImageMagick, xmllint. Python del sistema 3.14.4 (VTracer se usa con 3.12 vía uv). Ausentes:
Potrace, Cargo, CairoSVG funcional (sin libcairo), Inkscape.

**Archivos.** Ninguno (solo inspección). Arquitectura y decisiones en `README.md` y `docs/decisions.md`.

**Criterios.** ✔ El plan usa solo herramientas presentes o instalables (VTracer, resvg-py, FastAPI, Next.js).

**Problemas.** Potrace no disponible → queda opcional (D13). CairoSVG no utilizable → resvg-py (D4).

---

## Fase 1 — Prueba de concepto de vectorización

**Implementado.** Instalación y fijado de VTracer 0.6.15; inspección de su API real; generador de muestras
sintéticas; script de PoC que convierte PNG/JPEG/WebP con 5 configuraciones, renderiza con resvg y registra
tiempo, tamaño, rutas, colores, SSIM e IoU de alfa; sondas de `filter_speckle`, alfa parcial y agujeros en
modo binario.

**Archivos.** `scripts/make_samples.py`, `samples/synthetic/*` (8 imágenes), `scripts/poc_vtracer.py`,
`backend/requirements*.txt`. Salidas en `output/poc/` (SVG, PNG, `report.json`).

**Pruebas.** `backend/.venv/bin/python scripts/poc_vtracer.py` → resultados en D3. Ejemplo 512 px PNG:
defaults SSIM 0,9702 / 29 rutas; fidelity SSIM 0,9733; polygon 0,9768; JPEG q75 sin preprocesado:
1 003 colores de relleno.

**Criterios.** ✔ Conversión reproducible (versiones fijadas, k-means con semilla) y resultados inspeccionables.

**Problemas.** Las muestras son sintéticas: no prueban fidelidad sobre caricaturas reales.
Configuración inicial recomendada derivada: `filter_speckle=0`, `color_precision=8`, alfa binarizado,
cuantización previa obligatoria.

---

## Fase 2 — Backend y motor modular

**Implementado.** FastAPI con rutas v1 (health, capabilities, jobs, estado, cancelación, métricas, preview,
descargas SVG/PNG); esquemas Pydantic con validación de compatibilidad; contrato `VectorizerEngine` y
adaptador VTracer con validación de parámetros; decodificación con validación por firma, límites, protección
de bombas de descompresión, EXIF e ICC→sRGB; almacenamiento con UUID y lista blanca; trabajos asíncronos con
cancelación cooperativa y purga; errores tipados; registros sin contenido de imágenes.

**Archivos.** `backend/app/{main,__main__,config,schemas,errors}.py`, `api/routes.py`, `services/{jobs,pipeline,controls}.py`,
`vectorization/{base,vtracer_engine,compose}.py`, `preprocessing/decode.py`, `storage/files.py`.

**Pruebas.** `tests/test_decode.py`, `tests/test_api.py`, `tests/test_engine_and_validation.py`.

**Criterios.** ✔ Procesa archivos válidos, rechaza inválidos (415/422/413), devuelve SVG utilizable.

---

## Fase 3 — Pipeline de fidelidad

**Implementado.** Análisis y reducción de paleta con protección de minorías; limpieza de astillas;
detección de contornos (`outline_emphasis`); trazado por capas vs integral con selección por métricas;
ajuste de rellenos a la paleta; filtro mean-shift para entradas con pérdida; eliminación de fondo uniforme;
render + métricas (SSIM, ΔE2000, bordes, regiones, contornos, alfa, componentes y pérdidas).

**Archivos.** `preprocessing/{palette,outlines,labels,background,color}.py`, `validation/{metrics,render,svg_check}.py`,
`tests/test_preprocessing.py`, `tests/test_sensitivity.py`, `tests/test_pipeline.py`, `scripts/evaluate_samples.py`.

**Pruebas.** Sensibilidad por control (ver `docs/controls.md`). Evaluación:
`backend/.venv/bin/python scripts/evaluate_samples.py --json output/evaluation/synthetic.json`.

| Muestra | Elegido | Puntuación | SSIM | ΔE medio | Bordes F1 | Comp. | Rutas |
| --- | --- | --- | --- | --- | --- | --- | --- |
| char_white_512.png | integral | 0,9754 | 0,9761 | 0,47 | 0,998 | 35/37 | 38 |
| char_transparent_512.png (IoU alfa 0,990) | integral | 0,9615 | 0,9696 | 1,03 | 0,998 | 33/34 | 33 |
| char_white_1600.png | integral | 0,9718 | 0,9874 | 0,23 | 0,953 | 50/55 | 48 |
| char_white_200.png | por capas | 0,8982 | 0,9518 | 1,01 | 0,966 | 27/59 | 155 |
| char_white_512_q75.jpg | por capas | 0,9501 | 0,9701 | 0,90 | 0,982 | 168/205 | 355 |
| char_white_512_lossy.webp | por capas | 0,9667 | 0,9738 | 0,80 | 0,982 | 55/58 | 244 |

**Criterios.** ✔ Cada control relevante modifica una operación real con prueba de sensibilidad.
✔ La capa de contornos no se fuerza: se elige solo si puntúa mejor.

**Problemas corregidos durante la fase.** Astillas de antialiasing (D6); grosor máximo de línea demasiado
estrecho (detectado por prueba); exclusión de «otro tono» que usaba luminancia y descartaba grises;
duplicados de paleta tras el ajuste al color de origen; rellenos fuera de paleta (D7).

**Pendiente.** A 200 px se pierden 32 de 59 componentes pequeños: a esa resolución los rasgos miden 1–3 px.

---

## Fase 4 — Frontend funcional

**Implementado.** Carga por clic/arrastre con validación previa (firma, tamaño, dimensiones); panel de
parámetros conectado (segmentados, deslizadores con entrada numérica, interruptores, avanzados plegables con
override explícito, restablecer, incompatibilidades); progreso por etapas; cancelación; comparador
(deslizador, dividida sincronizada, original, resultado, zoom con rueda y botones, desplazamiento, ajustar,
1:1, fondo cuadrícula/blanco/negro/personalizado, marcado de pérdidas, abrir SVG); panel de métricas,
candidatos (descarga de cada uno), paleta, parámetros efectivos y origen; mensajes de error
recuperable/fatal, advertencias, pérdidas y decisiones; descargas SVG/PNG con estado; persistencia de
parámetros en `sessionStorage`; reprocesar sin recargar.

**Archivos.** `frontend/app/{layout,page}.tsx`, `components/{workbench,upload-zone,params-panel,comparator,metrics-panel,messages-panel}.tsx`,
`hooks/use-vectorize-job.ts`, `lib/{api,params,file-validation}.ts`, `types/api.ts`, `components/ui/*` (shadcn).

**Pruebas.** `npm run typecheck` ✔, `npm run lint` ✔, `npx next build` ✔ (ruta `/` estática).

**Criterios.** ✔ Flujo completo desde el navegador sin terminal.

---

## Fase 5 — Integración y control de calidad

**Pruebas ejecutadas (resultado final).**

| Comando | Resultado |
| --- | --- |
| `cd backend && .venv/bin/python -m pytest` | **75 passed** (3,1 s) |
| `cd backend && .venv/bin/ruff check app tests ../scripts` | All checks passed |
| `cd frontend && npm run typecheck && npm run lint` | sin errores |
| `cd frontend && npx vitest run` | **18 passed** (3 archivos) |
| `cd frontend && npx playwright test` | **6 passed** (servicios arrancados por Playwright) |
| `xmllint --noout result.svg` | XML bien formado |
| `magick result.svg out.png`, `qlmanage -t result.svg` | renderizado correcto (ImageMagick 7.1.2, Quick Look) |
| `./scripts/dev.sh` + Ctrl+C (pseudo-terminal) | ambos servicios arriba; parada limpia sin procesos huérfanos |
| `./scripts/dev.sh` con puerto 8000 ocupado | aborta con mensaje y `exit 1` |
| CORS con `Origin: http://evil.example` | sin `Access-Control-Allow-Origin` |

Cobertura funcional E2E: carga PNG → parámetros enviados y recibidos por el backend (`requested_params`) →
resultado → modos del comparador, zoom, 1:1 → descarga SVG (contiene `<path>`, sin `<image>` ni base64) y
PNG (firma válida) → reprocesar con otros parámetros → persistencia tras recargar; WebP transparente (IoU
alfa > 95 %); JPEG con filtro mean-shift; archivo falso rechazado sin llamar al backend; configuración
incompatible bloqueada; cancelación de un trabajo de 1600 px.

Rendimiento medido: ver README («Memoria y tiempo medidos»).

**Criterios.** ✔ Flujo principal reproducible; sin errores críticos conocidos pendientes.

---

## Fase 6 — Ejecución local y documentación

**Implementado.** `scripts/setup.sh`, `scripts/dev.sh` (comprobación de dependencias y puertos, espera de
salud, parada conjunta compatible con bash 3.2), `python -m app`, `.env.example` (backend y frontend),
README completo, `docs/controls.md`, `docs/metrics.md`, `docs/decisions.md`, este informe, `.gitignore`.

**Criterios.** ✔ Instrucciones de instalación, arranque, parada, variables, formatos, límites, pruebas,
cambio de parámetros y de motor.

---

## Evaluación con imagen real y recalibración

**Implementado.** Evaluación de `samples/real/brief 8.webp`, atribución de pérdidas por etapa, ablaciones y
tres cambios adoptados: grosor de línea estimado de la imagen (D14), conservación de fragmentos de líneas
finas en la limpieza de astillas (D15), trazos aclarados con margen proporcional a e (D16); además, el ruido de
codificación del alfa deja de presentarse como advertencia (D18). Descartados con evidencia: D17.

**Archivos.** `backend/app/preprocessing/{outlines,labels,palette,background}.py`, `app/services/pipeline.py`,
`app/validation/metrics.py` (misma política adaptativa para `outline_iou`), `tests/test_preprocessing.py`
(+4 pruebas), `frontend/e2e/flow.spec.ts` (+1 prueba que recorre `samples/real/` y se omite si está vacío).

**Pruebas.** pytest **79 passed**; ruff limpio; Vitest 18 passed; Playwright **7 passed** (incluida la imagen
real). Imagen real: SSIM 0,9453 → 0,9551, ΔE 3,33 → 3,11, recall de bordes 0,782 → 0,807 (tabla en D18). En
las sintéticas, las métricas medidas contra el original no empeoran (p. ej. 1600 px: SSIM 0,9886 → 0,9893).

**Pendiente.** Contorno de la nariz y otras líneas de color sobre piel sombreada; mechones claros; bandas en
degradados. Una sola imagen real no basta para fijar la calibración.

## Segunda imagen real (APLAUSOS.png) — máxima calidad

**Implementado.** Evaluación de una pegatina de 417×487 px, atribución de pérdidas, barrido de controles y de
nativos de VTracer, y tres cambios adoptados: sobremuestreo del trazado sin colores nuevos (D19, nuevo control
`supersample`, auto por defecto, en API, panel y especificación), colores de líneas finas en la paleta (D20) y
reasignación de astillas por color (D21). Corregida una carrera en la cancelación (D23).

**Archivos.** `backend/app/preprocessing/supersample.py` (nuevo), `preprocessing/{palette,labels}.py`,
`services/{pipeline,controls,jobs}.py`, `vectorization/compose.py`, `schemas.py`; pruebas en
`tests/test_preprocessing.py` (+4) y `tests/test_sensitivity.py` (+1); frontend `types/api.ts`, `lib/params.ts`
(los parámetros guardados de versiones anteriores se conservan), `components/{params-panel,metrics-panel}.tsx`,
`tests/lib.test.ts` (+1).

**Pruebas.** pytest **84 passed**; ruff limpio; typecheck y lint limpios; Vitest **19 passed**; Playwright
**7 passed** (incluida APLAUSOS.png desde `samples/real/`). APLAUSOS: SSIM 0,9216 → 0,9713, ΔE 2,48 → 1,30,
bordes F1 0,947 → 0,975, IoU de contornos 0,63 → 0,81. Primera imagen: SSIM 0,9551 → 0,9574, ΔE 3,11 → 2,96.
Sintéticas: ninguna empeora (512 px SSIM 0,976 → 0,993). Salidas en `output/evaluation/aplausos/`.

**Pendiente.** Mechones de 1 px sobre la zona gris del pelo; borde semitransparente de la silueta (binarizado).

## Pendiente y riesgos

1. **Más imágenes reales**: la calibración se basa en dos ilustraciones reales; conviene añadir varias
   (distintos estilos, fondos opacos, JPEG) a `samples/real/` y repetir la evaluación.
2. Sin comparación con otras herramientas: no se afirma superioridad.
3. Memoria alta en imágenes > 15 MP (≈ 3 GB a 23 MP).
4. La cancelación no interrumpe una llamada de VTracer en curso.
5. Potrace sin evaluar (no instalado).
