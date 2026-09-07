"""Same-origin local editing API and packaged studio hosting."""

from __future__ import annotations

import io
import json
import math
import re
import secrets
import shutil
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import quote
from uuid import uuid4

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from cleantake import __version__
from cleantake.engine import Alignment, render_range, sample_aligned
from cleantake.exports import project_audio
from cleantake.models import project_to_public, validate_id
from cleantake.projects import (
    ProjectConflictError,
    ProjectHistoryError,
    ProjectIntegrityError,
    ProjectNotFoundError,
    ProjectStore,
    ProjectValidationError,
)
from cleantake.transcripts import import_transcript

from .jobs import JobManager, safe_error
from .limits import Limits
from .security import SessionBoundary, Tickets, error_response


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class CreateProject(Payload):
    name: str = Field(min_length=1, max_length=200)


class Revision(Payload):
    expected_revision: int = Field(ge=0)


class ProjectPatch(Revision):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    primary_source_id: str | None = None


class SourcePatch(Revision):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    speaker: str | None = Field(default=None, max_length=200)
    alignment: dict[str, Any] | None = None


class RepairCreate(Revision):
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    source_id: str
    kind: Literal["manual"] = "manual"
    gain_db: float = 0.0
    fade_ms: float = 12.0


class RepairPatch(Revision):
    status: Literal["proposed", "accepted", "rejected", "unresolved"] | None = None
    source_id: str | None = None
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, gt=0)
    gain_db: float | None = None
    fade_ms: float | None = None


class TranscriptCreate(Revision):
    text: str = Field(max_length=1_500_000)
    source_id: str
    filename: str = Field(min_length=1, max_length=255)
    time_unit: str | None = None


class ExportCreate(Revision):
    format: Literal["wav", "flac"] = "wav"
    finish: bool = False


def _integer(raw: str, label: str) -> int:
    if not re.fullmatch(r"0|[1-9][0-9]*", raw):
        raise ProjectValidationError(f"{label} must be a non-negative integer")
    return int(raw)


def _safe_filename(raw: str | None) -> str:
    name = (raw or "recording").replace("\\", "/").rsplit("/", 1)[-1]
    if name in {"", ".", ".."} or len(name) > 255 or any(ord(c) < 32 for c in name):
        raise ProjectValidationError("Choose a valid file name")
    return name


