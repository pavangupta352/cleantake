from __future__ import annotations

import json
import stat
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import butter, sosfilt

from cleantake.models import ProjectRecord
from cleantake.projects import (
    DuplicateSourceError,
    ProjectConflictError,
    ProjectIntegrityError,
    ProjectNotFoundError,
    ProjectStore,
    ProjectValidationError,
)


def _wav(path: Path, *, frequency: float, sample_rate: int = 48_000, seconds: float = 0.5) -> None:
    frames = round(sample_rate * seconds)
    time = np.arange(frames, dtype=np.float64) / sample_rate
    sf.write(path, (0.2 * np.sin(2 * np.pi * frequency * time)).astype(np.float32), sample_rate)


def test_create_import_reopen_and_public_views_do_not_expose_paths(tmp_path: Path) -> None:
    """A project must survive reopen while its public DTO stays path-free."""

    workspace = tmp_path / "workspace"
    source_path = tmp_path / "話者 one.wav"
    _wav(source_path, frequency=337, sample_rate=44_100)
    store = ProjectStore(workspace)

    created = store.create("  Épisode 一  ")
    imported = store.import_source(created.id, source_path, name="  Room 左  ")
    reopened = ProjectStore(workspace).get(created.id)
    public = ProjectStore(workspace).get_public(created.id).model_dump(mode="json")
    summaries = ProjectStore(workspace).list()

    assert isinstance(reopened, ProjectRecord)
    assert reopened.name == "Épisode 一"
    assert reopened.revision == 1
    assert reopened.primary_source_id == imported.id
    assert reopened.duration_frames == imported.audio.frames == 24_000
    assert reopened.sources[0].name == "Room 左"
    assert reopened.sources[0].original_filename == "話者 one.wav"
    assert public["sources"][0]["audio"]["source_sample_rate"] == 44_100
    assert "original_path" not in public["sources"][0]
    assert "path" not in public["sources"][0]["audio"]
    assert summaries[0].id == created.id
    assert summaries[0].source_count == 1
    assert str(workspace) not in json.dumps(public, ensure_ascii=False)


def test_duplicate_source_is_rejected_without_changing_revision(tmp_path: Path) -> None:
    """Importing identical bytes twice must not create ambiguous duplicate tracks."""

    source_path = tmp_path / "take.wav"
    _wav(source_path, frequency=220)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    store.import_source(project.id, source_path)

    with pytest.raises(DuplicateSourceError, match="already imported"):
        store.import_source(project.id, source_path, name="Same bytes")

    assert store.get(project.id).revision == 1
    assert len(store.get(project.id).sources) == 1


def test_source_samples_are_read_only_memmap_and_integrity_detects_changed_original(
    tmp_path: Path,
) -> None:
    """Cache access stays disk-backed and a changed immutable original blocks validation."""

    source_path = tmp_path / "take.wav"
    _wav(source_path, frequency=220)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    source = store.import_source(project.id, source_path)

    samples = store.source_samples(project.id, source.id)
    assert isinstance(samples, np.memmap)
    assert samples.flags.writeable is False
    assert samples.shape == (24_000,)
    assert store.validate_sources(project.id) == []

    original = store.source_path(project.id, source.id, "original")
    original.chmod(stat.S_IRUSR | stat.S_IWUSR)
    with original.open("ab") as handle:
        handle.write(b"changed")
    original.chmod(stat.S_IRUSR)

    with pytest.raises(ProjectIntegrityError, match="hash mismatch"):
        store.validate_sources(project.id)


def test_source_ids_and_owned_paths_reject_traversal_and_symlink_escape(tmp_path: Path) -> None:
    """Project/source identifiers cannot select files outside the owned workspace."""

    source_path = tmp_path / "take.wav"
    _wav(source_path, frequency=220)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    source = store.import_source(project.id, source_path)

    with pytest.raises(ProjectValidationError, match="identifier"):
        store.get("../../outside")
    with pytest.raises(ProjectValidationError, match="identifier"):
        store.source_path(project.id, "../../outside", "cache")
    with pytest.raises(ProjectValidationError, match="kind"):
        store.source_path(project.id, source.id, "../../original")

    external = tmp_path / "external.f32le"
    external.write_bytes(b"\x00" * 32)
    cache = store.source_path(project.id, source.id, "cache")
    cache.unlink()
    cache.symlink_to(external)

    with pytest.raises(ProjectIntegrityError, match="symbolic link"):
        store.source_path(project.id, source.id, "cache")


