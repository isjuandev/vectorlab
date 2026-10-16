from __future__ import annotations

import io
import time
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app


def cartoon(size: int = 160, transparent: bool = False) -> np.ndarray:
    """Personaje plano mínimo: cabeza con contorno grueso, ojos, boca, pecas y bloque oscuro."""
    img = np.full((size, size, 3), 255, np.uint8)
    s = size / 160
    c = (int(80 * s), int(80 * s))
    cv2.ellipse(img, c, (int(55 * s), int(60 * s)), 0, 0, 360, (170, 205, 246), -1, cv2.LINE_AA)
    cv2.ellipse(img, c, (int(55 * s), int(60 * s)), 0, 0, 360, (20, 20, 20), max(2, int(4 * s)), cv2.LINE_AA)
    for ex in (60, 100):
        cv2.circle(img, (int(ex * s), int(70 * s)), int(9 * s), (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(img, (int(ex * s), int(70 * s)), int(4 * s), (20, 20, 20), -1, cv2.LINE_AA)
    cv2.ellipse(img, (int(80 * s), int(105 * s)), (int(18 * s), int(8 * s)), 0, 0, 180, (45, 35, 205), -1,
                cv2.LINE_AA)
    cv2.line(img, (int(62 * s), int(52 * s)), (int(75 * s), int(50 * s)), (20, 20, 20), max(1, int(2 * s)),
             cv2.LINE_AA)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    alpha = np.full((size, size), 255, np.uint8)
    if transparent:
        alpha[:] = 0
        cv2.ellipse(alpha, c, (int(57 * s), int(62 * s)), 0, 0, 360, 255, -1, cv2.LINE_AA)
    return np.dstack([rgb, alpha])


def encode(rgba: np.ndarray, fmt: str = "PNG", **kw) -> bytes:
    img = Image.fromarray(rgba, "RGBA")
    if fmt == "JPEG":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "jobs", max_dimension=2000, max_pixels=4_000_000, max_upload_mb=5)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


def wait_for(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body["state"] in ("completed", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError("el trabajo no terminó a tiempo")
