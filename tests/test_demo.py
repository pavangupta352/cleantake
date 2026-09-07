from __future__ import annotations

import json

import numpy as np
import soundfile as sf
from typer.testing import CliRunner

from cleantake.cli import app
from cleantake.projects import ProjectStore


def test_offline_demo_creates_real_reviewable_recovery(tmp_path):
    result = CliRunner().invoke(app, ["--workspace", str(tmp_path), "demo"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["injected_fault_seconds"] == [17.0, 17.5]
    assert payload["license"] == "CC-BY-4.0"
    store = ProjectStore(tmp_path / "projects")
    project = store.get(payload["project_id"])
    assert len(project.sources) == 2 and project.duration_frames == 960_000
    proposals = [repair for repair in project.repairs if repair.status == "proposed"]
    assert len(proposals) == 1
    assert proposals[0].source_id != project.primary_source_id
    assert 816_000 <= proposals[0].start_frame <= 817_000
    assert 839_000 <= proposals[0].end_frame <= 840_000
    assert not any(repair.status == "accepted" for repair in project.repairs)
    main = store.source_samples(project.id, project.primary_source_id)
    assert np.max(np.abs(main[817_000:839_000])) == 0
    assert store.validate_sources(project.id) == []


def test_sample_preparation_preserves_real_backup_and_labels_the_fault(tmp_path):
    from cleantake.demo import prepare_demo

    destination = tmp_path / "recordings"
    manifest = prepare_demo(destination)
    damaged, rate = sf.read(destination / "Headset-injected-dropout.wav")
    original, _ = sf.read(destination / "Headset-original.wav")
    assert np.array_equal(damaged[: 17 * rate], original[: 17 * rate])
    assert np.array_equal(damaged[int(17.5 * rate) :], original[int(17.5 * rate) :])
    assert not np.any(damaged[17 * rate : int(17.5 * rate)])
    assert np.any(original[17 * rate : int(17.5 * rate)])
    assert manifest["automatic_acceptance"] is False
    assert "CC-BY" in (destination / "manifest.json").read_text()
    assert (destination / "ATTRIBUTION.md").is_file()
    assert (destination / "Lapel-backup.wav").stat().st_size > 0


def test_sample_preparation_never_overwrites_an_existing_directory(tmp_path):
    import pytest

    from cleantake.demo import prepare_demo

    keep = tmp_path / "keep.txt"
    keep.write_text("keep this")
    with pytest.raises(ValueError, match="exists"):
        prepare_demo(tmp_path)
    assert keep.read_text() == "keep this"