def test_repairs_use_monotonic_revisions_with_conflicts_and_bounded_undo_redo(
    tmp_path: Path,
) -> None:
    """Edits must be validated, conflict-aware, and recoverable in both directions."""

    primary_path = tmp_path / "primary.wav"
    donor_path = tmp_path / "donor.wav"
    _wav(primary_path, frequency=220)
    _wav(donor_path, frequency=330)
    store = ProjectStore(tmp_path / "workspace", history_limit=3)
    project = store.create("Session")
    primary = store.import_source(project.id, primary_path)
    donor = store.import_source(project.id, donor_path)
    store.update_source(project.id, donor.id, {"alignment": {"offset_seconds": 0.0}})

    repaired = store.add_repair(
        project.id,
        start_frame=1_000,
        end_frame=2_000,
        kind="manual",
        source_id=donor.id,
        confidence=1.0,
        reason="editor selected donor",
        status="proposed",
        expected_revision=3,
    )
    accepted = store.update_repair(
        project.id,
        repaired.id,
        {"status": "accepted", "gain_db": -1.5, "fade_ms": 8.0},
        expected_revision=4,
    )

    assert accepted.status == "accepted"
    assert store.get(project.id).revision == 5
    with pytest.raises(ProjectConflictError, match="revision"):
        store.update_repair(project.id, repaired.id, {"status": "rejected"}, expected_revision=3)
    with pytest.raises(ProjectValidationError, match="primary"):
        store.add_repair(
            project.id,
            start_frame=3_000,
            end_frame=4_000,
            kind="manual",
            source_id=primary.id,
            confidence=1.0,
            reason="invalid donor",
            status="accepted",
        )

    undone = store.undo(project.id)
    assert undone.revision == 6
    assert undone.repairs[0].status == "proposed"
    redone = store.redo(project.id)
    assert redone.revision == 7
    assert redone.repairs[0].status == "accepted"
    assert store.history(project.id).undo_depth == 3
    with pytest.raises(ProjectConflictError):
        store.undo(project.id, expected_revision=4)


def test_invalid_edit_and_future_schema_are_rejected(tmp_path: Path) -> None:
    """Malformed ranges and unsupported future manifests cannot be loaded or persisted."""

    source_path = tmp_path / "take.wav"
    _wav(source_path, frequency=220)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    source = store.import_source(project.id, source_path)

    with pytest.raises(ProjectValidationError, match="end_frame"):
        store.add_repair(
            project.id,
            start_frame=10,
            end_frame=10,
            kind="manual",
            source_id=source.id,
            confidence=1.0,
            reason="bad range",
        )

    manifest = tmp_path / "workspace" / project.id / "project.json"
    raw = json.loads(manifest.read_text())
    raw["schema_version"] = 99
    manifest.write_text(json.dumps(raw))

    with pytest.raises(ProjectValidationError, match="schema version 99"):
        store.get(project.id)


def test_delete_removes_only_selected_owned_project(tmp_path: Path) -> None:
    """Deletion must target a validated project ID and leave peer projects intact."""

    store = ProjectStore(tmp_path / "workspace")
    first = store.create("First")
    second = store.create("Second")

    store.delete(first.id)

    with pytest.raises(ProjectNotFoundError):
        store.get(first.id)
    assert store.get(second.id).name == "Second"
    assert (tmp_path / "workspace" / second.id).is_dir()
    assert not (tmp_path / "workspace" / first.id).exists()


def test_project_and_source_metadata_updates_follow_revision_contract(tmp_path: Path) -> None:
    """Names/speakers are editable without changing samples, and stale writes conflict."""

    source_path = tmp_path / "take.wav"
    _wav(source_path, frequency=220)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    source = store.import_source(project.id, source_path)

    renamed = store.rename(project.id, "  Revised session  ", expected_revision=1)
    updated_source = store.update_source(
        project.id,
        source.id,
        {"name": "  Boom mic  ", "speaker": "  Priya  "},
        expected_revision=2,
    )

    assert renamed.name == "Revised session"
    assert updated_source.name == "Boom mic"
    assert updated_source.speaker == "Priya"
    assert store.get(project.id).revision == 3
    with pytest.raises(ProjectConflictError):
        store.rename(project.id, "Stale", expected_revision=1)


