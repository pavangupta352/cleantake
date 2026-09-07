"""Durable, versioned local project storage for CleanTake."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import numpy as np
from pydantic import BaseModel, ConfigDict, ValidationError

from .media import MediaError, copy_file_with_hash, decode_to_cache, sha256_file
from .models import (
    AlignmentRecord,
    AudioCacheRecord,
    ProjectRecord,
    ProjectSummary,
    PublicProjectRecord,
    RepairRecord,
    SourceRecord,
    project_summary,
    project_to_public,
    validate_id,
)

_LOCKS_GUARD = threading.Lock()
_PROJECT_LOCKS: dict[tuple[str, str], threading.RLock] = {}


class ProjectError(RuntimeError):
    """Base class for project storage failures."""


class ProjectValidationError(ProjectError, ValueError):
    """A caller value or saved manifest violates the project contract."""


class ProjectNotFoundError(ProjectError, FileNotFoundError):
    """A validated project or source identifier is not present."""


class ProjectConflictError(ProjectError):
    """A mutation's expected revision is stale."""


class ProjectIntegrityError(ProjectError):
    """Owned source data is missing, changed, or escapes its project."""


class DuplicateSourceError(ProjectValidationError):
    """The same original bytes already exist in this project."""


class ProjectHistoryError(ProjectError):
    """Undo or redo has no state available."""


