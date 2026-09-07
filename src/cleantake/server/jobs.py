"""Durable bounded jobs, isolated processing, and recoverable project publication."""

from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import signal
import stat
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cleantake.media import inspect_media
from cleantake.models import validate_id
from cleantake.projects import ProjectConflictError, ProjectStore, ProjectValidationError

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def now() -> str:
    return datetime.now(UTC).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, allow_nan=False)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def safe_error(error: Exception) -> str:
    # Pydantic/OS/decoder diagnostics may quote user input and private locations.
    text = str(error)
    if any(part in text for part in ("\n", "/", "\\", "input_value", "validation error")):
        return "The operation could not use the supplied data. Check the selection and try again."
    if isinstance(error, (ValueError, RuntimeError)) and 0 < len(text) <= 250:
        return text
    return "The operation could not finish. Check the source files and available disk space."


class WorkspaceLease:
    """Prevent a second server from recovering or writing a live workspace."""

    def __init__(self, workspace: Path):
        path = workspace / ".server.lock"
        if path.is_symlink():
            raise ProjectValidationError("Workspace lock must not be a symbolic link")
        self.file = path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self.file.seek(0)
                if not self.file.read(1):
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise ProjectConflictError(
                "This workspace is already open in another studio server"
            ) from None

    def close(self):
        if self.file.closed:
            return
        if os.name == "nt":
            import msvcrt

            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


def remove_owned_tree(path: Path):
    """Delete owned trees, including Windows read-only staging copies."""

    def retry_readonly(function, target, error):
        if os.name != "nt" or not isinstance(error, PermissionError):
            raise error
        os.chmod(target, os.stat(target).st_mode | stat.S_IWUSR)
        function(target)

    if path.exists():
        shutil.rmtree(path, onexc=retry_readonly)


def _clone_project(source: Path, destination: Path) -> None:
    def link_or_copy(src, dst):
        if Path(src).is_symlink():
            raise ProjectValidationError("Project contains a symbolic link")
        # Immutable PCM and originals are safe to share. Metadata stays independent.
        relative = Path(src).relative_to(source)
        if os.name != "nt" and relative.parts[0] in {"originals", "cache"}:
            try:
                os.link(src, dst)
                return dst
            except OSError:
                pass
        return shutil.copy2(src, dst)

    if any(path.is_symlink() for path in source.rglob("*")):
        raise ProjectValidationError("Project contains a symbolic link")
    shutil.copytree(source, destination, copy_function=link_or_copy)


def _windows_worker_job():
    """Contain this worker and its future children even if taskkill is unavailable."""
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("minimum_working_set", ctypes.c_size_t),
            ("maximum_working_set", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits),
            ("io_counters", ctypes.c_uint64 * 6),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise OSError("Could not contain background processing")
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        kernel.CloseHandle(handle)
        raise OSError("Could not contain background processing")
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        kernel.CloseHandle(handle)
        raise OSError("Could not contain background processing")

    # The unnamed, non-inheritable handle stays open until process exit. The OS
    # then closes it and kills remaining children, including after a forced kill.
    return lambda: kernel.TerminateJobObject(handle, 1)


def _guard_worker_lifetime():
    """Stop owned processing when the multiprocessing parent's actual sentinel closes."""
    from multiprocessing.connection import wait

    parent = multiprocessing.parent_process()
    if parent is None:
        raise RuntimeError("Background processing requires its workspace server")
    if os.name == "posix":
        os.setsid()

        def terminate_tree():
            os.killpg(os.getpgrp(), signal.SIGKILL)
    else:
        terminate_tree = _windows_worker_job()

    def parent_exited():
        try:
            terminate_tree()
        finally:
            os._exit(1)

    # Check before cloning files or starting media tools, including when the
    # backend died during multiprocessing's module/bootstrap imports.
    if wait([parent.sentinel], timeout=0):
        parent_exited()

    def watch():
        wait([parent.sentinel])
        parent_exited()

    threading.Thread(target=watch, name="cleantake-parent-lifetime", daemon=True).start()