def test_project_patch_applies_name_and_primary_as_one_revision(tmp_path: Path) -> None:
    """The API project patch must not create two revisions for one request."""

    primary_path = tmp_path / "primary.wav"
    donor_path = tmp_path / "donor.wav"
    _wav(primary_path, frequency=220, seconds=0.5)
    _wav(donor_path, frequency=330, seconds=0.25)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    store.import_source(project.id, primary_path)
    donor = store.import_source(project.id, donor_path)

    updated = store.update_project(
        project.id,
        name="Short take",
        primary_source_id=donor.id,
        expected_revision=2,
    )

    assert updated.revision == 3
    assert updated.name == "Short take"
    assert updated.primary_source_id == donor.id
    assert updated.duration_frames == 12_000


def test_manual_alignment_invalidates_accepted_repairs_using_that_source(tmp_path: Path) -> None:
    """Changing a donor clock must return accepted edits that use it to unresolved review."""

    primary_path = tmp_path / "primary.wav"
    donor_path = tmp_path / "donor.wav"
    _wav(primary_path, frequency=220)
    _wav(donor_path, frequency=330)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    store.import_source(project.id, primary_path)
    donor = store.import_source(project.id, donor_path)
    store.update_source(project.id, donor.id, {"alignment": {"offset_seconds": 0.0}})
    repair = store.add_repair(
        project.id,
        start_frame=1_000,
        end_frame=2_000,
        kind="manual",
        source_id=donor.id,
        confidence=1.0,
        reason="editor",
        status="accepted",
    )

    aligned = store.update_source(
        project.id,
        donor.id,
        {"alignment": {"offset_seconds": 0.125, "drift_ppm": 10.0, "polarity": -1}},
        expected_revision=4,
    )
    saved = store.get(project.id)

    assert aligned.alignment.status == "manual"
    assert aligned.alignment.offset_seconds == 0.125
    assert aligned.alignment.drift_ppm == 10.0
    assert aligned.alignment.polarity == -1
    assert saved.repairs[0].id == repair.id
    assert saved.repairs[0].status == "unresolved"
    assert "review" in saved.warnings[-1].lower()


def test_changing_primary_rebases_clock_and_clears_analysis_and_repairs(tmp_path: Path) -> None:
    """A new primary must define duration and explicitly reset incompatible analysis."""

    primary_path = tmp_path / "primary.wav"
    donor_path = tmp_path / "short donor.wav"
    _wav(primary_path, frequency=220, seconds=0.5)
    _wav(donor_path, frequency=330, seconds=0.25)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    primary = store.import_source(project.id, primary_path)
    donor = store.import_source(project.id, donor_path)
    store.add_repair(
        project.id,
        start_frame=1_000,
        end_frame=2_000,
        kind="manual",
        source_id=donor.id,
        confidence=1.0,
        reason="editor",
    )

    changed = store.set_primary_source(project.id, donor.id, expected_revision=3)

    assert changed.primary_source_id == donor.id
    assert changed.duration_frames == 12_000
    assert changed.repairs == []
    assert changed.status == "ready"
    assert (
        next(item for item in changed.sources if item.id == donor.id).alignment.status
        == "reference"
    )
    assert (
        next(item for item in changed.sources if item.id == primary.id).alignment.status
        == "uncertain"
    )
    assert "reset" in changed.warnings[-1].lower()


def test_transcript_records_and_history_state_persist_without_interpreting_content(
    tmp_path: Path,
) -> None:
    """Imported transcript dicts stay generic/JSON-safe and history reports durable state."""

    source_path = tmp_path / "take.wav"
    _wav(source_path, frequency=220)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    source = store.import_source(project.id, source_path)
    transcript = {
        "id": "transcript-1",
        "source_id": source.id,
        "format": "json",
        "turns": [{"text": "<script>literal</script>", "start_ms": 1000}],
        "warnings": [],
    }

    saved = store.add_transcript(project.id, transcript, expected_revision=1)
    state = store.history(project.id)

    assert saved.transcripts == [transcript]
    assert state.can_undo is True
    assert state.can_redo is False
    store.undo(project.id, expected_revision=2)
    reopened_state = ProjectStore(tmp_path / "workspace").history(project.id)
    assert reopened_state.can_undo is True
    assert reopened_state.can_redo is True