class HistoryState(BaseModel):
    """Path-free durable edit-history availability for clients."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    can_undo: bool
    can_redo: bool
    undo_depth: int
    redo_depth: int


def _now() -> datetime:
    return datetime.now(UTC)


def _model(payload: Mapping[str, Any]) -> ProjectRecord:
    try:
        return ProjectRecord.model_validate(payload)
    except ValidationError as error:
        raise ProjectValidationError(str(error)) from error


def _remove_readonly(function: Callable, path: str, error: BaseException) -> None:
    """Retry Windows deletion of an owned read-only regular file only."""

    if not isinstance(error, PermissionError) or function not in {os.unlink, os.remove}:
        raise error
    owned = Path(path)
    mode = owned.lstat().st_mode
    if not stat.S_ISREG(mode) or mode & stat.S_IWUSR:
        raise error
    owned.chmod(mode | stat.S_IWUSR)
    function(path)


class ProjectStore:
    """Own projects beneath ``root`` and serialize one writer per project.

    ``get`` returns the internal record required by render/export code. HTTP and
    UI callers must use ``get_public`` or ``list``; those types contain no file
    locations. Full PCM is exposed as a read-only ``numpy.memmap`` by
    ``source_samples``.
    """

    def __init__(self, root: Path, *, history_limit: int = 50) -> None:
        if isinstance(history_limit, bool) or not isinstance(history_limit, int):
            raise ProjectValidationError("history_limit must be an integer")
        if not 1 <= history_limit <= 1_000:
            raise ProjectValidationError("history_limit must be between 1 and 1000")
        requested_root = Path(root)
        requested_root.mkdir(parents=True, exist_ok=True)
        if not requested_root.is_dir():
            raise ProjectValidationError("project workspace must be a directory")
        self.root = requested_root.resolve(strict=True)
        self.history_limit = history_limit

    def create(self, name: str) -> ProjectRecord:
        """Create an empty project with a generated, path-safe identifier."""

        project_id = str(uuid4())
        created_at = _now()
        project = _model(
            {
                "schema_version": 1,
                "id": project_id,
                "name": name,
                "created_at": created_at,
                "updated_at": created_at,
                "revision": 0,
                "sample_rate": 48_000,
                "primary_source_id": None,
                "duration_frames": 0,
                "sources": [],
                "repairs": [],
                "transcripts": [],
                "warnings": [],
                "status": "empty",
                "error": None,
            }
        )
        project_dir = self.root / project_id
        try:
            project_dir.mkdir(mode=0o700)
            (project_dir / "originals").mkdir()
            (project_dir / "cache").mkdir()
            (project_dir / ".history" / "undo").mkdir(parents=True)
            (project_dir / ".history" / "redo").mkdir(parents=True)
            self._write_manifest(project_dir, project)
        except Exception:
            shutil.rmtree(project_dir, ignore_errors=True)
            raise
        return project

    def list(self) -> list[ProjectSummary]:
        """List path-free summaries ordered by most recent update."""

        projects: list[ProjectRecord] = []
        for candidate in self.root.iterdir():
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            try:
                validate_id(candidate.name)
                projects.append(self.get(candidate.name))
            except (ProjectError, ValueError):
                continue
        projects.sort(key=lambda project: (project.updated_at, project.id), reverse=True)
        return [project_summary(project) for project in projects]

    def get(self, project_id: str) -> ProjectRecord:
        """Load and validate an internal project record."""

        project_dir = self._project_dir(project_id)
        manifest = project_dir / "project.json"
        if manifest.is_symlink():
            raise ProjectIntegrityError("project manifest must not be a symbolic link")
        try:
            raw_text = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw_text)
        except FileNotFoundError as error:
            raise ProjectNotFoundError(f"project {project_id} has no manifest") from error
        except (OSError, json.JSONDecodeError) as error:
            raise ProjectValidationError("project manifest is not valid JSON") from error
        if not isinstance(payload, dict):
            raise ProjectValidationError("project manifest must be a JSON object")
        version = payload.get("schema_version")
        if version != 1:
            raise ProjectValidationError(f"unsupported project schema version {version!r}")
        project = _model(payload)
        if project.id != project_id:
            raise ProjectIntegrityError("project manifest identifier does not match its directory")
        return project

    def get_public(self, project_id: str) -> PublicProjectRecord:
        """Load a path-free record safe to serialize to an API client."""

        return project_to_public(self.get(project_id))

    def import_source(
        self,
        project_id: str,
        path: Path,
        *,
        name: str | None = None,
        channel: int | None = None,
        stream: int = 0,
        expected_revision: int | None = None,
    ) -> SourceRecord:
        """Copy immutable original bytes and decode a selected 48 kHz mono cache."""

        with self._lock(project_id):
            current = self.get(project_id)
            self._check_revision(current, expected_revision)
            if len(current.sources) >= 4:
                raise ProjectValidationError("a project can contain at most four sources")
            try:
                input_hash = sha256_file(path)
            except MediaError as error:
                raise ProjectValidationError(str(error)) from error
            if any(source.sha256 == input_hash for source in current.sources):
                raise DuplicateSourceError("this source file is already imported")

            source_id = str(uuid4())
            project_dir = self._project_dir(project_id)
            # Validate BOTH destination parents before creating the first output.
            originals = self._import_directory(project_dir, "originals")
            cache = self._import_directory(project_dir, "cache")
            original_dir = originals / source_id
            original_path = original_dir / "media"
            cache_path = cache / f"{source_id}.f32le"
            original_dir.mkdir(parents=False)
            try:
                copied_hash = copy_file_with_hash(path, original_path)
                if copied_hash != input_hash:
                    raise ProjectIntegrityError("source changed while it was being imported")
                decoded = decode_to_cache(
                    original_path,
                    cache_path,
                    stream=stream,
                    channel=channel,
                )
                cache_hash = sha256_file(cache_path)
                original_path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                source = SourceRecord(
                    id=source_id,
                    name=path.name if name is None else name,
                    original_filename=path.name,
                    original_path=f"originals/{source_id}/media",
                    sha256=copied_hash,
                    imported_at=_now(),
                    audio=AudioCacheRecord(
                        path=f"cache/{source_id}.f32le",
                        cache_sha256=cache_hash,
                        **decoded.__dict__,
                    ),
                    alignment=AlignmentRecord(
                        status="reference" if not current.sources else "uncertain",
                        confidence=1.0 if not current.sources else 0.0,
                        anchors=1 if not current.sources else 0,
                    ),
                )
                payload = current.model_dump(mode="python")
                payload["sources"] = [*current.sources, source]
                if not current.sources:
                    payload["primary_source_id"] = source.id
                    payload["duration_frames"] = source.audio.frames
                payload["status"] = "ready"
                payload["error"] = None
                updated = self._next_revision(current, payload)
                self._commit(current, updated)
            except MediaError as error:
                cache_path.unlink(missing_ok=True)
                shutil.rmtree(original_dir, onexc=_remove_readonly)
                raise ProjectValidationError(str(error)) from error
            except Exception:
                cache_path.unlink(missing_ok=True)
                shutil.rmtree(original_dir, onexc=_remove_readonly)
                raise
            return source

    def analyze(
        self,
        project_id: str,
        *,
        expected_revision: int | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> ProjectRecord:
        """Run the pure engine against read-only disk caches and save one revision.

        The optional callback lets a job coordinator cancel before publication.
        A cancellation leaves the current manifest byte-for-byte untouched.
        """

        is_cancelled = cancelled or (lambda: False)
        with self._lock(project_id):
            current = self.get(project_id)
            self._check_revision(current, expected_revision)
            if is_cancelled():
                return current
            if len(current.sources) < 2:
                raise ProjectValidationError("analysis requires at least two sources")
            try:
                self.validate_sources(project_id)
                from .engine import (
                    Alignment,
                    CandidateTrack,
                    estimate_alignment,
                    find_repairs,
                )

                primary = next(
                    source for source in current.sources if source.id == current.primary_source_id
                )
                reference = self.source_samples(project_id, primary.id)
                updated_sources: list[SourceRecord] = []
                candidates: list[CandidateTrack] = []
                for source in current.sources:
                    if source.id == primary.id:
                        alignment = Alignment(
                            confidence=1.0,
                            anchors=1,
                            status="reference",
                        )
                    else:
                        if is_cancelled():
                            return current
                        samples = self.source_samples(project_id, source.id)
                        alignment = (
                            Alignment(**source.alignment.model_dump())
                            if source.alignment.status == "manual"
                            else estimate_alignment(reference, samples, current.sample_rate)
                        )
                        candidates.append(
                            CandidateTrack(
                                source_id=source.id,
                                samples=samples,
                                alignment=alignment,
                            )
                        )
                    alignment_record = AlignmentRecord(
                        offset_seconds=alignment.offset_seconds,
                        drift_ppm=alignment.drift_ppm,
                        confidence=alignment.confidence,
                        anchors=alignment.anchors,
                        residual_ms=alignment.residual_ms,
                        status=alignment.status,
                        polarity=alignment.polarity,
                    )
                    updated_sources.append(
                        SourceRecord.model_validate(
                            {**source.model_dump(mode="python"), "alignment": alignment_record}
                        )
                    )
                if is_cancelled():
                    return current
                proposals = find_repairs(reference, candidates, current.sample_rate)
                generated_repairs = [
                    RepairRecord(
                        id=str(uuid4()),
                        start_frame=proposal.start_frame,
                        end_frame=proposal.end_frame,
                        kind=proposal.kind,
                        source_id=proposal.source_id,
                        confidence=proposal.confidence,
                        reason=proposal.reason,
                        alternatives=proposal.alternatives,
                        status=proposal.status,
                        gain_db=proposal.gain_db,
                        fade_ms=proposal.fade_ms,
                    )
                    for proposal in proposals
                ]
                retained_manual = [
                    repair.model_copy(
                        update={
                            "status": "unresolved" if repair.status == "accepted" else repair.status
                        }
                    )
                    for repair in current.repairs
                    if repair.kind == "manual"
                ]
                payload = current.model_dump(mode="python")
                payload.update(
                    {
                        "sources": updated_sources,
                        "repairs": [*retained_manual, *generated_repairs],
                        "status": "analyzed",
                        "error": None,
                    }
                )
                if current.repairs:
                    payload["warnings"] = [
                        *current.warnings,
                        "Analysis was rerun; automatic proposals were replaced and "
                        "accepted manual edits require review.",
                    ]
                updated = self._next_revision(current, payload)
                if is_cancelled():
                    return current
                self._commit(current, updated)
                return updated
            except Exception as error:
                if is_cancelled():
                    return current
                if isinstance(error, (ProjectConflictError, ProjectValidationError)):
                    raise
                payload = current.model_dump(mode="python")
                payload["status"] = "error"
                payload["error"] = str(error)[:4_000] or type(error).__name__
                failed = self._next_revision(current, payload)
                self._commit(current, failed)
                raise

    def update_repair(
        self,
        project_id: str,
        repair_id: str,
        changes: Mapping[str, Any],
        expected_revision: int | None = None,
    ) -> RepairRecord:
        """Validate and atomically replace selected editable repair fields."""

        try:
            validate_id(repair_id)
        except ValueError as error:
            raise ProjectValidationError(str(error)) from error
        allowed = {
            "start_frame",
            "end_frame",
            "kind",
            "source_id",
            "confidence",
            "reason",
            "alternatives",
            "status",
            "gain_db",
            "fade_ms",
        }
        self._check_change_keys(changes, allowed)
        with self._lock(project_id):
            current = self.get(project_id)
            self._check_revision(current, expected_revision)
            try:
                index = next(
                    index for index, repair in enumerate(current.repairs) if repair.id == repair_id
                )
            except StopIteration as error:
                raise ProjectNotFoundError(f"repair {repair_id} was not found") from error
            try:
                replacement = RepairRecord.model_validate(
                    {**current.repairs[index].model_dump(mode="python"), **dict(changes)}
                )
                repairs = list(current.repairs)
                repairs[index] = replacement
                payload = current.model_dump(mode="python")
                payload["repairs"] = repairs
                updated = self._next_revision(current, payload)
            except ValidationError as error:
                raise ProjectValidationError(str(error)) from error
            self._commit(current, updated)
            return replacement

    def add_repair(
        self,
        project_id: str,
        *,
        start_frame: int,
        end_frame: int,
        kind: str,
        source_id: str | None,
        confidence: float,
        reason: str,
        alternatives: Sequence[dict[str, Any]] | None = None,
        status: str = "proposed",
        gain_db: float = 0.0,
        fade_ms: float = 12.0,
        expected_revision: int | None = None,
    ) -> RepairRecord:
        """Append one validated review edit and return its generated record."""

        with self._lock(project_id):
            current = self.get(project_id)
            self._check_revision(current, expected_revision)
            try:
                repair = RepairRecord(
                    id=str(uuid4()),
                    start_frame=start_frame,
                    end_frame=end_frame,
                    kind=kind,
                    source_id=source_id,
                    confidence=confidence,
                    reason=reason,
                    alternatives=list(alternatives or []),
                    status=status,
                    gain_db=gain_db,
                    fade_ms=fade_ms,
                )
                payload = current.model_dump(mode="python")
                payload["repairs"] = [*current.repairs, repair]
                updated = self._next_revision(current, payload)
            except ValidationError as error:
                raise ProjectValidationError(str(error)) from error
            self._commit(current, updated)
            return repair

    def rename(
        self,
        project_id: str,
        name: str,
        *,
        expected_revision: int | None = None,
    ) -> ProjectRecord:
        """Rename a project without changing its media or review decisions."""

        with self._lock(project_id):
            current = self.get(project_id)
            self._check_revision(current, expected_revision)
            payload = current.model_dump(mode="python")
            payload["name"] = name
            updated = self._next_revision(current, payload)
            self._commit(current, updated)
            return updated

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        primary_source_id: str | None = None,
        expected_revision: int | None = None,
    ) -> ProjectRecord:
        """Apply the PATCH-project contract as one atomic revision."""

        if name is None and primary_source_id is None:
            raise ProjectValidationError("project update requires name or primary_source_id")
        with self._lock(project_id):
            current = self.get(project_id)
            self._check_revision(current, expected_revision)
            payload = current.model_dump(mode="python")
            if name is not None:
                payload["name"] = name
            if primary_source_id is not None and primary_source_id != current.primary_source_id:
                payload = self._primary_payload(current, primary_source_id, payload)
            updated = self._next_revision(current, payload)
            self._commit(current, updated)
            return updated

    def set_primary_source(
        self,
        project_id: str,
        source_id: str,
        *,
        expected_revision: int | None = None,
    ) -> ProjectRecord:
        """Rebase project time to ``source_id`` and explicitly reset analysis."""

        with self._lock(project_id):
            current = self.get(project_id)
            self._check_revision(current, expected_revision)
            if source_id == current.primary_source_id:
                raise ProjectValidationError("source is already the primary source")
            payload = self._primary_payload(current, source_id, current.model_dump(mode="python"))
            updated = self._next_revision(current, payload)
            self._commit(current, updated)
            return updated

    def update_source(
        self,
        project_id: str,
        source_id: str,
        changes: Mapping[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> SourceRecord:
        """Update source labels or set a manual alignment transform.

        Manual clock changes mark every non-rejected repair using that donor as
        unresolved, so a saved acceptance never survives a changed transform.
        """

        try:
            validate_id(source_id)
        except ValueError as error:
            raise ProjectValidationError(str(error)) from error
        self._check_change_keys(changes, {"name", "speaker", "alignment"})
        with self._lock(project_id):
            current = self.get(project_id)
            self._check_revision(current, expected_revision)
            try:
                index = next(
                    index for index, source in enumerate(current.sources) if source.id == source_id
                )
            except StopIteration as error:
                raise ProjectNotFoundError(f"source {source_id} was not found") from error
            if "alignment" in changes and source_id == current.primary_source_id:
                raise ProjectValidationError(
                    "primary source alignment is always the reference clock"
                )

            replacement_payload = current.sources[index].model_dump(mode="python")
            if "name" in changes:
                replacement_payload["name"] = changes["name"]
            if "speaker" in changes:
                replacement_payload["speaker"] = changes["speaker"]
            alignment_changed = "alignment" in changes
            if alignment_changed:
                raw_alignment = changes["alignment"]
                if not isinstance(raw_alignment, Mapping):
                    raise ProjectValidationError("alignment must be an object")
                allowed_alignment = {"offset_seconds", "drift_ppm", "polarity"}
                self._check_change_keys(raw_alignment, allowed_alignment)
                alignment_payload = {
                    **current.sources[index].alignment.model_dump(mode="python"),
                    **dict(raw_alignment),
                    "status": "manual",
                    "confidence": 1.0,
                    "anchors": 0,
                    "residual_ms": 0.0,
                }
                replacement_payload["alignment"] = alignment_payload
            try:
                replacement = SourceRecord.model_validate(replacement_payload)
                sources = list(current.sources)
                sources[index] = replacement
                payload = current.model_dump(mode="python")
                payload["sources"] = sources
                if alignment_changed:
                    payload["repairs"] = [
                        repair.model_copy(update={"status": "unresolved"})
                        if repair.source_id == source_id and repair.status != "rejected"
                        else repair
                        for repair in current.repairs
                    ]
                    payload["status"] = "ready"
                    payload["warnings"] = [
                        *current.warnings,
                        f"Alignment changed for {replacement.name}; affected repairs "
                        "require review.",
                    ]
                updated = self._next_revision(current, payload)
            except ValidationError as error:
                raise ProjectValidationError(str(error)) from error
            self._commit(current, updated)
            return replacement

    def add_transcript(
        self,
        project_id: str,
        transcript: Mapping[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> ProjectRecord:
        """Attach an already validated, JSON-safe transcript adapter result."""

        if not isinstance(transcript, Mapping):
            raise ProjectValidationError("transcript must be an object")
        with self._lock(project_id):
            current = self.get(project_id)
            self._check_revision(current, expected_revision)
            transcript_record = dict(transcript)
            source_id = transcript_record.get("source_id")
            if source_id is not None and source_id not in {source.id for source in current.sources}:
                raise ProjectValidationError("transcript source_id must name a known source")
            payload = current.model_dump(mode="python")
            payload["transcripts"] = [*current.transcripts, transcript_record]
            updated = self._next_revision(current, payload)
            self._commit(current, updated)
            return updated

    def undo(
        self,
        project_id: str,
        *,
        expected_revision: int | None = None,
    ) -> ProjectRecord:
        """Restore the newest durable undo snapshot with a new monotonic revision."""

        return self._restore(project_id, "undo", expected_revision)

    def redo(
        self,
        project_id: str,
        *,
        expected_revision: int | None = None,
    ) -> ProjectRecord:
        """Restore the newest durable redo snapshot with a new monotonic revision."""

        return self._restore(project_id, "redo", expected_revision)

    def history(self, project_id: str) -> HistoryState:
        """Return persistent undo/redo availability without exposing history files."""

        with self._lock(project_id):
            project_dir = self._project_dir(project_id)
            stacks = self._history_stacks(project_dir, self.get(project_id).revision)
            return HistoryState(
                can_undo=bool(stacks["undo"]),
                can_redo=bool(stacks["redo"]),
                undo_depth=len(stacks["undo"]),
                redo_depth=len(stacks["redo"]),
            )

    def validate_sources(self, project_id: str) -> list[str]:
        """Hash-check originals and caches; return an empty issue list on success."""

        with self._lock(project_id):
            project = self.get(project_id)
            for source in project.sources:
                original = self.source_path(project_id, source.id, "original")
                cache = self.source_path(project_id, source.id, "cache")
                if sha256_file(original) != source.sha256:
                    raise ProjectIntegrityError(f"source {source.id} has an original hash mismatch")
                if cache.stat().st_size != source.audio.frames * source.audio.bytes_per_frame:
                    raise ProjectIntegrityError(f"source {source.id} has an invalid cache size")
                if sha256_file(cache) != source.audio.cache_sha256:
                    raise ProjectIntegrityError(f"source {source.id} has a cache hash mismatch")
            return []

    def source_path(
        self,
        project_id: str,
        source_id: str,
        kind: Literal["original", "cache"],
    ) -> Path:
        """Resolve one saved source location under its owned project only."""

        try:
            validate_id(source_id)
        except ValueError as error:
            raise ProjectValidationError(str(error)) from error
        if kind not in {"original", "cache"}:
            raise ProjectValidationError("source kind must be 'original' or 'cache'")
        project = self.get(project_id)
        try:
            source = next(source for source in project.sources if source.id == source_id)
        except StopIteration as error:
            raise ProjectNotFoundError(f"source {source_id} was not found") from error
        relative = source.original_path if kind == "original" else source.audio.path
        return self._owned_existing_path(self._project_dir(project_id), relative)

    def source_samples(self, project_id: str, source_id: str) -> np.memmap:
        """Open a source's full mono cache as a read-only, disk-backed array."""

        project = self.get(project_id)
        try:
            source = next(source for source in project.sources if source.id == source_id)
        except StopIteration as error:
            raise ProjectNotFoundError(f"source {source_id} was not found") from error
        path = self.source_path(project_id, source_id, "cache")
        expected_size = source.audio.frames * source.audio.bytes_per_frame
        if path.stat().st_size != expected_size:
            raise ProjectIntegrityError(f"source {source_id} has an invalid cache size")
        return np.memmap(path, dtype="<f4", mode="r", shape=(source.audio.frames,))

    def delete(self, project_id: str, *, expected_revision: int | None = None) -> None:
        """Delete exactly one validated project directory."""

        with self._lock(project_id):
            project = self.get(project_id)
            self._check_revision(project, expected_revision)
            project_dir = self._project_dir(project_id)
            shutil.rmtree(project_dir, onexc=_remove_readonly)

    @staticmethod
    def _import_directory(project_dir: Path, name: str) -> Path:
        directory = project_dir / name
        try:
            mode = directory.lstat().st_mode
        except FileNotFoundError as error:
            raise ProjectValidationError(f"project {name} directory is missing") from error
        if stat.S_ISLNK(mode):
            raise ProjectValidationError(f"project {name} directory must not be a symbolic link")
        if not stat.S_ISDIR(mode):
            raise ProjectValidationError(f"project {name} location is not a directory")
        return directory

    def _project_dir(self, project_id: str) -> Path:
        try:
            validate_id(project_id)
        except ValueError as error:
            raise ProjectValidationError(str(error)) from error
        candidate = self.root / project_id
        try:
            candidate_stat = candidate.lstat()
        except FileNotFoundError as error:
            raise ProjectNotFoundError(f"project {project_id} was not found") from error
        if stat.S_ISLNK(candidate_stat.st_mode):
            raise ProjectIntegrityError("project directory must not be a symbolic link")
        if not stat.S_ISDIR(candidate_stat.st_mode):
            raise ProjectIntegrityError("project location is not a directory")
        try:
            candidate.resolve(strict=True).relative_to(self.root)
        except ValueError as error:
            raise ProjectIntegrityError("project directory escapes the workspace") from error
        return candidate

    def _lock(self, project_id: str) -> threading.RLock:
        try:
            validate_id(project_id)
        except ValueError as error:
            raise ProjectValidationError(str(error)) from error
        key = (str(self.root), project_id)
        with _LOCKS_GUARD:
            return _PROJECT_LOCKS.setdefault(key, threading.RLock())

    @staticmethod
    def _check_revision(project: ProjectRecord, expected_revision: int | None) -> None:
        if expected_revision is None:
            return
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ProjectValidationError("expected_revision must be a non-negative integer")
        if project.revision != expected_revision:
            raise ProjectConflictError(
                f"expected revision {expected_revision}, current revision is {project.revision}"
            )

    @staticmethod
    def _check_change_keys(changes: Mapping[str, Any], allowed: set[str]) -> None:
        if not isinstance(changes, Mapping) or not changes:
            raise ProjectValidationError("changes must be a non-empty object")
        unexpected = set(changes) - allowed
        if unexpected:
            raise ProjectValidationError(
                f"unsupported change fields: {', '.join(sorted(unexpected))}"
            )

    def _next_revision(self, current: ProjectRecord, payload: dict[str, Any]) -> ProjectRecord:
        payload["revision"] = current.revision + 1
        payload["updated_at"] = _now()
        return _model(payload)

    def _primary_payload(
        self,
        current: ProjectRecord,
        source_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            validate_id(source_id)
        except ValueError as error:
            raise ProjectValidationError(str(error)) from error
        try:
            primary = next(source for source in current.sources if source.id == source_id)
        except StopIteration as error:
            raise ProjectNotFoundError(f"source {source_id} was not found") from error
        sources = [
            SourceRecord.model_validate(
                {
                    **source.model_dump(mode="python"),
                    "alignment": AlignmentRecord(
                        status="reference" if source.id == source_id else "uncertain",
                        confidence=1.0 if source.id == source_id else 0.0,
                        anchors=1 if source.id == source_id else 0,
                    ),
                }
            )
            for source in current.sources
        ]
        payload.update(
            {
                "primary_source_id": source_id,
                "duration_frames": primary.audio.frames,
                "sources": sources,
                "repairs": [],
                "status": "ready",
                "error": None,
                "warnings": [
                    *current.warnings,
                    "Primary source changed; alignment, analysis, and repair decisions were reset.",
                ],
            }
        )
        return payload

    def _commit(self, current: ProjectRecord, updated: ProjectRecord) -> None:
        self._validate_accepted_audio(updated)
        self._publish_with_history(current, updated, "undo", restoring=False)

    def _validate_accepted_audio(self, project: ProjectRecord) -> None:
        """Run playback validation over every accepted frame before any state write.

        Chunking bounds temporary PCM memory; explicit map closure also lets
        Windows remove imported files immediately after a project operation.
        """

        accepted = [repair for repair in project.repairs if repair.status == "accepted"]
        if not accepted:
            return
        from .engine import Alignment, CandidateTrack, render_range

        project_dir = self._project_dir(project.id)
        needed = {project.primary_source_id, *(repair.source_id for repair in accepted)}
        with ExitStack() as opened:
            samples = {}
            candidates = []
            for source in project.sources:
                if source.id not in needed:
                    continue
                path = self._owned_existing_path(project_dir, source.audio.path)
                if path.stat().st_size != source.audio.frames * source.audio.bytes_per_frame:
                    raise ProjectIntegrityError(f"source {source.id} has an invalid cache size")
                pcm = np.memmap(path, dtype="<f4", mode="r", shape=(source.audio.frames,))
                opened.callback(pcm._mmap.close)
                samples[source.id] = pcm
                if source.id != project.primary_source_id:
                    candidates.append(
                        CandidateTrack(
                            source.id,
                            pcm,
                            Alignment(**source.alignment.model_dump()),
                        )
                    )
            try:
                for repair in accepted:
                    for start in range(repair.start_frame, repair.end_frame, 262_144):
                        render_range(
                            samples[project.primary_source_id],
                            candidates,
                            accepted,
                            start,
                            min(start + 262_144, repair.end_frame),
                            project.sample_rate,
                        )
            except ValueError as error:
                raise ProjectValidationError(str(error)) from error

    def _restore(
        self,
        project_id: str,
        direction: Literal["undo", "redo"],
        expected_revision: int | None,
    ) -> ProjectRecord:
        with self._lock(project_id):
            current = self.get(project_id)
            self._check_revision(current, expected_revision)
            project_dir = self._project_dir(project_id)
            snapshots = self._history_files(project_dir, direction)
            if not snapshots:
                raise ProjectHistoryError(f"nothing to {direction}")
            snapshot_path = snapshots[-1]
            try:
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ProjectIntegrityError(f"{direction} history is corrupt") from error
            restored_old = _model(payload)
            if restored_old.id != project_id:
                raise ProjectIntegrityError(f"{direction} history belongs to another project")
            opposite = "redo" if direction == "undo" else "undo"
            restored_payload = restored_old.model_dump(mode="python")
            restored = self._next_revision(current, restored_payload)
            self._validate_accepted_audio(restored)
            self._publish_with_history(current, restored, opposite, restoring=True)
            return restored

    def _write_manifest(self, project_dir: Path, project: ProjectRecord) -> None:
        self._write_json_atomic(project_dir / "project.json", project.model_dump(mode="json"))

    def _publish_with_history(
        self,
        current: ProjectRecord,
        updated: ProjectRecord,
        direction: Literal["undo", "redo"],
        *,
        restoring: bool,
    ) -> None:
        """Prepare both history stacks, then publish them with the manifest revision.

        A revision-specific index makes uncommitted snapshots invisible. Old
        history is only garbage-collected after the single manifest replacement;
        interrupted cleanup cannot resurrect a discarded redo branch.
        """
        project_dir = self._project_dir(current.id)
        stacks = self._history_stacks(project_dir, current.revision)
        current_index = self._history_index_path(project_dir, current.revision)
        if not current_index.exists():
            self._write_json_atomic(current_index, self._history_index(current.revision, stacks))
        directory = self._history_directory(project_dir, direction)
        snapshot = directory / f"{current.revision:020d}-{uuid4()}.json"
        next_index = self._history_index_path(project_dir, updated.revision)
        try:
            self._write_json_atomic(snapshot, current.model_dump(mode="json"))
            stacks[direction].append(snapshot)
            opposite = "redo" if direction == "undo" else "undo"
            stacks[opposite] = stacks[opposite][:-1] if restoring else []
            stacks = {key: paths[-self.history_limit :] for key, paths in stacks.items()}
            self._write_json_atomic(next_index, self._history_index(updated.revision, stacks))
            self._write_manifest(project_dir, updated)
        except Exception:
            # A directory fsync can fail after atomic replacement. If the new
            # manifest is already visible, callers must not treat the edit as
            # unpublished and remove source files that it now owns.
            if self.get(current.id) != updated:
                for path in (snapshot, next_index):
                    with suppress(OSError):
                        path.unlink(missing_ok=True)
                raise
            # Keep both indexes when post-publication durability is uncertain;
            # the next successful edit can safely collect the unused one.
            return
        self._collect_history(project_dir, next_index, stacks)

    @staticmethod
    def _history_index(revision: int, stacks: dict[str, list[Path]]) -> dict[str, Any]:
        return {
            "revision": revision,
            **{key: [path.name for path in paths] for key, paths in stacks.items()},
        }

    @staticmethod
    def _history_index_path(project_dir: Path, revision: int) -> Path:
        return project_dir / ".history" / f"index-{revision:020d}.json"

    def _history_stacks(self, project_dir: Path, revision: int) -> dict[str, list[Path]]:
        directories = {
            direction: self._history_directory(project_dir, direction)
            for direction in ("undo", "redo")
        }
        index = self._history_index_path(project_dir, revision)
        if index.is_symlink():
            raise ProjectIntegrityError("project history index must not be a symbolic link")
        try:
            payload = json.loads(index.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if any(index.parent.glob("index-*.json")):
                raise ProjectIntegrityError(
                    "project history index is missing for this revision"
                ) from None
            # Projects created before indexed history are migrated on their
            # first successful preparation, without changing either stack.
            return {
                key: sorted(path for path in directory.glob("*.json") if not path.is_symlink())
                for key, directory in directories.items()
            }
        except (OSError, json.JSONDecodeError) as error:
            raise ProjectIntegrityError("project history index is corrupt") from error
        if (
            not isinstance(payload, dict)
            or set(payload) != {"revision", "undo", "redo"}
            or type(payload["revision"]) is not int
            or payload["revision"] != revision
        ):
            raise ProjectIntegrityError("project history index is invalid")
        stacks = {}
        for key, directory in directories.items():
            names = payload[key]
            if (
                not isinstance(names, list)
                or len(names) > 1_000
                or any(
                    not isinstance(name, str)
                    or re.fullmatch(
                        r"[0-9]{20}-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\.json", name
                    )
                    is None
                    for name in names
                )
                or len(set(names)) != len(names)
            ):
                raise ProjectIntegrityError("project history index contains invalid snapshots")
            paths = [directory / name for name in names]
            if any(path.is_symlink() or not path.is_file() for path in paths):
                raise ProjectIntegrityError("project history snapshot is missing or invalid")
            stacks[key] = paths
        return stacks

    def _history_files(self, project_dir: Path, direction: Literal["undo", "redo"]) -> list[Path]:
        revision = self.get(project_dir.name).revision
        return self._history_stacks(project_dir, revision)[direction]

    def _collect_history(
        self, project_dir: Path, active_index: Path, stacks: dict[str, list[Path]]
    ) -> None:
        keep = {active_index, *(path for paths in stacks.values() for path in paths)}
        # This is storage cleanup, never publication. A denied unlink leaves
        # an ignored file for the next successful edit to collect.
        with suppress(OSError, ProjectIntegrityError):
            candidates = list(active_index.parent.glob("index-*.json"))
            for direction in ("undo", "redo"):
                candidates.extend(self._history_directory(project_dir, direction).glob("*.json"))
            for path in candidates:
                if path not in keep:
                    with suppress(OSError):
                        path.unlink(missing_ok=True)

    @staticmethod
    def _history_directory(project_dir: Path, direction: Literal["undo", "redo"]) -> Path:
        history_root = project_dir / ".history"
        directory = history_root / direction
        for candidate in (history_root, directory):
            try:
                candidate_stat = candidate.lstat()
            except FileNotFoundError as error:
                raise ProjectIntegrityError("project history directory is missing") from error
            if stat.S_ISLNK(candidate_stat.st_mode):
                raise ProjectIntegrityError("project history directory must not be a symbolic link")
            if not stat.S_ISDIR(candidate_stat.st_mode):
                raise ProjectIntegrityError("project history location is not a directory")
            try:
                candidate.resolve(strict=True).relative_to(project_dir.resolve(strict=True))
            except ValueError as error:
                raise ProjectIntegrityError(
                    "project history directory escapes its project"
                ) from error
        return directory

    @staticmethod
    def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
        if path.is_symlink():
            raise ProjectIntegrityError("project metadata destination must not be a symbolic link")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
            # Windows cannot open directories through os.open. File data was
            # fsynced above and replacement remains atomic on that platform.
            if os.name != "nt":
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    @staticmethod
    def _owned_existing_path(project_dir: Path, relative: str) -> Path:
        candidate = project_dir / relative
        current = project_dir
        for part in Path(relative).parts:
            current = current / part
            try:
                current_stat = current.lstat()
            except FileNotFoundError as error:
                raise ProjectIntegrityError("owned source file is missing") from error
            if stat.S_ISLNK(current_stat.st_mode):
                raise ProjectIntegrityError("owned source path contains a symbolic link")
        try:
            candidate.resolve(strict=True).relative_to(project_dir.resolve(strict=True))
        except ValueError as error:
            raise ProjectIntegrityError("owned source path escapes its project") from error
        if not candidate.is_file():
            raise ProjectIntegrityError("owned source path is not a regular file")
        return candidate


__all__ = [
    "DuplicateSourceError",
    "HistoryState",
    "ProjectConflictError",
    "ProjectError",
    "ProjectHistoryError",
    "ProjectIntegrityError",
    "ProjectNotFoundError",
    "ProjectStore",
    "ProjectValidationError",
]