def _worker(
    workspace_text: str,
    jid: str,
    project_id: str | None,
    operation: str,
    params: dict,
    limits: dict,
):
    workspace = Path(workspace_text)
    pending = workspace / "pending" / jid
    try:
        _guard_worker_lifetime()
        store = ProjectStore(workspace / "projects")
        staged_store = None
        if operation in {"import", "analyze"}:
            staged_store = ProjectStore(pending / "projects")
            _clone_project(store.root / project_id, staged_store.root / project_id)
        if operation == "import":
            path = Path(params["path"])
            probe = inspect_media(path)
            stream = params.get("stream", 0)
            if stream >= len(probe.audio_streams):
                raise ProjectValidationError("Selected audio stream does not exist")
            if probe.audio_streams[stream].duration_seconds > limits["max_recording_seconds"]:
                raise ProjectValidationError("Recording exceeds the four-hour duration limit")
            staged_store.import_source(
                project_id,
                path,
                name=params.get("name"),
                channel=params.get("channel"),
                stream=stream,
                expected_revision=params.get("expected_revision"),
            )
            record = staged_store.get(project_id)
            if any(
                source.audio.frames > record.sample_rate * limits["max_recording_seconds"]
                for source in record.sources
            ):
                raise ProjectValidationError("Recording exceeds the four-hour duration limit")
            result = {"project_id": project_id, "revision": record.revision}
        elif operation == "analyze":
            record = staged_store.analyze(project_id, expected_revision=params["expected_revision"])
            result = {"project_id": project_id, "revision": record.revision}
        elif operation == "export" and params.get("archive"):
            from cleantake.portability import export_archive

            output = pending / "output"
            output.mkdir()
            archive = output / "project.cleantake.zip"
            detail = export_archive(
                store, project_id, archive, expected_revision=params["expected_revision"]
            )
            result = {
                "export_id": params["export_id"],
                "revision": store.get(project_id).revision,
                "artifacts": [
                    {
                        "name": archive.name,
                        "size": archive.stat().st_size,
                        "media_type": "application/zip",
                    }
                ],
                "warnings": detail.get("warnings", []),
            }
        elif operation == "export":
            from cleantake.exports import export_project

            result = export_project(
                store,
                project_id,
                pending / "output",
                format=params["format"],
                finish=params["finish"],
                expected_revision=params["expected_revision"],
            )
            result["export_id"] = params["export_id"]
        elif operation == "archive_import":
            from cleantake.portability import import_archive

            staged_store = ProjectStore(pending / "projects")
            record = import_archive(
                staged_store, Path(params["path"]), max_bytes=limits["max_archive_bytes"]
            )
            if any(
                source.audio.frames > record.sample_rate * limits["max_recording_seconds"]
                for source in record.sources
            ):
                raise ProjectValidationError("Recording exceeds the four-hour duration limit")
            result = {"project_id": record.id, "revision": record.revision}
        else:
            raise ProjectValidationError("Unknown job operation")
        atomic_json(pending / "result.json", {"ok": True, "result": result})
    except Exception as error:
        atomic_json(pending / "result.json", {"ok": False, "error": safe_error(error)})