def test_analyze_uses_disk_caches_and_persists_engine_alignment(tmp_path: Path) -> None:
    """Analysis must serialize the real engine contract into a new durable revision."""

    primary_path = tmp_path / "primary.wav"
    donor_path = tmp_path / "donor.wav"
    frames = 48_000 * 4
    rng = np.random.default_rng(42)
    signal = sosfilt(
        butter(3, [160, 4_000], fs=48_000, btype="bandpass", output="sos"),
        rng.normal(size=frames),
    ).astype(np.float32)
    sf.write(primary_path, signal, 48_000, subtype="FLOAT")
    sf.write(donor_path, signal * 0.8, 48_000, subtype="FLOAT")
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    primary = store.import_source(project.id, primary_path)
    donor = store.import_source(project.id, donor_path)

    analyzed = store.analyze(project.id, expected_revision=2)

    assert analyzed.revision == 3
    assert analyzed.status == "analyzed"
    assert analyzed.error is None
    assert (
        next(item for item in analyzed.sources if item.id == primary.id).alignment.status
        == "reference"
    )
    donor_alignment = next(item for item in analyzed.sources if item.id == donor.id).alignment
    assert donor_alignment.status == "aligned"
    assert abs(donor_alignment.offset_seconds) < 0.002


def test_cancelled_analysis_leaves_revision_and_decisions_unchanged(tmp_path: Path) -> None:
    """A pre-cancelled analysis must not publish status, transforms, or a revision."""

    source_path = tmp_path / "take.wav"
    _wav(source_path, frequency=220)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    store.import_source(project.id, source_path)
    before = store.get(project.id)

    after = store.analyze(project.id, expected_revision=1, cancelled=lambda: True)

    assert after == before
    assert store.get(project.id) == before


def test_failed_media_import_preserves_manifest_and_removes_partial_outputs(tmp_path: Path) -> None:
    """A decode failure must not advance revision or leave source/cache artifacts."""

    invalid = tmp_path / "broken.mov"
    invalid.write_bytes(b"not a media container")
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")

    with pytest.raises(ProjectValidationError, match="audio"):
        store.import_source(project.id, invalid)

    assert store.get(project.id) == project
    project_dir = tmp_path / "workspace" / project.id
    assert list((project_dir / "originals").iterdir()) == []
    assert list((project_dir / "cache").iterdir()) == []


def test_changed_cache_is_detected_even_when_its_size_is_unchanged(tmp_path: Path) -> None:
    """A same-size cache mutation must not silently become rendering input."""

    source_path = tmp_path / "take.wav"
    _wav(source_path, frequency=220)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    source = store.import_source(project.id, source_path)
    cache = store.source_path(project.id, source.id, "cache")
    with cache.open("r+b") as handle:
        handle.seek(128)
        handle.write(b"\xff\xff\xff\xff")

    with pytest.raises(ProjectIntegrityError, match="cache hash mismatch"):
        store.validate_sources(project.id)


def test_history_symlink_tampering_cannot_write_outside_project(tmp_path: Path) -> None:
    """An attacker-controlled history symlink cannot redirect a revision snapshot."""

    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    outside.mkdir()
    store = ProjectStore(workspace)
    project = store.create("Session")
    undo_dir = workspace / project.id / ".history" / "undo"
    undo_dir.rmdir()
    undo_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ProjectIntegrityError, match="history"):
        store.rename(project.id, "Unsafe", expected_revision=0)

    assert store.get(project.id).name == "Session"
    assert list(outside.iterdir()) == []


