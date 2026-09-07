import pytest
from conftest import project_with_source


def test_health_is_public_but_projects_require_header(client):
    client.headers.pop("X-CleanTake-Token")
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert "workspace" not in health.text and "secret" not in health.text
    for headers in ({}, {"X-CleanTake-Token": "wrong"}):
        result = client.get("/api/projects", headers=headers)
        assert result.status_code == 401
        assert result.json()["error"]["code"] == "invalid_session"
    assert client.get("/api/projects?token=test-session-secret").status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "attacker.example"},
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
        {"Origin": "http://localhost:8765"},
        {"Host": "127.0.0.1.attacker.example:8765"},
        {"Host": "127.0.0.1:8765@attacker.example"},
    ],
)
def test_foreign_hosts_and_origins_are_forbidden_even_with_token(client, headers):
    result = client.get("/api/projects", headers=headers)
    assert result.status_code == 403
    assert "error" in result.json()


def test_same_origin_allowed_and_errors_are_redacted_json(client):
    assert (
        client.get("/api/projects", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
    )
    for path in ("/api/unknown", "/api/projects/not-a-uuid", "/api/projects/%2E%2E%2Fsecret"):
        result = client.get(path)
        assert result.status_code in {404, 422}
        assert "error" in result.json()
        assert "/Users/" not in result.text
    malicious = "private-transcript-secret /Users/example #test-session-secret"
    result = client.post("/api/projects", json={"name": {"secret": malicious}})
    assert result.status_code == 422
    assert malicious not in result.text
    result = client.post(
        "/api/projects", content="{broken", headers={"Content-Type": "application/json"}
    )
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "invalid_request"


def test_upload_limit_rejects_declared_and_streamed_bodies(client):
    client.app.state.limits.max_upload_bytes = 1024
    project = client.post("/api/projects", json={"name": "Limits"}).json()
    path = f"/api/projects/{project['id']}/sources"
    oversized = client.post(path, files={"file": ("huge.wav", b"a" * 2048)})
    assert oversized.status_code == 413
    streamed = client.post(
        path,
        content=iter([b"x" * 1000, b"x" * 1000]),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert streamed.status_code == 413
    assert list((client.app.state.workspace / "uploads").iterdir()) == []


def test_public_source_dto_does_not_expose_storage_paths(client):
    project = project_with_source(client)
    assert project["sources"][0]["original_filename"] == "Main Ω.wav"
    assert "original_path" not in project["sources"][0]
    assert "path" not in project["sources"][0]["audio"]
    assert "no-referrer" == client.get("/api/projects").headers["referrer-policy"]
    assert "default-src 'self'" in client.get("/").headers["content-security-policy"]


@pytest.mark.parametrize(
    "origin", ["http://[", "http://127.0.0.1:bad", "http://user@127.0.0.1:8765"]
)
def test_malformed_origin_is_a_forbidden_json_error(client, origin):
    response = client.get("/api/projects", headers={"Origin": origin})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden_origin"


def test_non_ascii_invalid_token_is_an_unauthorized_json_error(client):
    response = client.get("/api/projects", headers={b"X-CleanTake-Token": b"\xff"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


def test_validation_never_echoes_private_transcript_keys(client):
    project = project_with_source(client)
    secret = "secret-transcript-word"
    result = client.post(
        f"/api/projects/{project['id']}/transcript",
        json={
            "text": '{"segments":[{"start":0,"end":1,"text":"hi","' + secret + '":0}]}',
            "source_id": project["sources"][0]["id"],
            "filename": "private.json",
            "expected_revision": project["revision"],
        },
    )
    if result.status_code != 200:
        assert secret not in result.text


def test_streamed_multipart_bytes_are_limited_before_spooling(client):
    client.app.state.limits.max_upload_bytes = 1024
    project = client.post("/api/projects", json={"name": "Streamed"}).json()
    boundary = "cleantake-test-boundary"
    chunks = [
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            'filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n'
        ).encode(),
        b"x" * 600,
        b"y" * 600,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    response = client.post(
        f"/api/projects/{project['id']}/sources",
        content=iter(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"
    assert list((client.app.state.workspace / "uploads").iterdir()) == []


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json",
        "application/vnd.cleantake+json",
        "Application/JSON; charset=utf-8",
        "",
    ],
)
def test_json_body_limit_covers_all_json_interpretations(client, content_type):
    client.app.state.limits.json_bytes = 128
    body = b'{"name":"Small actual name"}' + b" " * 1024
    result = client.post(
        "/api/projects",
        content=body,
        headers={"Content-Type": content_type} if content_type else {},
    )
    assert result.status_code == 413
    assert client.get("/api/projects").json()["projects"] == []
