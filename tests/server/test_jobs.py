import json
import time
from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
from conftest import project_with_source, wait_job, wav_bytes
from fastapi.testclient import TestClient

from cleantake.server import create_app


def test_cancel_real_import_retains_prior_project_and_releases_writer(client):
    project = project_with_source(client)
    pid = project["id"]
    payload = wav_bytes(np.random.default_rng(21).normal(0, 0.1, 4_800_000).astype("float32"))
    response = client.post(f"/api/projects/{pid}/sources", files={"file": ("long.wav", payload)})
    assert response.status_code == 202
    job = response.json()
    busy = client.patch(
        f"/api/projects/{pid}", json={"name": "Race", "expected_revision": project["revision"]}
    )
    assert busy.status_code == 409
    export = client.post(
        f"/api/projects/{pid}/exports",
        json={"format": "wav", "finish": False, "expected_revision": project["revision"]},
    )
    assert export.status_code == 409
    cancelled = client.post(f"/api/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    terminal = wait_job(client, job)
    assert terminal["status"] == "cancelled", terminal
    saved = client.get(f"/api/projects/{pid}").json()
    assert saved["revision"] == project["revision"]
    assert len(saved["sources"]) == 1
    assert not list((client.app.state.workspace / "uploads").iterdir())
    assert not list((client.app.state.workspace / "pending").iterdir())
    assert (
        client.patch(
            f"/api/projects/{pid}",
            json={"name": "Available", "expected_revision": project["revision"]},
        ).status_code
        == 200
    )


def test_restart_marks_orphaned_jobs_interrupted_and_removes_partial_outputs(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    jid = str(uuid4())
    now = datetime.now(UTC).isoformat()
    record = {
        "id": jid,
        "project_id": str(uuid4()),
        "operation": "import",
        "status": "running",
        "progress": None,
        "message": "Importing",
        "created_at": now,
        "updated_at": now,
        "result": None,
        "error": None,
    }
    (jobs / f"{jid}.json").write_text(json.dumps(record))
    pending = tmp_path / "pending" / jid
    pending.mkdir(parents=True)
    (pending / "partial.f32le").write_bytes(b"partial")
    uploads = tmp_path / "uploads" / jid
    uploads.mkdir(parents=True)
    (uploads / "source.wav").write_bytes(b"source")
    with TestClient(
        create_app(tmp_path, token="new-session"), base_url="http://localhost"
    ) as client:
        result = client.get(f"/api/jobs/{jid}", headers={"X-CleanTake-Token": "new-session"})
        assert result.status_code == 200
        assert result.json()["status"] == "interrupted"
        assert not pending.exists() and not uploads.exists()
    persisted = json.loads((jobs / f"{jid}.json").read_text())
    assert persisted["status"] == "interrupted"


def test_completed_jobs_survive_restart(tmp_path):
    with TestClient(create_app(tmp_path, token="first"), base_url="http://localhost") as client:
        client.headers["X-CleanTake-Token"] = "first"
        project = client.post("/api/projects", json={"name": "Persistent"}).json()
        uploaded = client.post(
            f"/api/projects/{project['id']}/sources", files={"file": ("main.wav", wav_bytes())}
        ).json()
        assert wait_job(client, uploaded)["status"] == "completed"
    with TestClient(create_app(tmp_path, token="second"), base_url="http://localhost") as client:
        job = client.get(
            f"/api/jobs/{uploaded['id']}", headers={"X-CleanTake-Token": "second"}
        ).json()
        assert job["status"] == "completed"
        assert job["result"]["revision"] == 1


def test_cancelling_active_worker_waits_for_termination_before_returning_terminal(client):
    project = project_with_source(client)
    pid = project["id"]
    payload = wav_bytes(np.random.default_rng(99).normal(0, 0.1, 9_600_000).astype("float32"))
    job = client.post(
        f"/api/projects/{pid}/sources", files={"file": ("decode.wav", payload)}
    ).json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        active = list(client.app.state.jobs.processes)
        if active:
            break
        time.sleep(0.01)
    assert active
    client.post(f"/api/jobs/{job['id']}/cancel")
    assert wait_job(client, job)["status"] == "cancelled"
    assert list(client.app.state.jobs.processes) == []


def test_second_server_cannot_recover_or_write_active_workspace(tmp_path):
    import pytest

    from cleantake.projects import ProjectConflictError

    first = create_app(tmp_path, token="first")
    with TestClient(first, base_url="http://localhost"):
        with pytest.raises(ProjectConflictError, match="already open"):
            create_app(tmp_path, token="second")
    with TestClient(create_app(tmp_path, token="third"), base_url="http://localhost") as client:
        assert client.get("/api/health").status_code == 200


def test_interrupted_project_swap_restores_previous_revision(tmp_path):
    from cleantake.projects import ProjectStore

    store = ProjectStore(tmp_path / "projects")
    project = store.create("Survives interrupted publication")
    jid = str(uuid4())
    stage = tmp_path / "pending" / jid
    stage.mkdir(parents=True)
    (stage / "commit.json").write_text(json.dumps({"project_id": project.id}))
    (store.root / project.id).rename(stage / "backup")
    with TestClient(create_app(tmp_path, token="recover"), base_url="http://localhost") as client:
        response = client.get(
            f"/api/projects/{project.id}", headers={"X-CleanTake-Token": "recover"}
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Survives interrupted publication"
        assert response.json()["revision"] == 0


def test_queue_ceiling_rejects_extra_work_and_cancellation_cleans_upload(client):
    client.app.state.limits.queued_jobs = 2
    projects = [
        client.post("/api/projects", json={"name": f"Queued {index}"}).json() for index in range(3)
    ]
    payload = wav_bytes(np.random.default_rng(184).normal(0, 0.1, 4_800_000).astype("float32"))
    active = [
        client.post(
            f"/api/projects/{project['id']}/sources", files={"file": ("queued.wav", payload)}
        )
        for project in projects[:2]
    ]
    assert all(response.status_code == 202 for response in active)
    rejected = client.post(
        f"/api/projects/{projects[2]['id']}/sources", files={"file": ("queued.wav", payload)}
    )
    assert rejected.status_code == 409
    assert len(client.app.state.jobs.processes) <= 2
    for response in active:
        client.post(f"/api/jobs/{response.json()['id']}/cancel")
    for response in active:
        assert wait_job(client, response.json())["status"] in {"cancelled", "completed"}
    assert list((client.app.state.workspace / "uploads").iterdir()) == []


def test_cancellation_terminates_an_actual_ffmpeg_descendant(client, tmp_path, monkeypatch):
    import os
    import shlex
    import shutil
    import subprocess

    import pytest

    if os.name != "posix":
        pytest.skip("Process-tree inspection uses POSIX ps; Windows uses taskkill /T")
    project = project_with_source(client)
    pid = project["id"]
    decoder = shutil.which("ffmpeg")
    assert decoder
    tools = tmp_path / "paced media"
    tools.mkdir()
    wrapper = tools / "ffmpeg"
    # Pace the real decoder, so a fast WAV import cannot finish between ps
    # snapshots. The shell is replaced by FFmpeg and cancellation still has to
    # terminate that actual child process and roll back the staged import.
    wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(decoder)} -re "$@"\n')
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ.get("PATH", ""))
    payload = wav_bytes(np.random.default_rng(35).normal(0, 0.1, 1_440_000).astype("float32"))
    job = client.post(
        f"/api/projects/{pid}/sources", files={"file": ("decode.wav", payload)}
    ).json()
    child_pid = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with client.app.state.jobs.lock:
            workers = {process.pid for process in client.app.state.jobs.processes.values()}
        listing = subprocess.run(
            ["ps", "-ax", "-o", "pid=,ppid=,comm="], capture_output=True, text=True, check=True
        ).stdout
        for line in listing.splitlines():
            fields = line.strip().split(maxsplit=2)
            if (
                len(fields) == 3
                and int(fields[1]) in workers
                and fields[2].rsplit("/", 1)[-1] == "ffmpeg"
            ):
                child_pid = int(fields[0])
                break
        if child_pid is not None:
            break
        time.sleep(0.005)
    if child_pid is None:
        current = client.get(f"/api/jobs/{job['id']}").json()
        raise AssertionError(
            f"No actual FFmpeg child observed: job={current['status']}, "
            f"error={current.get('error')}"
        )
    client.post(f"/api/jobs/{job['id']}/cancel")
    terminal = wait_job(client, job)
    assert terminal["status"] == "cancelled", terminal
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        raise AssertionError("Cancelled FFmpeg child is still running")
    assert client.get(f"/api/projects/{pid}").json()["revision"] == project["revision"]
    assert list((client.app.state.workspace / "pending").iterdir()) == []


def test_cleanup_error_does_not_leave_project_busy_forever(client):
    import os

    import pytest

    if os.name != "posix" or os.geteuid() == 0:
        pytest.skip("This regression needs normal POSIX directory permissions")
    project = project_with_source(client)
    pid = project["id"]
    payload = wav_bytes(np.random.default_rng(711).normal(0, 0.1, 4_800_000).astype("float32"))
    job = client.post(
        f"/api/projects/{pid}/sources", files={"file": ("permissions.wav", payload)}
    ).json()
    stage = client.app.state.workspace / "pending" / job["id"]
    (stage / "cannot-remove").write_bytes(b"partial")
    stage.chmod(0o500)
    try:
        client.post(f"/api/jobs/{job['id']}/cancel")
        terminal = wait_job(client, job, timeout=2)
        assert terminal["status"] == "failed"
        assert "temporary" in terminal["error"].lower()
        updated = client.patch(
            f"/api/projects/{pid}",
            json={"name": "Still editable", "expected_revision": project["revision"]},
        )
        assert updated.status_code == 200
    finally:
        if stage.exists():
            stage.chmod(0o700)


def test_failed_job_record_write_releases_project_reservation(client):
    import os

    import pytest

    if os.name != "posix" or os.geteuid() == 0:
        pytest.skip("This regression needs normal POSIX directory permissions")
    project = client.post("/api/projects", json={"name": "Job storage permissions"}).json()
    directory = client.app.state.workspace / "jobs"
    directory.chmod(0o500)
    try:
        with pytest.raises(PermissionError):
            client.post(
                f"/api/projects/{project['id']}/sources",
                files={"file": ("source.wav", wav_bytes())},
            )
    finally:
        directory.chmod(0o700)
    retry = client.post(
        f"/api/projects/{project['id']}/sources", files={"file": ("source.wav", wav_bytes())}
    )
    assert retry.status_code == 202, retry.text
    assert wait_job(client, retry.json())["status"] == "completed"