def test_analysis_failure_persists_safe_error_without_replacing_sources(tmp_path: Path) -> None:
    """A failed analysis becomes visible while the last valid media/edit state remains."""

    primary_path = tmp_path / "primary.wav"
    donor_path = tmp_path / "donor.wav"
    _wav(primary_path, frequency=220)
    _wav(donor_path, frequency=330)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Session")
    primary = store.import_source(project.id, primary_path)
    donor = store.import_source(project.id, donor_path)
    original = store.source_path(project.id, donor.id, "original")
    original.chmod(stat.S_IRUSR | stat.S_IWUSR)
    with original.open("ab") as handle:
        handle.write(b"changed")
    original.chmod(stat.S_IRUSR)

    with pytest.raises(ProjectIntegrityError, match="hash mismatch"):
        store.analyze(project.id, expected_revision=2)

    failed = store.get(project.id)
    assert failed.revision == 3
    assert failed.status == "error"
    assert failed.error is not None and "hash mismatch" in failed.error
    assert [source.id for source in failed.sources] == [primary.id, donor.id]
    assert failed.repairs == []


def _repair_session(tmp_path: Path) -> tuple[ProjectStore, ProjectRecord, str]:
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Review")
    for name, level in (("main", 0.1), ("donor", 0.5)):
        path = tmp_path / f"{name}.wav"
        sf.write(path, np.full(24_000, level, dtype=np.float32), 48_000, subtype="FLOAT")
        donor = store.import_source(project.id, path)
    return store, store.get(project.id), donor.id


def test_manual_alignment_survives_analysis_and_reopen(tmp_path: Path) -> None:
    """Rerunning detection must retain the editor's authoritative donor clock."""

    store, project, donor_id = _repair_session(tmp_path)
    manual = store.update_source(
        project.id,
        donor_id,
        {
            "alignment": {
                "offset_seconds": 0.125,
                "drift_ppm": 37.0,
                "polarity": -1,
            }
        },
    ).alignment

    analyzed = store.analyze(project.id)
    reopened = ProjectStore(store.root).get(project.id)

    assert analyzed.status == "analyzed"
    assert next(s for s in reopened.sources if s.id == donor_id).alignment == manual


@pytest.mark.parametrize("operation", ["add", "update"])
@pytest.mark.parametrize("invalid", ["uncertain", "prefix", "suffix", "overlap", "gain"])
def test_unrenderable_acceptance_is_rejected_without_writing(
    tmp_path: Path,
    operation: str,
    invalid: str,
) -> None:
    """Accepted edits must satisfy playback constraints before manifest/history writes."""

    store, project, donor_id = _repair_session(tmp_path)
    if invalid != "uncertain":
        offset = -1.0 if invalid == "prefix" else 1.0 if invalid == "suffix" else 0.0
        store.update_source(project.id, donor_id, {"alignment": {"offset_seconds": offset}})
    if invalid == "overlap":
        store.add_repair(
            project.id,
            start_frame=100,
            end_frame=300,
            kind="manual",
            source_id=donor_id,
            confidence=1.0,
            reason="first",
            status="accepted",
        )
    fields = dict(
        start_frame=100,
        end_frame=200,
        kind="manual",
        source_id=donor_id,
        confidence=1.0,
        reason="candidate",
        gain_db=12.0 if invalid == "gain" else 0.0,
    )
    if operation == "update":
        pending = store.add_repair(project.id, **fields)
    manifest = store.root / project.id / "project.json"
    before, history = manifest.read_bytes(), store.history(project.id)
    revision = store.get(project.id).revision

    with pytest.raises(ProjectValidationError):
        if operation == "add":
            store.add_repair(project.id, **fields, status="accepted", expected_revision=revision)
        else:
            store.update_repair(project.id, pending.id, {"status": "accepted"}, revision)

    assert manifest.read_bytes() == before
    assert store.get(project.id).revision == revision
    assert store.history(project.id) == history


def test_accepted_gain_update_validates_entire_interval_before_writing(tmp_path: Path) -> None:
    """A late donor peak must reject gain even when the first render chunk is quiet."""

    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Long repair")
    primary_path, donor_path = tmp_path / "main.wav", tmp_path / "donor.wav"
    samples = np.full(300_000, 0.1, dtype=np.float32)
    sf.write(primary_path, samples, 48_000, subtype="FLOAT")
    samples[-1] = 0.5
    sf.write(donor_path, samples, 48_000, subtype="FLOAT")
    store.import_source(project.id, primary_path)
    donor = store.import_source(project.id, donor_path)
    store.update_source(project.id, donor.id, {"alignment": {"offset_seconds": 0.0}})
    repair = store.add_repair(
        project.id,
        start_frame=0,
        end_frame=len(samples),
        kind="manual",
        source_id=donor.id,
        confidence=1.0,
        reason="whole",
        status="accepted",
    )
    before = store.get(project.id)
    with pytest.raises(ProjectValidationError, match="full scale"):
        store.update_repair(project.id, repair.id, {"gain_db": 12.0})
    assert store.get(project.id) == before