class JobManager:
    def __init__(self, workspace: Path, store: ProjectStore, limits):
        self.workspace, self.store, self.limits = workspace, store, limits
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.reserved: dict[str, str] = {}
        self.cancelled: set[str] = set()
        self.processes: dict[str, multiprocessing.Process] = {}
        self._closed = False
        for name in ("jobs", "pending", "uploads", "exports"):
            directory = workspace / name
            if directory.is_symlink():
                raise ProjectValidationError("Workspace directories must not be symbolic links")
            directory.mkdir(parents=True, exist_ok=True)
        self.lease = WorkspaceLease(workspace)
        try:
            self._recover()
        except BaseException:
            self.lease.close()
            raise
        self.executor = ThreadPoolExecutor(
            max_workers=limits.workers, thread_name_prefix="cleantake-job"
        )

    def _recover(self):
        for stage in (self.workspace / "pending").iterdir():
            if stage.is_symlink():
                stage.unlink()
                continue
            journal = stage / "commit.json"
            if journal.is_file():
                try:
                    details = json.loads(journal.read_text())
                    pid = validate_id(details["project_id"])
                    target = self.store.root / pid
                    backup = stage / "backup"
                    if not target.exists() and backup.is_dir():
                        os.rename(backup, target)
                except (ValueError, KeyError, OSError):
                    raise ProjectValidationError(
                        "Interrupted project publication needs recovery"
                    ) from None
            remove_owned_tree(stage)
        for upload in (self.workspace / "uploads").iterdir():
            if upload.is_dir() and not upload.is_symlink():
                remove_owned_tree(upload)
            else:
                upload.unlink(missing_ok=True)
        for path in (self.workspace / "jobs").glob("*.json"):
            if path.is_symlink():
                continue
            try:
                record = json.loads(path.read_text())
                jid = validate_id(record["id"])
                if path.stem != jid:
                    continue
                if record["status"] not in TERMINAL:
                    record.update(
                        status="interrupted",
                        message="Processing was interrupted; try again.",
                        error="The previous server stopped before this job finished.",
                        updated_at=now(),
                        progress=None,
                    )
                    atomic_json(path, record)
                self.jobs[jid] = record
            except (ValueError, KeyError, OSError):
                continue

    def _save(self, record: dict):
        atomic_json(self.workspace / "jobs" / f"{record['id']}.json", record)

    @contextmanager
    def mutation(self, project_id: str, expected_revision: int | None = None):
        with self.lock:
            self.check_available(project_id, expected_revision)
            yield

    def check_available(self, project_id: str, expected_revision: int | None = None):
        if project_id in self.reserved:
            raise ProjectConflictError("Project is busy; wait for its current job to finish")
        project = self.store.get(project_id)
        if expected_revision is not None and project.revision != expected_revision:
            raise ProjectConflictError("Project revision changed; refresh before editing")
        return project

    def submit(self, project_id: str | None, operation: str, params: dict) -> dict:
        with self.lock:
            if self._closed:
                raise ProjectConflictError("The server is stopping")
            if (
                sum(job["status"] not in TERMINAL for job in self.jobs.values())
                >= self.limits.queued_jobs
            ):
                raise ProjectConflictError("The processing queue is full; wait for a job to finish")
            if project_id is not None:
                self.check_available(project_id, params.get("expected_revision"))
            jid = str(uuid4())
            if operation == "export":
                params = {**params, "export_id": str(uuid4())}
            record = {
                "id": jid,
                "project_id": project_id,
                "operation": operation,
                "status": "queued",
                "progress": None,
                "message": "Waiting to process",
                "created_at": now(),
                "updated_at": now(),
                "result": None,
                "error": None,
            }
            (self.workspace / "pending" / jid).mkdir()
            self.jobs[jid] = record
            if project_id is not None:
                self.reserved[project_id] = jid
            try:
                self._save(record)
                self.executor.submit(self._run, jid, params)
            except BaseException:
                self.jobs.pop(jid, None)
                if self.reserved.get(project_id) == jid:
                    del self.reserved[project_id]
                remove_owned_tree(self.workspace / "pending" / jid)
                raise
            return dict(record)

    def get(self, jid: str) -> dict:
        validate_id(jid)
        with self.lock:
            if jid not in self.jobs:
                raise FileNotFoundError("Job was not found")
            return dict(self.jobs[jid])

    def cancel(self, jid: str) -> dict:
        with self.lock:
            record = self.get(jid)
            if record["status"] not in TERMINAL:
                self.cancelled.add(jid)
                self.jobs[jid].update(message="Cancelling processing", updated_at=now())
                self._save(self.jobs[jid])
            return dict(self.jobs[jid])

    def _stop(self, process):
        if process.pid is None:
            return
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                # A cancellation can arrive before the child establishes its group.
                if process.is_alive():
                    process.kill()
        elif process.is_alive():
            from cleantake.runtime import subprocess_options

            taskkill = (
                Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            )
            try:
                subprocess.run(
                    [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    timeout=5,
                    **subprocess_options(),
                )
            except (OSError, subprocess.TimeoutExpired):
                # Worker-owned Windows Job Objects also contain its children
                # when the OS helper cannot run and the direct kill is needed.
                pass
            if process.is_alive():
                process.kill()
        process.join(timeout=5)

    def _publish(self, jid: str, params: dict, result: dict):
        record = self.jobs[jid]
        stage = self.workspace / "pending" / jid
        if record["operation"] in {"import", "analyze", "archive_import"}:
            pid = validate_id(result["project_id"])
            target = self.store.root / pid
            source = stage / "projects" / pid
            if record["operation"] == "archive_import" and target.exists():
                raise ProjectConflictError("Imported project identifier already exists")
            atomic_json(stage / "commit.json", {"project_id": pid})
            if target.exists():
                os.rename(target, stage / "backup")
            try:
                os.rename(source, target)
            except BaseException:
                if (stage / "backup").exists():
                    os.rename(stage / "backup", target)
                raise
            record["project_id"] = pid
        elif record["operation"] == "export":
            target = self.workspace / "exports" / record["project_id"] / params["export_id"]
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(stage / "output" / ".artifacts.json", result)
            os.rename(stage / "output", target)

    def _run(self, jid: str, params: dict):
        stage = self.workspace / "pending" / jid
        process = None
        terminal, failure, result = "failed", None, None
        try:
            with self.lock:
                record = self.jobs[jid]
                if jid in self.cancelled:
                    terminal = "cancelled"
                    return
                record.update(
                    status="running",
                    message={
                        "import": "Importing and decoding audio",
                        "analyze": "Analyzing recording clocks and damage",
                        "export": "Preparing export files",
                        "archive_import": "Validating and importing project archive",
                    }[record["operation"]],
                    updated_at=now(),
                )
                self._save(record)
                process = multiprocessing.get_context("spawn").Process(
                    target=_worker,
                    args=(
                        str(self.workspace),
                        jid,
                        record["project_id"],
                        record["operation"],
                        params,
                        asdict(self.limits),
                    ),
                    daemon=False,
                )
                process.start()
                self.processes[jid] = process
            while process.is_alive():
                with self.lock:
                    stopping = jid in self.cancelled
                if stopping:
                    self._stop(process)
                    break
                process.join(timeout=0.05)
            with self.lock:
                if jid in self.cancelled:
                    terminal = "cancelled"
                elif process.exitcode != 0 or not (stage / "result.json").is_file():
                    failure = "Processing stopped unexpectedly. Try the job again."
                else:
                    outcome = json.loads((stage / "result.json").read_text())
                    if outcome["ok"]:
                        result = outcome["result"]
                        self._publish(jid, params, result)
                        terminal = "completed"
                    else:
                        failure = outcome["error"]
        except Exception as error:
            failure = safe_error(error)
        finally:
            if process is not None:
                if process.is_alive():
                    self._stop(process)
                with self.lock:
                    self.processes.pop(jid, None)
                process.close()
            try:
                remove_owned_tree(stage)
                if "path" in params:
                    remove_owned_tree(Path(params["path"]).parent)
            except OSError:
                terminal = "failed"
                failure = (
                    "Temporary processing files could not be removed. "
                    "Check disk permissions and restart CleanTake."
                )
            with self.lock:
                record = self.jobs[jid]
                record.update(
                    status=terminal,
                    progress=1.0 if terminal == "completed" else None,
                    message={
                        "completed": "Complete",
                        "cancelled": "Cancelled; previous project retained",
                        "failed": "Processing failed",
                    }[terminal],
                    result=result if terminal == "completed" else None,
                    error=failure,
                    updated_at=now(),
                )
                try:
                    self._save(record)
                except OSError:
                    record.update(
                        status="failed",
                        message="Job status could not be saved",
                        error="Check disk space and permissions before processing again.",
                    )
                finally:
                    pid = record["project_id"]
                    if self.reserved.get(pid) == jid:
                        del self.reserved[pid]
                    self.cancelled.discard(jid)

    def close(self):
        with self.lock:
            self._closed = True
            for jid, job in self.jobs.items():
                if job["status"] not in TERMINAL:
                    self.cancelled.add(jid)
        try:
            self.executor.shutdown(wait=True, cancel_futures=False)
        finally:
            self.lease.close()
