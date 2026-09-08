from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from cleantake.projects import ProjectStore
from cleantake.server.jobs import WorkspaceLease

ENTRY = Path(__file__).resolve().parents[1] / "packaging/runtime_entry.py"


def launch(workspace):
    return subprocess.Popen(
        [sys.executable, str(ENTRY), "--desktop", "--workspace", str(workspace)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=dict(os.environ),
    )


def message(process):
    lines = queue.Queue()
    threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
    line = lines.get(timeout=40)
    assert line, "Backend exited before the desktop handshake"
    return json.loads(line)


def stop(process, *, eof=False):
    if process.poll() is None:
        if not eof:
            process.stdin.write("shutdown\n")
            process.stdin.flush()
        process.stdin.close()
    try:
        code = process.wait(timeout=15)
        assert code == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_desktop_first_run_is_ready_with_pending_sample_and_respects_deletion(tmp_path):
    workspace = tmp_path / "Workspace é"
    process = launch(workspace)
    try:
        ready = message(process)
        assert ready["event"] == "ready"
        url = urlsplit(ready["url"])
        assert url.scheme == "http" and url.hostname == "127.0.0.1"
        token = parse_qs(url.fragment)["token"][0]
        origin = f"{url.scheme}://{url.netloc}"
        request = urllib.request.Request(
            f"{origin}/api/projects", headers={"X-CleanTake-Token": token}
        )
        projects = json.load(urllib.request.urlopen(request, timeout=5))["projects"]
        assert len(projects) == 1
        store = ProjectStore(workspace / "projects")
        sample = store.get(projects[0]["id"])
        assert sample.repairs and all(r.status == "proposed" for r in sample.repairs)
    finally:
        stop(process)
    assert "#token=" not in process.stderr.read()
    lease = WorkspaceLease(workspace)
    lease.close()
    store.delete(sample.id)
    process = launch(workspace)
    try:
        assert message(process)["event"] == "ready"
        assert store.list() == []
    finally:
        stop(process, eof=True)


def test_desktop_reports_workspace_in_use_without_modifying_it(tmp_path):
    workspace = tmp_path / "busy"
    workspace.mkdir()
    lease = WorkspaceLease(workspace)
    process = launch(workspace)
    try:
        failure = message(process)
        assert failure["event"] == "error"
        assert failure["code"] == "workspace_in_use"
        assert "token" not in json.dumps(failure)
        assert process.wait(timeout=10) == 1
        assert ProjectStore(workspace / "projects").list() == []
    finally:
        lease.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def test_desktop_eof_cancels_spawned_analysis_and_releases_workspace(tmp_path):
    process = launch(tmp_path)
    try:
        ready = message(process)
        url = urlsplit(ready["url"])
        origin = f"{url.scheme}://{url.netloc}"
        token = parse_qs(url.fragment)["token"][0]

        def request(path, value=None):
            payload = None if value is None else json.dumps(value).encode()
            req = urllib.request.Request(
                origin + path,
                data=payload,
                headers={
                    "X-CleanTake-Token": token,
                    "Content-Type": "application/json",
                    "Origin": origin,
                },
            )
            return json.load(urllib.request.urlopen(req, timeout=5))

        sample = request("/api/projects")["projects"][0]
        job = request(
            f"/api/projects/{sample['id']}/analyze",
            {
                "expected_revision": sample["revision"],
            },
        )
        deadline = time.monotonic() + 5
        while request(f"/api/jobs/{job['id']}")["status"] == "queued":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        stop(process, eof=True)
        saved = json.loads((tmp_path / "jobs" / f"{job['id']}.json").read_text())
        assert saved["status"] == "cancelled"
        assert not list((tmp_path / "pending").iterdir())
        lease = WorkspaceLease(tmp_path)
        lease.close()
        assert ProjectStore(tmp_path / "projects").get(sample["id"]).revision == sample["revision"]
    finally:
        if process.poll() is None:
            stop(process)


def test_desktop_existing_project_is_preserved_and_marked_initialized(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    project = store.create("My existing recording")
    process = launch(tmp_path)
    try:
        assert message(process)["event"] == "ready"
        assert [p.id for p in store.list()] == [project.id]
    finally:
        stop(process)
    store.delete(project.id)
    process = launch(tmp_path)
    try:
        assert message(process)["event"] == "ready"
        assert store.list() == []
    finally:
        stop(process)


def test_desktop_rejects_initialization_temp_symlink_without_writing_target(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    other = tmp_path / "unrelated.txt"
    other.write_text("keep this content")
    (workspace / ".desktop-initialized.tmp").symlink_to(other)
    process = launch(workspace)
    try:
        event = message(process)
        assert event["event"] == "error"
        assert event["code"] == "workspace_unavailable"
        assert other.read_text() == "keep this content"
        assert process.wait(timeout=10) == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_desktop_spawned_analysis_finishes_while_control_input_remains_open(tmp_path):
    """The worker must not share a pipe on which the control thread is reading."""
    process = launch(tmp_path)
    try:
        ready = message(process)
        url = urlsplit(ready["url"])
        origin = f"{url.scheme}://{url.netloc}"
        token = parse_qs(url.fragment)["token"][0]

        def request(path, value=None):
            payload = None if value is None else json.dumps(value).encode()
            req = urllib.request.Request(
                origin + path, data=payload,
                headers={"X-CleanTake-Token": token, "Content-Type": "application/json"},
            )
            return json.load(urllib.request.urlopen(req, timeout=5))

        sample = request("/api/projects")["projects"][0]
        job = request(
            f"/api/projects/{sample['id']}/analyze",
            {"expected_revision": sample["revision"]},
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            job = request(f"/api/jobs/{job['id']}")
            if job["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                break
            time.sleep(0.05)
        assert job["status"] == "completed", job
        assert not process.stdin.closed
        assert request(f"/api/projects/{sample['id']}")["revision"] > sample["revision"]
    finally:
        stop(process)