def test_adjacent_accepted_edits_with_manual_drift_render_and_survive_history(
    tmp_path: Path,
) -> None:
    """Supported manual drift and touching ranges remain playable after undo/redo."""

    from cleantake.engine import Alignment, CandidateTrack, render_range

    store, project, donor_id = _repair_session(tmp_path)
    donor = store.update_source(project.id, donor_id, {"alignment": {"drift_ppm": 100_000.0}})
    for start, end in ((100, 200), (200, 300)):
        store.add_repair(
            project.id,
            start_frame=start,
            end_frame=end,
            kind="manual",
            source_id=donor_id,
            confidence=1.0,
            reason="adjacent",
            status="accepted",
            gain_db=-6.0,
            fade_ms=0.0,
        )
    store.undo(project.id)
    restored = store.redo(project.id)
    output = render_range(
        store.source_samples(project.id, project.primary_source_id),
        [
            CandidateTrack(
                donor_id,
                store.source_samples(project.id, donor_id),
                Alignment(**donor.alignment.model_dump()),
            )
        ],
        restored.repairs,
        100,
        300,
        48_000,
    )
    np.testing.assert_allclose(output, 0.2505936168136361)
    assert len(restored.repairs) == 2


@pytest.mark.parametrize(
    "alignment",
    [
        {"drift_ppm": -1_000_000.0},
        {"drift_ppm": -1_000_001.0},
        {"drift_ppm": 10**1000},
        {"offset_seconds": 1e308},
    ],
)
def test_invalid_manual_clock_is_rejected_without_revision_change(
    tmp_path: Path,
    alignment: dict,
) -> None:
    """Nonpositive or overflowing preview coordinates cannot become saved clocks."""

    store, project, donor_id = _repair_session(tmp_path)
    with pytest.raises(ProjectValidationError, match="clock|finite"):
        store.update_source(project.id, donor_id, {"alignment": alignment})
    assert store.get(project.id) == project


@pytest.mark.parametrize("directory", ["originals", "cache"])
def test_import_rejects_symlink_destination_before_writing(tmp_path: Path, directory: str) -> None:
    """Both owned destination directories must be checked before any import output."""

    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Boundary")
    source_path = tmp_path / "sample.wav"
    _wav(source_path, frequency=220)
    outside = tmp_path / "outside"
    outside.mkdir()
    destination = store.root / project.id / directory
    destination.rmdir()
    destination.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ProjectValidationError, match="symbolic link"):
        store.import_source(project.id, source_path)
    assert list(outside.iterdir()) == []
    other = "cache" if directory == "originals" else "originals"
    assert list((store.root / project.id / other).iterdir()) == []
    assert store.get(project.id) == project


def test_delete_removes_imported_read_only_originals(tmp_path: Path) -> None:
    """Deleting a real imported project must remove immutable originals on Windows too."""

    store, project, _ = _repair_session(tmp_path)
    untouched = store.create("Keep")
    originals = [store.source_path(project.id, s.id, "original") for s in project.sources]
    assert all(not p.stat().st_mode & stat.S_IWUSR for p in originals)
    store.delete(project.id)
    assert not (store.root / project.id).exists()
    assert store.get(untouched.id) == untouched


def test_failed_import_removes_read_only_originals(tmp_path: Path) -> None:
    """Validation after decoding must clean immutable originals, including on Windows."""

    source_path = tmp_path / "source.wav"
    _wav(source_path, frequency=220)
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Cleanup")
    with pytest.raises(ValueError):
        store.import_source(project.id, source_path, name=" ")
    assert list((store.root / project.id / "originals").iterdir()) == []
    assert list((store.root / project.id / "cache").iterdir()) == []
    assert store.get(project.id) == project


