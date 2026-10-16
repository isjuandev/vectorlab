# Backend de VectorLab (FastAPI + VTracer) para Coolify.
# Contexto de construcción: carpeta backend/ (Base Directory = /backend en Coolify).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Usuario sin privilegios para ejecutar el servicio.
RUN groupadd --system --gid 1001 vectorlab \
 && useradd --system --uid 1001 --gid vectorlab --home /app vectorlab

# Dependencias primero para aprovechar la caché de capas.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app

# Trabajos generados (originales, SVG, vistas previas). Montar un volumen persistente en /data.
ENV VECTORLAB_HOST=0.0.0.0 \
    VECTORLAB_PORT=8000 \
    VECTORLAB_DATA_DIR=/data/jobs
RUN mkdir -p /data/jobs && chown -R vectorlab:vectorlab /data

USER vectorlab
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"

CMD ["python", "-m", "app"]
