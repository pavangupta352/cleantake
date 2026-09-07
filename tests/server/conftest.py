import io
import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from cleantake.server import create_app


@pytest.fixture
def client(tmp_path):
    application = create_app(tmp_path, token="test-session-secret")
    with TestClient(application, base_url="http://127.0.0.1:8765") as connection:
        connection.headers["X-CleanTake-Token"] = "test-session-secret"
        yield connection


def wav_bytes(samples=None):
    if samples is None:
        samples = np.random.default_rng(827).normal(0, 0.1, 96_000).astype("float32")
    stream = io.BytesIO()
    sf.write(stream, samples, 48_000, format="WAV", subtype="FLOAT")
    return stream.getvalue()


def wait_job(client, job, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job['id']}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"Job did not finish: {job}")


def project_with_source(client, samples=None):
    response = client.post("/api/projects", json={"name": "Interview Ω"})
    assert response.status_code == 201, response.text
    project = response.json()
    response = client.post(
        f"/api/projects/{project['id']}/sources",
        files={"file": ("Main Ω.wav", wav_bytes(samples), "audio/wav")},
    )
    assert response.status_code == 202, response.text
    job = wait_job(client, response.json())
    assert job["status"] == "completed", job
    return client.get(f"/api/projects/{project['id']}").json()
