# VectorLab

Herramienta web **local** que convierte imágenes rasterizadas (PNG, JPEG, WebP) en **SVG editable con
geometría vectorial real**, priorizando la fidelidad visual de caricaturas e ilustraciones de colores planos
con contornos negros. Funciona sin internet, sin cuentas y sin servicios externos: el navegador habla con un
backend Python que escucha solo en `127.0.0.1`.

- No redibuja ni "inventa": vectoriza la imagen de entrada con [VTracer](https://github.com/visioncortex/vtracer).
- No promete fidelidad perfecta: **mide** cada resultado (SSIM, ΔE2000, bordes, regiones, componentes perdidos)
  y muestra las pérdidas detectadas.
- El SVG nunca contiene la imagen rasterizada incrustada (se verifica en cada conversión).

| Servicio | Dirección |
| --- | --- |
| Frontend | <http://localhost:3000> |
| Backend (API) | <http://127.0.0.1:8000> |
| Documentación de la API | <http://127.0.0.1:8000/docs> |

## Requisitos

- macOS (probado en macOS 27, Apple Silicon). Debería funcionar en Linux con los mismos pasos.
- [uv](https://docs.astral.sh/uv/) (recomendado; descarga Python 3.12 si hace falta) **o** `python3.12`.
  VTracer 0.6.15 publica wheels para Python 3.12; el Python 3.14 del sistema no se usa.
- Node.js ≥ 20 y npm (probado con Node 26.4 / npm 10.9).
- Conexión a internet **solo para instalar** dependencias. La vectorización es 100 % local.

## Instalación

```bash
./scripts/setup.sh
```

Crea `backend/.venv` (Python 3.12) con `backend/requirements-dev.txt` e instala el frontend con `npm ci`.
Para las pruebas E2E instale además el navegador de Playwright:

```bash
cd frontend && npx playwright install chromium
```

## Arranque y parada

```bash
./scripts/dev.sh
```

Arranca el backend (espera a que `/api/v1/health` responda) y después el frontend. Si cualquiera de los dos
termina, detiene el otro. Comprueba antes que los puertos 8000 y 3000 estén libres.

**Detener:** `Ctrl+C` en esa terminal (o `kill -TERM <pid de dev.sh>`). Ambos procesos se terminan.

Por separado, si se prefiere:

```bash
cd backend && .venv/bin/python -m app
```

```bash
cd frontend && npm run dev
```

## Uso

1. Arrastre una imagen a la zona de carga (o haga clic). Se valida el **contenido real** (firma binaria),
   el tamaño y las dimensiones antes de enviarla; el backend vuelve a validarlo todo.
2. Ajuste los parámetros (se conservan durante la sesión del navegador) y pulse **Vectorizar**.
3. Siga el progreso por etapas; puede **cancelar** en cualquier momento.
4. Compare original y SVG: deslizador, vista dividida con zoom y desplazamiento sincronizados, ajuste a
   pantalla, 1:1, fondo de transparencia configurable y marcado de pérdidas detectadas.
5. Revise métricas, advertencias, paleta, decisiones del pipeline y parámetros efectivos.
6. Descargue el SVG, el PNG de vista previa o el SVG de cualquier candidato evaluado. **Reprocesar** reutiliza
   el archivo cargado con los parámetros nuevos.

## Formatos y límites

| Aspecto | Valor por defecto | Variable |
| --- | --- | --- |
| Formatos | PNG, JPEG, WebP (estático; de un animado se usa el 1.er fotograma) | — |
| Tamaño máximo de archivo | 25 MB | `VECTORLAB_MAX_UPLOAD_MB` |
| Lado máximo / mínimo | 6000 px / 8 px | `VECTORLAB_MAX_DIMENSION`, `VECTORLAB_MIN_DIMENSION` |
| Píxeles máximos | 24 000 000 | `VECTORLAB_MAX_PIXELS` |
| Resolución de métricas | 4 000 000 px (se reduce por encima) | `VECTORLAB_METRICS_MAX_PIXELS` |

**Memoria y tiempo medidos** (M-series, perfil por defecto, 2 candidatos): 512 px ≈ 2,4 s (sobremuestreo
automático ×3; 0,4 s con ×1); 417×487 px ≈ 1,9 s; 1600 px ≈ 3,7 s;
3000 px ≈ 8 s / 2,3 GB de memoria pico; 4800 px (23 MP) ≈ 21 s / 3,1 GB. Las imágenes cercanas al límite
requieren varios GB de RAM libres; baje `VECTORLAB_MAX_PIXELS` en equipos con poca memoria.

## Variables de entorno

Backend: copie `backend/.env.example` a `backend/.env` (prefijo `VECTORLAB_`). Además de los límites anteriores:
`VECTORLAB_HOST` (por defecto `127.0.0.1`; cambiarlo expone el servicio a la red), `VECTORLAB_PORT`,
`VECTORLAB_DATA_DIR` (por defecto `output/jobs`), `VECTORLAB_WORKER_THREADS` (1),
`VECTORLAB_JOB_TTL_HOURS` (24), `VECTORLAB_MAX_RETAINED_JOBS` (50), `VECTORLAB_MAX_CANDIDATE_BUDGET` (4),
`VECTORLAB_CORS_ORIGINS` (JSON; por defecto solo `localhost:3000` y `127.0.0.1:3000`).

Frontend: `NEXT_PUBLIC_API_BASE` (por defecto `http://127.0.0.1:8000`), se incrusta al compilar.

## Pruebas

```bash
cd backend && .venv/bin/python -m pytest
```

```bash
cd backend && .venv/bin/ruff check app tests ../scripts
```

```bash
cd frontend && npm run typecheck && npm run lint && npm test
```

```bash
cd frontend && npm run test:e2e
```

La prueba E2E usa los servicios reales (los arranca si no están en marcha) y las muestras de `samples/synthetic`.
Resultados de la última ejecución en [docs/phase-reports.md](docs/phase-reports.md).

Herramientas de evaluación (sin interfaz):

```bash
backend/.venv/bin/python scripts/evaluate_samples.py --json output/evaluation/resultado.json
```

`scripts/diagnose_edges.py IMAGEN --crop y0,y1,x0,x1 --out mapa.png` indica si un detalle se pierde en la
paleta o en el trazado. `scripts/make_samples.py` regenera las muestras sintéticas; `scripts/poc_vtracer.py` repite la prueba de
concepto y las sondas sobre el comportamiento real de VTracer.

## Parámetros

Perfil predeterminado `cartoon_fidelity_v1`: modo auto, 64 colores, conservación de detalles 100 %, énfasis
en contornos 80 %, transparencia y validación visual activadas, sobremuestreo del trazado automático (las
imágenes de menos de 1600 px se trazan a ×2–×4 sin añadir colores; el SVG conserva el tamaño original). La especificación completa de cada control
(rango, unidad, etapa, parámetros nativos, operación personalizada, casos sin efecto y prueba de sensibilidad)
está en [docs/controls.md](docs/controls.md) y también se sirve en `GET /api/v1/capabilities`.

Para cambiar el perfil por defecto, edite `VectorizeParams` en `backend/app/schemas.py` y la traducción a
parámetros nativos en `backend/app/services/controls.py` (`derive_engine_config`). En la interfaz, los
**ajustes avanzados** permiten sobrescribir cada parámetro nativo de VTracer; el override queda registrado
como tal en el informe.

## Cambiar o añadir un motor

El pipeline depende del contrato `VectorizerEngine` (`backend/app/vectorization/base.py`):
`validate_config(config)` y `trace(rgba, config, binary=False) -> TraceResult`. Para añadir otro motor
(p. ej. Potrace para máscaras binarias) implemente esa interfaz y pásela a `JobManager` en
`backend/app/main.py`. El frontend no depende de detalles del motor.

## Estructura

```
backend/app/
  main.py, __main__.py   aplicación FastAPI y arranque
  config.py, schemas.py, errors.py
  api/routes.py          rutas HTTP v1 (sin lógica de negocio)
  services/              pipeline.py (orquestación), jobs.py (trabajos), controls.py (perfil y especificación)
  preprocessing/         decode, background/alfa, palette, outlines, labels, color
  vectorization/         base (contrato), vtracer_engine (adaptador), compose (reconstrucción SVG)
  validation/            svg_check, render (resvg), metrics
  storage/files.py       rutas de trabajos controladas
backend/tests/           pytest: unitarias, integración API, sensibilidad, pipeline
frontend/                Next.js: app/, components/, hooks/, lib/, types/, tests/ (Vitest), e2e/ (Playwright)
scripts/                 setup.sh, dev.sh, make_samples.py, poc_vtracer.py, evaluate_samples.py
samples/                 synthetic/ (generadas) y real/ (suyas, ignoradas por git)
docs/                    decisiones, controles, métricas, informes de fase
output/                  trabajos, PoC, evaluaciones y capturas (ignorado por git)
```

## API

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/api/v1/health` | Estado |
| GET | `/api/v1/capabilities` | Formatos, límites, motor, perfil, especificación de controles |
| POST | `/api/v1/jobs` | Multipart: `file` + `params` (JSON de `VectorizeParams`). 202 con el trabajo |
| GET | `/api/v1/jobs/{id}` | Estado, etapa, progreso, parámetros efectivos, advertencias, exportaciones |
| POST | `/api/v1/jobs/{id}/cancel` | Cancelación cooperativa; borra los archivos del trabajo |
| GET | `/api/v1/jobs/{id}/metrics` | Informe completo (métricas por candidato, pérdidas, tiempos, decisiones) |
| GET | `/api/v1/jobs/{id}/preview` | PNG renderizado del SVG elegido |
| GET | `/api/v1/jobs/{id}/download.svg` | SVG (`?candidate=<id>`, `?disposition=inline`) |
| GET | `/api/v1/jobs/{id}/download.png` | PNG de vista previa (`?candidate=<id>`) |

Errores: `{"error": {"code", "message", "details"}}` con códigos estables (`invalid_image` 415,
`corrupt_image` 422, `limit_exceeded` 413, `incompatible_params` 422, `job_not_found` 404, `job_not_ready` 409…).

## Seguridad

Archivos tratados como no confiables: tipo validado por firma, límites de tamaño/dimensiones/píxeles,
protección contra bombas de descompresión, identificadores UUID internos (el nombre original nunca forma
una ruta), lista blanca de artefactos descargables, copia original de solo lectura, SVG validado (sin
`<image>`, `<script>`, `href`, atributos `on*`) y servido con `Content-Security-Policy: default-src 'none'`,
CORS limitado al frontend local, backend solo en loopback. Los registros contienen identificadores,
etapas y tiempos, nunca contenido de imágenes. Los trabajos se purgan tras `VECTORLAB_JOB_TTL_HOURS` o al
superar `VECTORLAB_MAX_RETAINED_JOBS`; los cancelados se borran de inmediato.

## Despliegue en Coolify

Dos aplicaciones Docker independientes, cada una con su `Dockerfile`:

| Servicio | Base Directory | Puerto | Build variables | Volumen persistente |
| --- | --- | --- | --- | --- |
| Backend | `/backend` | `8000` | — | `/data/jobs` |
| Frontend | `/frontend` | `3000` | `NEXT_PUBLIC_API_BASE` | — |

1. **Backend.** Nueva aplicación → repositorio `isjuandev/vectorlab`, rama `main`, *Build Pack*: Dockerfile,
   *Base Directory*: `/backend`. Variables de entorno:
   - `VECTORLAB_CORS_ORIGINS` = `["https://<dominio-del-frontend>"]` (obligatorio; por defecto solo localhost).
   - Opcional: `VECTORLAB_JOB_TTL_HOURS`, `VECTORLAB_MAX_UPLOAD_MB`, etc. (ver `backend/.env.example`).
   - Añadir un *Persistent Storage* con destino `/data/jobs` para conservar los trabajos entre redespliegues.
   - Dominio: por ejemplo `https://api.<dominio>` con puerto `8000`.
   - Mantener **una sola réplica**: el estado de los trabajos vive en memoria del proceso.
2. **Frontend.** Nueva aplicación → mismo repositorio, *Base Directory*: `/frontend`, Dockerfile.
   - `NEXT_PUBLIC_API_BASE` = `https://api.<dominio>` marcada como **Build Variable** (Coolify la pasa como
     `ARG` al construir; Next la incrusta en el bundle, por lo que cambiarla exige reconstruir).
   - Dominio: por ejemplo `https://<dominio>` con puerto `3000`.

Comprobación rápida del backend: `https://api.<dominio>/api/v1/health` debe responder `{"status":"ok", ...}`.

Para probar las imágenes en local (con Docker en marcha):

```bash
docker build -t vectorlab-backend ./backend
docker build -t vectorlab-frontend --build-arg NEXT_PUBLIC_API_BASE=http://localhost:8000 ./frontend
```

## Limitaciones conocidas

- **Fidelidad no garantizada.** Se han evaluado dos ilustraciones reales: una hoja de 6 poses (2560×1440, WebP
  con pérdida; SSIM 0,957, ΔE2000 medio 3,0) y una pegatina pequeña (417×487 PNG; SSIM 0,971, ΔE 1,3).
  Persisten pérdidas en mechones de 1 px sobre zonas sombreadas, en líneas finas de color sobre piel sombreada
  de imágenes con pérdida y en degradados de piel (se convierten en bandas). Detalle en `docs/decisions.md`
  (D14–D23). No se ha comparado con otras herramientas.
- El sobremuestreo hace los SVG de imágenes pequeñas 2–3× más pesados (coordenadas ×k) y el proceso más lento.
- VTracer pierde parches de 1 px salvo en modo de curvas «Píxel», y parches de 2 px si `filter_speckle ≥ 1`.
- El alfa parcial se **binariza** (VTracer trata cualquier alfa > 0 como opaco): los bordes semitransparentes
  y las sombras difuminadas no se conservan como transparencia.
- Los degradados se convierten en bandas de color plano (es un vectorizador de colores planos).
- La cancelación es cooperativa: una llamada de VTracer en curso no se interrumpe; el trabajo se detiene al
  terminar esa etapa.
- Los trabajos viven en memoria: al reiniciar el backend se pierde su estado (los archivos se purgan por TTL).
- El modo «por capas» no siempre mejora: produce ~3–5× más rutas; en las muestras sintéticas sin pérdida
  puntúa algo peor que el integral y gana en JPEG/WebP con pérdida y a 200 px. Por eso el modo auto lo elige
  solo cuando las métricas lo favorecen.
- Potrace no se integró: no está instalado y ninguna prueba ha justificado su uso todavía.

Más detalle en [docs/decisions.md](docs/decisions.md) y [docs/metrics.md](docs/metrics.md).
