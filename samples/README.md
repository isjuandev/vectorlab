# Muestras

- `synthetic/` — imágenes **sintéticas** generadas por `scripts/make_samples.py` (personaje plano con contornos
  gruesos y finos, sombras en bloque, pecas de 2–3 px, fondo blanco/de color/transparente, PNG/JPEG/WebP,
  200–1600 px). Sirven para pruebas funcionales y de sensibilidad. **No son evidencia de fidelidad sobre
  ilustraciones reales.**
- `real/` — coloque aquí caricaturas e ilustraciones reales para evaluarlas con
  `backend/.venv/bin/python scripts/evaluate_samples.py`. La carpeta está en `.gitignore` porque esas imágenes
  suelen tener derechos de autor.