@pytest.mark.parametrize(
    "offset_frames,start,end,valid",
    [
        (0.0, 0, 24_000, True),
        (-0.5, 0, 100, False),
        (0.5, 23_900, 24_000, False),
        (0.5, 23_900, 23_999, True),
    ],
)
def test_accepted_coverage_includes_fractional_interpolation_support(
    tmp_path: Path,
    offset_frames: float,
    start: int,
    end: int,
    valid: bool,
) -> None:
    """The last included sample must have real interpolation support in its donor."""

    store, project, donor_id = _repair_session(tmp_path)
    store.update_source(
        project.id,
        donor_id,
        {
            "alignment": {
                "offset_seconds": offset_frames / 48_000,
            }
        },
    )
    before = store.get(project.id)
    fields = dict(
        start_frame=start,
        end_frame=end,
        kind="manual",
        source_id=donor_id,
        confidence=1.0,
        reason="coverage edge",
        status="accepted",
        fade_ms=0,
    )
    if valid:
        repair = store.add_repair(project.id, **fields)
        assert repair.status == "accepted"
    else:
        with pytest.raises(ProjectValidationError, match="coverage"):
            store.add_repair(project.id, **fields)
        assert store.get(project.id) == before


@pytest.mark.parametrize("operation", ["rename", "undo", "redo"])
def test_failed_manifest_publication_keeps_both_history_stacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """A failed publication cannot consume redo or evict the oldest retained undo."""
    store = ProjectStore(tmp_path / "workspace", history_limit=2)
    project = store.create("First")
    store.rename(project.id, "Second")
    store.rename(project.id, "Third")
    if operation == "redo":
        store.undo(project.id)
    elif operation == "rename":
        store.undo(project.id)
        store.undo(project.id)
    manifest = store.root / project.id / "project.json"
    before = manifest.read_bytes()
    history = store.history(project.id)
    real_replace = __import__("os").replace

    def unavailable_manifest(source, destination):
        if Path(destination) == manifest:
            raise PermissionError("manifest destination is unavailable")
        return real_replace(source, destination)

    with monkeypatch.context() as failure:
        failure.setattr("cleantake.projects.os.replace", unavailable_manifest)
        with pytest.raises(PermissionError):
            if operation == "rename":
                store.rename(project.id, "Unpublished")
            else:
                getattr(store, operation)(project.id)

    reopened = ProjectStore(store.root, history_limit=2)
    assert manifest.read_bytes() == before
    assert reopened.history(project.id) == history
    if operation == "rename":
        assert reopened.redo(project.id).name == "Second"
        assert reopened.redo(project.id).name == "Third"
    elif operation == "undo":
        assert reopened.undo(project.id).name == "Second"
        assert reopened.undo(project.id).name == "First"
    else:
        assert reopened.redo(project.id).name == "Third"


