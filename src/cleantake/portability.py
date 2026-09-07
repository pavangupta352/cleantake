"""Verified project archives, imported under fresh project identities."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import zipfile
import zlib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import ValidationError

from cleantake.exports import ExportError, _check_cancelled
from cleantake.media import sha256_file
from cleantake.models import ProjectRecord
from cleantake.projects import ProjectConflictError, ProjectError, ProjectStore

MAX_ARCHIVE_BYTES = 50 * 1024**3
MAX_ARCHIVE_MEMBERS = 64
MAX_MANIFEST_BYTES = 4 * 1024**2


def _member_paths(project):
    paths = {"project.json"}
    for source in project.sources:
        original = f"originals/{source.id}/media"
        cache = f"cache/{source.id}.f32le"
        if source.original_path != original or source.audio.path != cache:
            raise ExportError("Archive source locations do not match the project layout")
        paths.update((original, cache))
    return paths


def _copy_stream(source, target, cancelled, *, limit):
    copied = 0
    while data := source.read(1024 * 1024):
        _check_cancelled(cancelled)
        copied += len(data)
        if copied > limit:
            raise ExportError("Archive expanded size exceeds its limit")
        target.write(data)
    return copied


def _publish_file(temporary, destination):
    # An exclusive link cannot replace a file created by another export in the meantime.
    try:
        os.link(temporary, destination)
    except FileExistsError as error:
        raise ExportError("Archive destination already exists") from error
    temporary.unlink()


def export_archive(store, project_id, destination, *, expected_revision=None, cancelled=None):
    """Package saved decisions plus exact original media and working caches."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ExportError("Archive destination already exists")
    _check_cancelled(cancelled)
    project = store.get(project_id)
    if expected_revision is not None and project.revision != expected_revision:
        raise ProjectConflictError("Project revision changed; refresh before archiving")
    _member_paths(project)
    store.validate_sources(project_id)
    manifest = project.model_dump_json(indent=2).encode("utf-8")
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise ExportError("Project metadata is too large for a portable archive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".archive.", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    total = len(manifest)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True
        ) as archive:
            archive.writestr("project.json", manifest)
            for source in project.sources:
                for kind, member in [
                    ("original", source.original_path),
                    ("cache", source.audio.path),
                ]:
                    path = store.source_path(project_id, source.id, kind)
                    with (
                        path.open("rb") as input_file,
                        archive.open(member, "w", force_zip64=True) as output,
                    ):
                        total += _copy_stream(
                            input_file, output, cancelled, limit=MAX_ARCHIVE_BYTES - total
                        )
        _check_cancelled(cancelled)
        if store.get(project_id).revision != project.revision:
            raise ProjectConflictError("Project changed during archive export; export again")
        _publish_file(temporary, destination)
        return {
            "revision": project.revision,
            "artifacts": [
                {
                    "name": destination.name,
                    "size": destination.stat().st_size,
                    "media_type": "application/zip",
                }
            ],
            "sha256": sha256_file(destination),
            "warnings": [],
        }
    finally:
        temporary.unlink(missing_ok=True)


def _validate_members(archive, max_bytes):
    members = archive.infolist()
    if not members or len(members) > MAX_ARCHIVE_MEMBERS:
        raise ExportError("Archive has an invalid member count")
    names = set()
    expanded = 0
    for member in members:
        name = member.filename
        path = PurePosixPath(name)
        mode = member.external_attr >> 16
        if (
            not name
            or "\\" in name
            or ":" in name
            or "\x00" in name
            or path.is_absolute()
            or path.as_posix() != name
            or any(part in {".", ".."} for part in path.parts)
            or member.is_dir()
            or stat.S_ISLNK(mode)
            or (stat.S_IFMT(mode) not in {0, stat.S_IFREG})
            or name in names
        ):
            raise ExportError("Archive contains unsafe or duplicate members")
        if member.flag_bits & 1:
            raise ExportError("Encrypted archives are not supported")
        if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise ExportError("Archive compression is unsupported; use stored or deflate ZIP")
        names.add(name)
        expanded += member.file_size
        if expanded > max_bytes:
            raise ExportError("Archive expanded size exceeds its limit")
    if (
        "project.json" not in names
        or archive.getinfo("project.json").file_size > MAX_MANIFEST_BYTES
    ):
        raise ExportError("Archive has missing or oversized project metadata")
    return names


def import_archive(
    store: ProjectStore, path: Path, *, cancelled=None, max_bytes=MAX_ARCHIVE_BYTES
) -> ProjectRecord:
    """Validate all members and content hashes before publishing a fresh project."""
    _check_cancelled(cancelled)
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ExportError("Archive expanded size limit must be a positive integer")
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ExportError("Select a regular portable project archive")
    stage = None
    try:
        with zipfile.ZipFile(source) as archive:
            names = _validate_members(archive, max_bytes)
            project = ProjectRecord.model_validate_json(archive.read("project.json"))
            if names != _member_paths(project):
                raise ExportError("Archive contains missing media or unexpected members")
            stage = Path(tempfile.mkdtemp(prefix=".import.", dir=store.root))
            new_id = str(uuid4())
            project_dir = stage / new_id
            project_dir.mkdir(mode=0o700)
            (project_dir / "originals").mkdir()
            (project_dir / "cache").mkdir()
            (project_dir / ".history/undo").mkdir(parents=True)
            (project_dir / ".history/redo").mkdir(parents=True)
            total = 0
            for member in archive.infolist():
                if member.filename == "project.json":
                    continue
                target = project_dir / member.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as input_file, target.open("xb") as output:
                    total += _copy_stream(input_file, output, cancelled, limit=max_bytes - total)
                if target.stat().st_size != member.file_size:
                    raise ExportError("Archive member size does not match its declaration")
            payload = project.model_dump(mode="python")
            payload.update(
                id=new_id, revision=0, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
            )
            if payload["status"] == "analyzing":
                payload.update(status="ready", error=None)
            restored = ProjectRecord.model_validate(payload)
            (project_dir / "project.json").write_text(
                restored.model_dump_json(indent=2), encoding="utf-8"
            )
            verification_store = ProjectStore(stage)
            verification_store.validate_sources(new_id)
            for item in restored.sources:
                verification_store.source_path(new_id, item.id, "original").chmod(0o444)
            _check_cancelled(cancelled)
            os.rename(project_dir, store.root / new_id)
            return store.get(new_id)
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        ValidationError,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        ProjectError,
        zlib.error,
        NotImplementedError,
        EOFError,
    ) as error:
        raise ExportError("Archive integrity or project metadata validation failed") from error
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
