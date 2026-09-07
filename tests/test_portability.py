from __future__ import annotations

import json
import stat
import zipfile

import numpy as np
import pytest
import soundfile as sf

from cleantake.exports import ExportCancelled, ExportError
from cleantake.portability import export_archive, import_archive
from cleantake.projects import ProjectStore


@pytest.fixture
def saved(tmp_path):
    path = tmp_path / "original.wav"
    sf.write(path, np.linspace(-0.2, 0.2, 4800), 48_000, subtype="FLOAT")
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("旅行")
    store.import_source(project.id, path)
    alternate = tmp_path / "alternate.wav"
    sf.write(alternate, np.linspace(0.3, -0.3, 4800), 48_000, subtype="FLOAT")
    donor = store.import_source(project.id, alternate)
    store.update_source(project.id, donor.id, {"alignment": {"offset_seconds": 0}})
    store.add_repair(
        project.id,
        start_frame=1000,
        end_frame=2000,
        kind="manual",
        source_id=donor.id,
        confidence=1,
        reason="Reviewed alternate",
        status="accepted",
        gain_db=-2,
        fade_ms=5,
    )
    return store, project.id


def test_archive_round_trip_preserves_bytes_and_decisions_as_new_identity(saved, tmp_path):
    store, pid = saved
    original = store.get(pid)
    path = tmp_path / "project.cleantake.zip"
    result = export_archive(store, pid, path)
    assert result["revision"] == original.revision
    restored = import_archive(store, path)
    assert restored.id != pid
    assert restored.name == original.name
    assert restored.sources == original.sources
    assert restored.repairs == original.repairs
    assert restored.repairs[0].status == "accepted"
    assert store.validate_sources(restored.id) == []
    assert store.get(pid) == original
    for source in original.sources:
        assert (
            store.source_path(pid, source.id, "original").read_bytes()
            == store.source_path(restored.id, source.id, "original").read_bytes()
        )
    assert store.history(restored.id).can_undo is False


@pytest.mark.parametrize(
    "member", ["../outside", "/tmp/outside", "C:/outside", "cache\\outside", "cache/../outside"]
)
def test_archive_rejects_unsafe_members_before_writing(saved, tmp_path, member):
    store, pid = saved
    path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("project.json", store.get(pid).model_dump_json())
        archive.writestr(member, "bad")
    with pytest.raises(ExportError):
        import_archive(store, path)
    assert [project.id for project in store.list()] == [pid]


def test_archive_rejects_symlinks_duplicates_missing_media_and_size_limits(saved, tmp_path):
    store, pid = saved
    for attack in ("symlink", "duplicate", "missing", "size"):
        path = tmp_path / f"{attack}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("project.json", store.get(pid).model_dump_json())
            if attack == "symlink":
                link = zipfile.ZipInfo("link")
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(link, "/tmp/outside")
            elif attack == "duplicate":
                with pytest.warns(UserWarning):
                    archive.writestr("project.json", "{}")
            elif attack == "size":
                archive.writestr("huge", b"0" * 10_000)
        with pytest.raises(ExportError):
            import_archive(store, path, max_bytes=5000 if attack == "size" else 50_000_000)
    assert len(store.list()) == 1


def test_archive_cancellation_and_corrupt_media_leave_no_project(saved, tmp_path):
    store, pid = saved
    path = tmp_path / "portable.zip"
    with pytest.raises(ExportCancelled):
        export_archive(store, pid, path, cancelled=lambda: True)
    assert not path.exists()
    export_archive(store, pid, path)
    with pytest.raises(ExportCancelled):
        import_archive(store, path, cancelled=lambda: True)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(path) as original, zipfile.ZipFile(tampered, "w") as target:
        for member in original.infolist():
            data = original.read(member)
            if member.filename.startswith("cache/"):
                data = b"x" * len(data)
            target.writestr(member, data)
    with pytest.raises(ExportError, match="integrity"):
        import_archive(store, tampered)
    assert len(store.list()) == 1
    assert not list(store.root.glob(".import.*"))


def test_foreign_manifest_cannot_reference_other_archive_entries(saved, tmp_path):
    store, pid = saved
    path = tmp_path / "foreign.zip"
    manifest = json.loads(store.get(pid).model_dump_json())
    manifest["sources"][0]["original_path"] = "project.json"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("project.json", json.dumps(manifest))
    with pytest.raises(ExportError):
        import_archive(store, path)