def test_unavailable_history_storage_does_not_publish_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Metadata publication depends on successfully preparing its history."""
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("First")
    store.rename(project.id, "Second")
    before = store.get(project.id)
    history = store.history(project.id)
    real_replace = __import__("os").replace

    def unavailable_history(source, destination):
        if ".history" in Path(destination).parts:
            raise OSError("history storage unavailable")
        return real_replace(source, destination)

    with monkeypatch.context() as failure:
        failure.setattr("cleantake.projects.os.replace", unavailable_history)
        with pytest.raises(OSError):
            store.rename(project.id, "Unpublished")

    assert ProjectStore(store.root).get(project.id) == before
    assert store.history(project.id) == history


def test_history_cleanup_failure_does_not_expose_discarded_redo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a new edit commits, leftover files cannot resurrect the abandoned branch."""
    store = ProjectStore(tmp_path / "workspace", history_limit=2)
    project = store.create("First")
    store.rename(project.id, "Second")
    store.undo(project.id)
    real_unlink = Path.unlink

    def unavailable_cleanup(path, *args, **kwargs):
        if ".history" in path.parts and path.suffix == ".json":
            raise PermissionError("old history cleanup unavailable")
        return real_unlink(path, *args, **kwargs)

    with monkeypatch.context() as failure:
        failure.setattr(Path, "unlink", unavailable_cleanup)
        saved = store.rename(project.id, "Replacement")
    reopened = ProjectStore(store.root, history_limit=2)
    assert reopened.get(project.id) == saved
    assert reopened.history(project.id).can_redo is False
    assert reopened.undo(project.id).name == "First"
    assert reopened.redo(project.id).name == "Replacement"


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("failure_point", ["history", "manifest"])
def test_first_history_preparation_failure_preserves_existing_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy: bool,
    failure_point: str,
) -> None:
    """Empty and pre-index projects keep their state when initial preparation fails."""
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("First")
    directory = store.root / project.id
    if legacy:
        store.rename(project.id, "Second")
        store.undo(project.id)
        for index in (directory / ".history").glob("index-*.json"):
            index.unlink()
    before = (directory / "project.json").read_bytes()
    history = store.history(project.id)
    real_replace = __import__("os").replace

    def unavailable_storage(source, destination):
        destination = Path(destination)
        if (failure_point == "history" and destination.parent.name == ".history") or (
            failure_point == "manifest" and destination == directory / "project.json"
        ):
            raise PermissionError("publication storage is unavailable")
        return real_replace(source, destination)

    with monkeypatch.context() as failure:
        failure.setattr("cleantake.projects.os.replace", unavailable_storage)
        with pytest.raises(PermissionError):
            store.rename(project.id, "Unpublished")
    reopened = ProjectStore(store.root)
    assert (directory / "project.json").read_bytes() == before
    assert reopened.history(project.id) == history
    if legacy:
        assert reopened.redo(project.id).name == "Second"
        assert reopened.undo(project.id).name == "First"
    assert reopened.rename(project.id, "Saved").name == "Saved"
    assert reopened.undo(project.id).name == "First"


def test_directory_sync_failure_after_replacement_reports_the_published_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A post-replace sync error cannot make callers discard now-owned project data."""
    import os

    if os.name == "nt":
        pytest.skip("Directory synchronization is not performed on Windows")
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("First")
    directory_stat = (store.root / project.id).stat()
    real_fsync = os.fsync

    def unavailable_directory_sync(descriptor):
        target = os.fstat(descriptor)
        if (target.st_dev, target.st_ino) == (directory_stat.st_dev, directory_stat.st_ino):
            raise OSError("directory sync unavailable after replacement")
        return real_fsync(descriptor)

    with monkeypatch.context() as failure:
        failure.setattr("cleantake.projects.os.fsync", unavailable_directory_sync)
        saved = store.rename(project.id, "Published")
    assert ProjectStore(store.root).get(project.id) == saved
    assert saved.name == "Published"
    assert store.undo(project.id).name == "First"
    assert store.redo(project.id).name == "Published"


def test_failed_history_cleanup_keeps_the_visible_retention_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retention belongs to the committed index, even when obsolete files remain."""
    store = ProjectStore(tmp_path / "workspace", history_limit=2)
    project = store.create("First")
    store.rename(project.id, "Second")
    store.rename(project.id, "Third")
    real_unlink = Path.unlink

    def unavailable_cleanup(path, *args, **kwargs):
        if ".history" in path.parts and path.suffix == ".json":
            raise PermissionError("old history cleanup unavailable")
        return real_unlink(path, *args, **kwargs)

    with monkeypatch.context() as failure:
        failure.setattr(Path, "unlink", unavailable_cleanup)
        store.rename(project.id, "Fourth")
    reopened = ProjectStore(store.root, history_limit=2)
    assert reopened.history(project.id).undo_depth == 2
    assert reopened.undo(project.id).name == "Third"
    assert reopened.undo(project.id).name == "Second"
    assert reopened.history(project.id).can_undo is False


def test_initial_project_publication_failure_leaves_no_partial_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ProjectStore(tmp_path / "workspace")
    real_replace = __import__("os").replace

    def unavailable_manifest(source, destination):
        if Path(destination).name == "project.json":
            raise PermissionError("initial project publication unavailable")
        return real_replace(source, destination)

    with monkeypatch.context() as failure:
        failure.setattr("cleantake.projects.os.replace", unavailable_manifest)
        with pytest.raises(PermissionError):
            store.create("Unpublished")
    assert store.list() == []
    assert list(store.root.iterdir()) == []
