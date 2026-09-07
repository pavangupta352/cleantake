#!/usr/bin/env python3
"""Exercise the actual frozen backend without developer tools on its PATH."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import queue
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import psutil


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def isolated_environment():
    env = dict(os.environ)
    env["PATH"] = ""
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX"):
        env.pop(name, None)
    return env


class Session:
    def __init__(self, executable, workspace):
        self.process = subprocess.Popen(
            [str(executable), "--desktop", "--workspace", str(workspace)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=isolated_environment(),
            cwd=workspace.parent,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
        self.events = queue.Queue()
        self.errors = []
        self.token = ""
        self.peak_rss = 0
        self.observed = {}
        self.monitoring = True

        def read_events():
            while line := self.process.stdout.readline(8192):
                try:
                    self.events.put(json.loads(line))
                except ValueError:
                    self.events.put({"event": "invalid_output"})
            self.events.put({"event": "exit"})

        def read_errors():
            while line := self.process.stderr.readline(4096):
                self.errors.append(line)
                del self.errors[:-30]

        def monitor():
            parent = psutil.Process(self.process.pid)
            while self.monitoring:
                total = 0
                try:
                    children = parent.children(recursive=True)
                    for process in [parent, *children]:
                        try:
                            total += process.memory_info().rss
                            if process.pid != parent.pid:
                                self.observed[process.pid] = process
                        except psutil.Error:
                            pass
                    self.peak_rss = max(self.peak_rss, total)
                except psutil.Error:
                    break
                time.sleep(0.02)

        for function in (read_events, read_errors, monitor):
            threading.Thread(target=function, daemon=True).start()

    def ready(self):
        event = self.events.get(timeout=90)
        assert event.get("event") == "ready", {
            "event": event,
            "diagnostics": "".join(self.errors)[-2000:],
        }
        url = urlsplit(event["url"])
        assert url.scheme == "http" and url.hostname == "127.0.0.1" and url.port
        self.token = parse_qs(url.fragment)["token"][0]
        self.origin = f"http://127.0.0.1:{url.port}"
        self.version = event["version"]
        return self

    def request(self, path, value=None, method=None, payload=None, content_type=None, raw=False):
        headers = {"X-CleanTake-Token": self.token, "Origin": self.origin}
        if value is not None:
            payload = json.dumps(value).encode()
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(
            self.origin + path,
            data=payload,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read()
            return data if raw or not data else json.loads(data)

    def upload(self, path, source):
        boundary = "cleantake-smoke-" + uuid.uuid4().hex
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{source.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode()
        body += source.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        return self.request(
            path, payload=body, content_type=f"multipart/form-data; boundary={boundary}"
        )

    def wait_job(self, job, expected="completed"):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            current = self.request(f"/api/jobs/{job['id']}")
            if current["status"] in {"completed", "cancelled", "failed", "interrupted"}:
                assert current["status"] == expected, current
                return current
            time.sleep(0.05)
        raise AssertionError("Processing job timed out")

    def stop(self, eof=False):
        started = time.monotonic()
        if self.process.poll() is None:
            if not eof:
                self.process.stdin.write("shutdown\n")
                self.process.stdin.flush()
            self.process.stdin.close()
        assert self.process.wait(timeout=15) == 0
        deadline = time.monotonic() + 5
        survivors = []
        while time.monotonic() < deadline:
            survivors = []
            for process in self.observed.values():
                try:
                    if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                        survivors.append(process)
                except psutil.Error:
                    pass
            if not survivors:
                break
            time.sleep(0.05)
        self.monitoring = False
        assert not survivors, f"Owned children survived shutdown: {[p.pid for p in survivors]}"
        assert self.token not in "".join(self.errors), "Private token appeared in diagnostics"
        return {
            "shutdown_seconds": time.monotonic() - started,
            "peak_tree_rss_bytes": self.peak_rss,
            "observed_children": len(self.observed),
        }

    def cleanup(self):
        self.monitoring = False
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
        for process in self.observed.values():
            try:
                process.kill()
            except psutil.Error:
                pass


def run(runtime: Path, report: dict):
    runtime = runtime.resolve()
    suffix = ".exe" if sys.platform == "win32" else ""
    if runtime.is_file():
        runtime = runtime.parent
    assert (runtime / ("cleantake-runtime" + suffix)).is_file(), "Runtime executable missing"
    report["runtime_manifest_sha256"] = digest(runtime / "runtime-manifest.json")
    manifest = json.loads((runtime / "runtime-manifest.json").read_text())
    report["version"] = manifest["cleantake_version"]
    for name, info in manifest["files"].items():
        source = runtime / name
        assert source.resolve().is_relative_to(runtime), "Runtime dependency escapes its bundle"
        assert digest(source) == info["sha256"], f"Runtime file hash mismatch: {name}"
    report["checks"].append(
        {"name": "runtime_file_integrity", "files": len(manifest["files"]), "status": "passed"}
    )
    with tempfile.TemporaryDirectory(prefix="CleanTake frozen é ") as temporary:
        root = Path(temporary)
        relocated = root / "Read only resources é" / "backend"
        shutil.copytree(runtime, relocated, symlinks=True)
        for item in [*relocated.rglob("*"), relocated]:
            if not item.is_symlink():
                item.chmod(item.stat().st_mode & ~0o222)
        executable = relocated / ("cleantake-runtime" + suffix)
        workspace = root / "Editing workspace é"
        doctor_started = time.monotonic()
        result = subprocess.run(
            [str(executable), "doctor"],
            env=isolated_environment(),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr
        doctor = json.loads(result.stdout)
        assert doctor["ffmpeg"]["available"] and doctor["ffprobe"]["available"]
        assert doctor["studio"]["available"]
        report["checks"].append(
            {
                "name": "doctor_empty_PATH",
                "status": "passed",
                "cold_start_seconds": time.monotonic() - doctor_started,
            }
        )
        session = Session(executable, workspace)
        try:
            session.ready()
            assert session.version == report["version"]
            sample = session.request("/api/projects")["projects"]
            assert len(sample) == 1
            pid = sample[0]["id"]
            route = f"/api/projects/{pid}"
            project = session.request(route)
            assert project["repairs"] and all(r["status"] == "proposed" for r in project["repairs"])
            session.request("/", raw=True)
            try:
                urllib.request.urlopen(session.origin + "/api/projects", timeout=5)
                raise AssertionError("Unauthenticated project read was accepted")
            except urllib.error.HTTPError as error:
                assert error.code == 401
            report["checks"].append({"name": "first_run_sample_and_auth", "status": "passed"})
            analyzed = session.wait_job(
                session.request(route + "/analyze", {"expected_revision": project["revision"]})
            )
            project = session.request(route)
            repair = next(r for r in project["repairs"] if r["status"] == "proposed")
            project = session.request(
                route + f"/repairs/{repair['id']}",
                {
                    "status": "accepted",
                    "expected_revision": project["revision"],
                },
                method="PATCH",
            )
            project = session.request(route + "/undo", {"expected_revision": project["revision"]})
            assert (
                next(r for r in project["repairs"] if r["id"] == repair["id"])["status"]
                == "proposed"
            )
            project = session.request(route + "/redo", {"expected_revision": project["revision"]})
            preview = session.request(
                route + "/audio?start_frame=816000&end_frame=840000&mode=repaired", raw=True
            )
            assert preview[:4] == b"RIFF" and len(preview) > 48_000
            report["checks"].append(
                {
                    "name": "spawned_analysis_edit_preview",
                    "status": "passed",
                    "job_status": analyzed["status"],
                }
            )
            for format_name in ("wav", "flac"):
                job = session.wait_job(
                    session.request(
                        route + "/exports",
                        {
                            "format": format_name,
                            "finish": True,
                            "expected_revision": project["revision"],
                        },
                    )
                )
                result = job["result"]
                assert any(a["name"].endswith(".rpp") for a in result["artifacts"])
                export = route + "/exports/" + result["export_id"] + "/"
                mapping = json.loads(session.request(export + "source-map.json", raw=True))
                dialogue = session.request(export + "dialogue." + format_name, raw=True)
                assert hashlib.sha256(dialogue).hexdigest() == mapping["output"]["sha256"]
                assert mapping["output"]["frames"] == project["duration_frames"]
                assert any(s["contributors"] for s in mapping["spans"])
                report["checks"].append(
                    {
                        "name": "export_" + format_name,
                        "status": "passed",
                        "artifacts": len(result["artifacts"]),
                        "warnings": result["warnings"],
                    }
                )
            archive_job = session.wait_job(
                session.request(route + "/archive", {"expected_revision": project["revision"]})
            )
            archive = root / "reopen.cleantake.zip"
            archive.write_bytes(
                session.request(
                    route
                    + "/exports/"
                    + archive_job["result"]["export_id"]
                    + "/project.cleantake.zip",
                    raw=True,
                )
            )
            restored = session.wait_job(session.upload("/api/projects/import", archive))
            assert restored["result"]["project_id"] != pid
            report["checks"].append({"name": "archive_round_trip", "status": "passed"})
            # A second real container traverses the bundled demux/decode path.
            assets = relocated / "_internal/cleantake/assets/demo"
            source = next(assets.glob("*.wav"))
            packed = root / "recording.wv"
            subprocess.run(
                [
                    str(relocated / "_internal/media" / ("ffmpeg" + suffix)),
                    "-v",
                    "error",
                    "-i",
                    str(source),
                    "-c:a",
                    "wavpack",
                    str(packed),
                ],
                check=True,
                env=isolated_environment(),
                timeout=30,
            )
            extra = session.request("/api/projects", {"name": "WavPack import"})
            session.wait_job(session.upload(f"/api/projects/{extra['id']}/sources", packed))
            imported = session.request(f"/api/projects/{extra['id']}")
            assert imported["duration_frames"] > 0 and len(imported["sources"]) == 1
            report["checks"].append({"name": "wavpack_import", "status": "passed"})
            media_job = session.request(
                route + "/exports",
                {"format": "wav", "finish": True, "expected_revision": project["revision"]},
            )
            deadline = time.monotonic() + 15
            media_child = None
            while time.monotonic() < deadline and media_child is None:
                for child in psutil.Process(session.process.pid).children(recursive=True):
                    try:
                        if child.name().lower() in {"ffmpeg", "ffmpeg.exe"}:
                            media_child = child
                            session.observed[child.pid] = child
                            break
                    except psutil.Error:
                        pass
                time.sleep(0.005)
            assert media_child is not None, "No actual FFmpeg child observed for cancellation"
            cancel_started = time.monotonic()
            session.request(f"/api/jobs/{media_job['id']}/cancel", {})
            session.wait_job(media_job, expected="cancelled")
            try:
                assert not media_child.is_running() or media_child.status() == psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                pass
            assert session.request(route)["revision"] == project["revision"]
            assert not list((workspace / "pending").iterdir())
            report["checks"].append(
                {
                    "name": "active_FFmpeg_tree_cancellation",
                    "status": "passed",
                    "cancel_seconds": time.monotonic() - cancel_started,
                }
            )
            job = session.request(route + "/analyze", {"expected_revision": project["revision"]})
            deadline = time.monotonic() + 10
            observed_worker = False
            while time.monotonic() < deadline:
                for child in psutil.Process(session.process.pid).children(recursive=True):
                    try:
                        if "--multiprocessing-fork" in child.cmdline():
                            observed_worker = True
                            session.observed[child.pid] = child
                    except psutil.Error:
                        pass
                if observed_worker:
                    break
                time.sleep(0.01)
            assert observed_worker, "No actual spawned worker observed before shutdown"
            measured = session.stop(eof=True)
            job_record = json.loads((workspace / "jobs" / f"{job['id']}.json").read_text())
            assert job_record["status"] == "cancelled", job_record["status"]
            assert not list((workspace / "pending").iterdir())
            report["checks"].append(
                {"name": "EOF_active_worker_cleanup", "status": "passed", **measured}
            )
        finally:
            session.cleanup()
        session = Session(executable, workspace)
        try:
            session.ready()
            assert len(session.request("/api/projects")["projects"]) == 3
            for item in session.request("/api/projects")["projects"]:
                session.request(
                    f"/api/projects/{item['id']}",
                    {"expected_revision": item["revision"]},
                    method="DELETE",
                )
            session.stop()
        finally:
            session.cleanup()
        session = Session(executable, workspace)
        try:
            session.ready()
            assert not session.request("/api/projects")["projects"]
            session.stop()
            report["checks"].append({"name": "restart_preserves_deletion", "status": "passed"})
        finally:
            session.cleanup()
        media_tool = relocated / "_internal/media" / ("ffprobe" + suffix)
        media_tool.parent.chmod(media_tool.parent.stat().st_mode | stat.S_IWUSR)
        media_tool.rename(media_tool.with_suffix(".disabled"))
        session = Session(executable, workspace)
        try:
            event = session.events.get(timeout=30)
            assert event["event"] == "error" and event["code"] == "media_tools_unavailable"
            assert session.process.wait(timeout=10) == 1
            report["checks"].append({"name": "missing_bundled_tool_fails", "status": "passed"})
        finally:
            session.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "schema_version": 1,
        "started_at": datetime.now(UTC).isoformat(),
        "platform": sys.platform,
        "architecture": platform.machine(),
        "checks": [],
    }
    started = time.monotonic()
    try:
        run(args.runtime, report)
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"[:2000]
    report["elapsed_seconds"] = time.monotonic() - started
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
