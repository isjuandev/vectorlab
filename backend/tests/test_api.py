from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import cartoon, encode, wait_for


def _post(client: TestClient, data: bytes, params: dict | None = None, name: str = "img.png"):
    files = {"file": (name, data, "application/octet-stream")}
    form = {"params": json.dumps(params)} if params is not None else {}
    return client.post("/api/v1/jobs", files=files, data=form)


def test_health_and_capabilities(client: TestClient) -> None:
    assert client.get("/api/v1/health").json()["status"] == "ok"
    caps = client.get("/api/v1/capabilities").json()
    assert caps["engines"][0]["name"] == "vtracer" and caps["engines"][0]["version"] == "0.6.15"
    ids = {c["id"] for c in caps["controls"]}
    assert {"max_colors", "detail_preservation", "outline_emphasis", "strategy", "curve_mode"} <= ids
    for c in caps["controls"]:  # especificación completa por control (sección 14)
        for key in ("label", "type", "default", "unit", "stage", "expected_effect", "no_effect_cases"):
            assert key in c
    assert caps["profiles"][0]["defaults"]["max_colors"] == 64


def test_full_flow_png(client: TestClient) -> None:
    r = _post(client, encode(cartoon()), {"strategy": "auto"})
    assert r.status_code == 202, r.text
    job = wait_for(client, r.json()["job_id"])
    assert job["state"] == "completed", job
    assert job["progress"] == 100 and job["exports"] and job["metrics_summary"]["ssim"] > 0.9
    assert job["effective_params"]["engine"]["version"] == "0.6.15"
    assert any(c["selected"] for c in job["candidates"])

    svg = client.get(job["exports"]["svg"])
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert "attachment" in svg.headers["content-disposition"]
    assert "default-src 'none'" in svg.headers["content-security-policy"]
    assert "<path" in svg.text and "<image" not in svg.text and "base64" not in svg.text

    inline = client.get(job["exports"]["svg"] + "?disposition=inline")
    assert inline.headers["content-disposition"].startswith("inline")

    png = client.get(job["exports"]["png"])
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(job["exports"]["preview"]).status_code == 200

    metrics = client.get(job["exports"]["metrics"]).json()
    assert {"metrics", "candidates", "effective_params", "requested_params", "timings_s"} <= set(metrics)

    other = [c for c in job["candidates"] if not c["selected"]]
    if other:
        alt = client.get(f"{job['exports']['svg']}?candidate={other[0]['id']}")
        assert alt.status_code == 200 and "<path" in alt.text


@pytest.mark.parametrize("fmt,kw,name", [("JPEG", {"quality": 85}, "a.jpg"), ("WEBP", {"quality": 80}, "a.webp")])
def test_other_formats(client: TestClient, fmt: str, kw: dict, name: str) -> None:
    r = _post(client, encode(cartoon(), fmt, **kw), {}, name)
    assert wait_for(client, r.json()["job_id"])["state"] == "completed"


def test_rejects_invalid_file(client: TestClient) -> None:
    r = _post(client, b"GIF89a" + b"\0" * 64, None, "trap.png")
    assert r.status_code == 415 and r.json()["error"]["code"] == "invalid_image"


def test_rejects_corrupt_file(client: TestClient) -> None:
    data = encode(cartoon())
    r = _post(client, data[:40])
    assert r.status_code in (415, 422)


def test_rejects_too_large(settings: Settings) -> None:
    small = settings.model_copy(update={"max_upload_mb": 0.002})
    with TestClient(create_app(small)) as c:
        r = _post(c, encode(cartoon(300)))
        assert r.status_code == 413 and r.json()["error"]["code"] == "limit_exceeded"


@pytest.mark.parametrize("params", [{"max_colors": 1}, {"outline_emphasis": 101}, {"unknown": 1},
                                    {"strategy": "layered", "outline_emphasis": 0},
                                    {"background_mode": "remove_uniform", "preserve_alpha": False},
                                    {"visual_validation": False, "strategy": "auto", "candidate_budget": 2},
                                    {"advanced": {"length_threshold": 1}}])
def test_rejects_invalid_or_incompatible_params(client: TestClient, params: dict) -> None:
    r = _post(client, encode(cartoon()), params)
    assert r.status_code == 422 and r.json()["error"]["code"] == "incompatible_params", r.text


def test_rejects_malformed_params_json(client: TestClient) -> None:
    r = client.post("/api/v1/jobs", files={"file": ("a.png", encode(cartoon()))}, data={"params": "{nope"})
    assert r.status_code == 422


def test_unknown_job_and_traversal(client: TestClient) -> None:
    assert client.get("/api/v1/jobs/" + "0" * 32).status_code == 404
    assert client.get("/api/v1/jobs/..%2F..%2Fetc").status_code == 404
    r = _post(client, encode(cartoon()))
    job = wait_for(client, r.json()["job_id"])
    bad = client.get(f"/api/v1/jobs/{job['job_id']}/download.svg?candidate=../../report")
    assert bad.status_code == 404


class _SlowEngine:
    """Envuelve el motor real añadiendo una espera para probar estados intermedios y cancelación."""

    def __init__(self, inner, started: threading.Event, delay: float) -> None:
        self.inner, self.started, self.delay = inner, started, delay
        self.name, self.version = inner.name, inner.version

    def validate_config(self, cfg):  # noqa: ANN001, ANN201
        return self.inner.validate_config(cfg)

    def trace(self, rgba, cfg, binary=False):  # noqa: ANN001, ANN201
        self.started.set()
        time.sleep(self.delay)
        return self.inner.trace(rgba, cfg, binary)


def test_not_ready_then_cancel_cleans_files(settings: Settings) -> None:
    app = create_app(settings)
    started = threading.Event()
    with TestClient(app) as c:
        c.app.state.jobs.runner.engine = _SlowEngine(app.state.engine, started, 0.8)
        r = _post(c, encode(cartoon()), {"strategy": "integral"})
        job_id = r.json()["job_id"]
        assert started.wait(10)
        assert c.get(f"/api/v1/jobs/{job_id}/download.svg").status_code == 409
        running = c.get(f"/api/v1/jobs/{job_id}").json()
        assert running["state"] == "running" and 0 < running["progress"] < 100
        c.post(f"/api/v1/jobs/{job_id}/cancel")
        final = wait_for(c, job_id)
        assert final["state"] == "cancelled"
        assert not (settings.data_dir / job_id).exists()


def test_original_is_stored_read_only(client: TestClient, settings: Settings) -> None:
    r = _post(client, encode(cartoon()))
    job = wait_for(client, r.json()["job_id"])
    original = settings.data_dir / job["job_id"] / "original.png"
    assert original.exists() and not (original.stat().st_mode & 0o222)