def _checked_owned(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if parts.is_absolute() or "\\" in relative or any(part in {"..", "."} for part in parts.parts):
        raise ProjectValidationError("Invalid artifact name")
    path = root
    for part in parts.parts:
        path = path / part
        if path.is_symlink():
            raise ProjectIntegrityError("Artifact is not an owned regular file")
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ProjectNotFoundError("Artifact was not found")
    return path


def create_app(workspace: Path, token: str | None = None) -> FastAPI:
    """Create a local studio. The launcher binds loopback and disables access logs."""
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    if workspace.is_symlink():
        raise ProjectValidationError("Workspace must not be a symbolic link")
    workspace = workspace.resolve()
    if (workspace / "projects").is_symlink():
        raise ProjectValidationError("Projects directory must not be a symbolic link")
    store = ProjectStore(workspace / "projects")
    limits = Limits()
    jobs = JobManager(workspace, store, limits)

    @asynccontextmanager
    async def lifespan(application):
        try:
            yield
        finally:
            jobs.close()

    app = FastAPI(
        title="CleanTake local API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.workspace = workspace
    app.state.store = store
    app.state.limits = limits
    app.state.jobs = jobs
    app.state.token = token or secrets.token_urlsafe(32)
    app.state.tickets = Tickets()
    app.add_middleware(SessionBoundary, state=app.state)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(request, error):
        return error_response(
            422, "invalid_request", "Check the request fields, types, and required values."
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        code = "not_found" if error.status_code == 404 else "invalid_request"
        message = (
            "This item or API route was not found."
            if error.status_code == 404
            else "The request could not be read."
        )
        return error_response(error.status_code, code, message)

    @app.exception_handler(ProjectConflictError)
    @app.exception_handler(ProjectHistoryError)
    async def conflict_error(request, error):
        return error_response(409, "project_conflict", safe_error(error))

    @app.exception_handler(ProjectNotFoundError)
    @app.exception_handler(FileNotFoundError)
    async def missing_error(request, error):
        return error_response(
            404, "not_found", "The selected project, source, job, or artifact was not found."
        )

    @app.exception_handler(ProjectValidationError)
    @app.exception_handler(ValueError)
    async def invalid_error(request, error):
        return error_response(422, "invalid_request", safe_error(error))

    @app.exception_handler(ProjectIntegrityError)
    async def integrity_error(request, error):
        return error_response(
            409,
            "source_integrity",
            "A saved source is missing or has changed. Restore the original project media.",
        )

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        return error_response(
            500,
            "processing_error",
            "The operation could not finish. Check available disk space and try again.",
        )

    def public(pid: str):
        with jobs.lock:
            result = project_to_public(store.get(pid)).model_dump(mode="json")
            # Failed historical manifests may contain unsanitized exception details.
            if result["error"]:
                result["error"] = "Project processing failed. Check source integrity and try again."
            history = store.history(pid)
            result.update(can_undo=history.can_undo, can_redo=history.can_redo)
            return result

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/settings")
    def settings():
        return {"limits": asdict(limits)}

    @app.get("/api/projects")
    def list_projects():
        with jobs.lock:
            return {"projects": [project.model_dump(mode="json") for project in store.list()]}

    @app.post("/api/projects", status_code=201)
    def create_project(payload: CreateProject):
        with jobs.lock:
            return public(store.create(payload.name).id)

    async def receive_upload(request: Request, *, archive: bool = False):
        # Parsing is fed by the ASGI byte counter and spools large uploads to disk.
        directory = None
        try:
            async with request.form(max_files=1, max_fields=4, max_part_size=16_384) as form:
                allowed = {"file"} if archive else {"file", "name", "channel", "stream"}
                if set(form.keys()) - allowed or any(len(form.getlist(key)) != 1 for key in form):
                    raise ProjectValidationError("Upload contains unexpected or duplicate fields")
                uploaded = form.get("file")
                if not isinstance(uploaded, UploadFile):
                    # Consume non-multipart bodies so the streamed size cap still applies.
                    if not request.headers.get("content-type", "").startswith("multipart/"):
                        async for _ in request.stream():
                            pass
                    raise ProjectValidationError("Choose one file to upload")
                name = _safe_filename(uploaded.filename)
                params = {}
                for key in ("channel", "stream"):
                    if key in form:
                        if not isinstance(form[key], str):
                            raise ProjectValidationError("Audio selection must be an integer")
                        params[key] = _integer(form[key], key)
                if "name" in form:
                    if (
                        not isinstance(form["name"], str)
                        or not 1 <= len(form["name"].strip()) <= 200
                    ):
                        raise ProjectValidationError("Source name must contain 1 to 200 characters")
                    params["name"] = form["name"].strip()
                directory = workspace / "uploads" / str(uuid4())
                directory.mkdir(mode=0o700)
                target = directory / name
                size = 0
                with target.open("xb") as output:
                    while chunk := await uploaded.read(1024 * 1024):
                        size += len(chunk)
                        if size > limits.max_upload_bytes:
                            from .security import UploadTooLarge

                            raise UploadTooLarge
                        output.write(chunk)
                if size == 0:
                    raise ProjectValidationError("The selected file is empty")
                return {"path": str(target), **params}
        except BaseException:
            if directory is not None:
                shutil.rmtree(directory, ignore_errors=True)
            raise

    @app.post("/api/projects/import", status_code=202)
    async def archive_import(request: Request):
        params = await receive_upload(request, archive=True)
        try:
            return jobs.submit(None, "archive_import", params)
        except BaseException:
            shutil.rmtree(Path(params["path"]).parent, ignore_errors=True)
            raise

    @app.get("/api/projects/{pid}")
    def get_project(pid: str):
        return public(pid)

    @app.patch("/api/projects/{pid}")
    def patch_project(pid: str, payload: ProjectPatch):
        with jobs.mutation(pid, payload.expected_revision):
            store.update_project(pid, **payload.model_dump())
            return public(pid)

    @app.delete("/api/projects/{pid}", status_code=204)
    def delete_project(pid: str, payload: Revision):
        with jobs.mutation(pid, payload.expected_revision):
            store.delete(pid, expected_revision=payload.expected_revision)
            shutil.rmtree(workspace / "exports" / pid, ignore_errors=True)
        return Response(status_code=204)

    @app.post("/api/projects/{pid}/sources", status_code=202)
    async def import_source(pid: str, request: Request):
        with jobs.lock:
            project = jobs.check_available(pid)
            if len(project.sources) >= limits.max_sources:
                raise ProjectValidationError("A project can contain at most four sources")
        params = await receive_upload(request)
        try:
            return jobs.submit(pid, "import", {**params, "expected_revision": project.revision})
        except BaseException:
            shutil.rmtree(Path(params["path"]).parent, ignore_errors=True)
            raise

    @app.patch("/api/projects/{pid}/sources/{sid}")
    def patch_source(pid: str, sid: str, payload: SourcePatch):
        with jobs.mutation(pid, payload.expected_revision):
            changes = payload.model_dump(exclude={"expected_revision"}, exclude_unset=True)
            if not changes:
                raise ProjectValidationError("Choose a source field to change")
            store.update_source(pid, sid, changes, expected_revision=payload.expected_revision)
            return public(pid)

    @app.post("/api/projects/{pid}/analyze", status_code=202)
    def analyze(pid: str, payload: Revision):
        with jobs.lock:
            project = jobs.check_available(pid, payload.expected_revision)
            if len(project.sources) < 2:
                raise ProjectValidationError(
                    "Import at least two simultaneous recordings to analyze"
                )
            return jobs.submit(pid, "analyze", payload.model_dump())

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str):
        return jobs.get(jid)

    @app.post("/api/jobs/{jid}/cancel")
    def cancel_job(jid: str):
        return jobs.cancel(jid)

    @app.post("/api/projects/{pid}/repairs")
    def create_repair(pid: str, payload: RepairCreate):
        with jobs.mutation(pid, payload.expected_revision):
            store.add_repair(
                pid,
                **payload.model_dump(),
                confidence=1.0,
                reason="Manual repair selected by the editor",
            )
            return public(pid)

    @app.patch("/api/projects/{pid}/repairs/{rid}")
    def patch_repair(pid: str, rid: str, payload: RepairPatch):
        with jobs.mutation(pid, payload.expected_revision):
            changes = payload.model_dump(exclude={"expected_revision"}, exclude_unset=True)
            if not changes:
                raise ProjectValidationError("Choose a repair field to change")
            store.update_repair(pid, rid, changes, expected_revision=payload.expected_revision)
            return public(pid)

    @app.post("/api/projects/{pid}/undo")
    def undo(pid: str, payload: Revision):
        with jobs.mutation(pid, payload.expected_revision):
            store.undo(pid, expected_revision=payload.expected_revision)
            return public(pid)

    @app.post("/api/projects/{pid}/redo")
    def redo(pid: str, payload: Revision):
        with jobs.mutation(pid, payload.expected_revision):
            store.redo(pid, expected_revision=payload.expected_revision)
            return public(pid)

    @app.post("/api/projects/{pid}/transcript")
    def transcript(pid: str, payload: TranscriptCreate):
        with jobs.mutation(pid, payload.expected_revision):
            data = import_transcript(
                payload.text, payload.source_id, payload.filename, time_unit=payload.time_unit
            )
            store.add_transcript(pid, data, expected_revision=payload.expected_revision)
            return public(pid)

    def window(pid: str, request: Request, *, peaks: bool):
        allowed = (
            {"source_id", "mode", "start_frame", "end_frame", "bins"}
            if peaks
            else {"source_id", "mode", "start_frame", "end_frame"}
        )
        if set(request.query_params) - allowed or any(
            len(request.query_params.getlist(key)) != 1 for key in request.query_params
        ):
            raise ProjectValidationError("Unexpected or duplicate audio parameters")
        project = store.get(pid)
        if not project.sources:
            raise ProjectValidationError("Import a primary recording before listening")
        mode = request.query_params.get(
            "mode", "source" if peaks and "source_id" in request.query_params else "original"
        )
        if mode not in {"original", "repaired", "source"}:
            raise ProjectValidationError("Audio mode must be original, repaired, or source")
        sid = request.query_params.get("source_id")
        if mode == "source" and sid is None:
            raise ProjectValidationError("Choose a source for source listening")
        if sid is not None:
            validate_id(sid)
        if sid is not None and mode != "source":
            raise ProjectValidationError("Source selection requires source mode")
        sid = sid or project.primary_source_id
        source = next((source for source in project.sources if source.id == sid), None)
        if source is None:
            raise ProjectValidationError("Choose a source that belongs to this project")
        aligned = source.alignment.status != "uncertain" or source.id == project.primary_source_id
        if mode == "source" and not aligned and not peaks:
            raise ProjectValidationError(
                "This source needs manual alignment before synchronized listening"
            )
        duration = source.audio.frames if not aligned and peaks else project.duration_frames
        start = _integer(request.query_params.get("start_frame", "0"), "start_frame")
        default_end = (
            duration
            if peaks
            else min(duration, start + project.sample_rate * limits.preview_seconds)
        )
        end = _integer(request.query_params.get("end_frame", str(default_end)), "end_frame")
        if not 0 <= start < end <= duration:
            raise ProjectValidationError(
                "Choose a non-empty frame range within the recording duration"
            )
        if not peaks and end - start > project.sample_rate * limits.preview_seconds:
            raise ProjectValidationError("Audio preview windows cannot exceed 120 seconds")
        bins = _integer(request.query_params.get("bins", "1200"), "bins") if peaks else 0
        if peaks and not 1 <= bins <= limits.waveform_bins:
            raise ProjectValidationError("Waveform bins must be between 1 and 4096")
        if mode == "repaired":
            reference, candidates, repairs = project_audio(store, project)

            def read(first, last):
                return render_range(
                    reference, candidates, repairs, first, last, project.sample_rate
                )

            coverage = [0, duration]
        else:
            samples = store.source_samples(pid, sid)
            clock = Alignment(**source.alignment.model_dump())
            if aligned:

                def read(first, last):
                    return sample_aligned(samples, first, last, project.sample_rate, clock)

                offset = clock.offset_seconds * project.sample_rate
                scale = 1 + clock.drift_ppm / 1_000_000
                first = max(0, math.ceil(-offset / scale))
                last = min(duration, math.floor((len(samples) - 1 - offset) / scale) + 1)
                coverage = [min(first, duration), max(min(first, duration), last)]
            else:

                def read(first, last):
                    return samples[first:last]

                coverage = [0, len(samples)]
        return project, sid, mode, aligned, start, end, bins, coverage, read

    @app.get("/api/projects/{pid}/peaks")
    def peaks(pid: str, request: Request):
        with jobs.lock:
            project, sid, mode, aligned, start, end, bins, coverage, read = window(
                pid, request, peaks=True
            )
            bins = min(bins, end - start)
            edges = np.linspace(start, end, bins + 1, dtype=np.int64)
            minima, maxima = [], []
            for first, last in zip(edges[:-1], edges[1:], strict=True):
                low, high = math.inf, -math.inf
                for chunk_start in range(int(first), int(last), 262_144):
                    values = read(chunk_start, min(chunk_start + 262_144, int(last)))
                    if not np.isfinite(values).all():
                        raise ProjectIntegrityError("Source contains non-finite samples")
                    low = min(low, float(np.min(values)))
                    high = max(high, float(np.max(values)))
                minima.append(low)
                maxima.append(high)
            return {
                "source_id": sid if mode != "repaired" else None,
                "start_frame": start,
                "end_frame": end,
                "sample_rate": project.sample_rate,
                "min": minima,
                "max": maxima,
                "coverage": coverage,
                "revision": project.revision,
                "aligned": aligned,
            }

    @app.get("/api/projects/{pid}/audio")
    def audio(pid: str, request: Request):
        with jobs.lock:
            project, _, _, _, start, end, _, _, read = window(pid, request, peaks=False)
            output = io.BytesIO()
            with sf.SoundFile(
                output,
                mode="w",
                samplerate=project.sample_rate,
                channels=1,
                format="WAV",
                subtype="FLOAT",
            ) as stream:
                for first in range(start, end, 262_144):
                    values = read(first, min(first + 262_144, end))
                    if not np.isfinite(values).all():
                        raise ProjectIntegrityError("Source contains non-finite samples")
                    stream.write(values)
            return Response(
                output.getvalue(),
                media_type="audio/wav",
                headers={
                    "X-CleanTake-Start-Frame": str(start),
                    "X-CleanTake-End-Frame": str(end),
                    "X-CleanTake-Revision": str(project.revision),
                },
            )

    @app.post("/api/projects/{pid}/exports", status_code=202)
    def export(pid: str, payload: ExportCreate):
        return jobs.submit(pid, "export", payload.model_dump())

    @app.post("/api/projects/{pid}/archive", status_code=202)
    def archive(pid: str, payload: Revision):
        return jobs.submit(pid, "export", {**payload.model_dump(), "archive": True})

    def artifact(pid: str, eid: str, name: str):
        validate_id(pid)
        validate_id(eid)
        store.get(pid)
        root = workspace / "exports" / pid / eid
        if any(path.is_symlink() for path in (workspace / "exports", root.parent, root)):
            raise ProjectIntegrityError("Export directory must not be a symbolic link")
        manifest = _checked_owned(root, ".artifacts.json")
        detail = json.loads(manifest.read_text())
        entry = next((item for item in detail["artifacts"] if item["name"] == name), None)
        if entry is None:
            raise ProjectNotFoundError("Artifact was not found")
        return _checked_owned(root, name), entry

    @app.post("/api/projects/{pid}/exports/{eid}/{name:path}/ticket")
    def download_ticket(pid: str, eid: str, name: str):
        artifact(pid, eid, name)
        return app.state.tickets.issue(f"/api/projects/{pid}/exports/{eid}/{quote(name, safe='/')}")

    @app.get("/api/projects/{pid}/exports/{eid}/{name:path}")
    def download(pid: str, eid: str, name: str, request: Request):
        path, entry = artifact(pid, eid, name)
        http_range = request.headers.get("range")
        if http_range is not None:
            match = re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", http_range)
            if match is None or not any(match.groups()):
                return error_response(400, "invalid_range", "Choose one valid byte range.")
            first, last = match.groups()
            size = path.stat().st_size
            if (
                (first and int(first) >= size)
                or (first and last and int(last) < int(first))
                or (not first and int(last) == 0)
            ):
                response = error_response(
                    416, "invalid_range", "The byte range is outside this artifact."
                )
                response.headers["Content-Range"] = f"bytes */{size}"
                return response
        return FileResponse(path, media_type=entry["media_type"], filename=path.name)

    static = Path(__file__).resolve().parent.parent / "static"

    @app.api_route(
        "/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    )
    def studio(path: str, request: Request):
        if path == "api" or path.startswith("api/") or request.method not in {"GET", "HEAD"}:
            raise HTTPException(404)
        if path:
            try:
                candidate = _checked_owned(static, path)
            except (ProjectValidationError, ProjectNotFoundError):
                candidate = None
            if candidate is not None:
                return FileResponse(candidate)
            if "." in Path(path).name:
                raise HTTPException(404)
        index = static / "index.html"
        if index.is_file() and not index.is_symlink():
            return FileResponse(index, media_type="text/html")
        return Response(
            "CleanTake studio assets are missing. Install the built package or build the studio.",
            status_code=503,
            media_type="text/plain",
        )

    return app
