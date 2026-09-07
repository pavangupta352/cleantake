from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cleantake.exports import ExportCancelled, ExportError, export_project, finish_audio
from cleantake.projects import ProjectIntegrityError, ProjectStore


@pytest.fixture
def session(tmp_path: Path):
    rate = 48_000
    t = np.arange(rate, dtype=np.float64) / rate
    primary = (0.15 * np.sin(2 * np.pi * 317 * t)).astype(np.float32)
    donor = (0.2 * np.sin(2 * np.pi * 617 * t)).astype(np.float32)
    sf.write(tmp_path / "primary.wav", primary, rate, subtype="FLOAT")
    sf.write(tmp_path / "donor.wav", donor, rate, subtype="FLOAT")
    store = ProjectStore(tmp_path / "workspace")
    project = store.create('A "quoted" session')
    first = store.import_source(project.id, tmp_path / "primary.wav")
    second = store.import_source(project.id, tmp_path / "donor.wav")
    store.update_source(project.id, second.id, {"alignment": {"offset_seconds": 0}})
    return store, project.id, first, second, primary, donor


def test_export_contains_literal_donor_and_both_fade_contributors(session, tmp_path):
    store, pid, first, second, primary, donor = session
    store.add_repair(
        pid,
        start_frame=12_000,
        end_frame=24_000,
        kind="manual",
        source_id=second.id,
        confidence=1,
        reason="Reviewed",
        status="accepted",
        fade_ms=10,
        gain_db=-6,
    )
    out = tmp_path / "render"
    result = export_project(store, pid, out)
    samples, rate = sf.read(out / "dialogue.wav", dtype="float32")
    assert rate == 48_000 and samples.shape == primary.shape
    np.testing.assert_array_equal(samples[:12_000], primary[:12_000])
    np.testing.assert_array_equal(samples[24_000:], primary[24_000:])
    np.testing.assert_allclose(
        samples[12_480:23_520], donor[12_480:23_520] * 10 ** (-6 / 20), atol=1e-7
    )
    provenance = json.loads((out / "source-map.json").read_text())
    assert provenance["project_revision"] == store.get(pid).revision == result["revision"]
    assert provenance["output"]["frames"] == 48_000
    assert provenance["output"]["subtype"] == "FLOAT"
    assert provenance["sources"][0]["sha256"] == first.sha256
    fades = [span for span in provenance["spans"] if len(span["contributors"]) == 2]
    assert len(fades) == 2
    assert {c["source_id"] for c in fades[0]["contributors"]} == {first.id, second.id}
    assert fades[0]["start_frame"] == 12_000
    assert fades[0]["end_frame"] == 12_480
    contributor = next(c for c in fades[0]["contributors"] if c["source_id"] == second.id)
    assert contributor["source_start_frame"] == 12_000
    assert contributor["original_clock_start_frame"] == 12_000
    assert str(tmp_path) not in (out / "source-map.json").read_text()
    names = {artifact["name"] for artifact in result["artifacts"]}
    assert {"dialogue.wav", "source-map.json", "session.rpp"} <= names
    assert len([name for name in names if name.startswith("stems/")]) == 2
    for artifact in result["artifacts"]:
        assert (out / artifact["name"]).stat().st_size == artifact["size"]


def test_unaccepted_repairs_do_not_change_export(session, tmp_path):
    store, pid, _, second, primary, _ = session
    store.add_repair(
        pid,
        start_frame=100,
        end_frame=500,
        kind="manual",
        source_id=second.id,
        confidence=1,
        reason="Unreviewed",
    )
    export_project(store, pid, tmp_path / "render")
    audio, _ = sf.read(tmp_path / "render/dialogue.wav", dtype="float32")
    np.testing.assert_array_equal(audio, primary)


def test_flac_quantization_is_explicit_and_bounded(session, tmp_path):
    store, pid, _, _, primary, _ = session
    export_project(store, pid, tmp_path / "render", format="flac")
    info = sf.info(tmp_path / "render/dialogue.flac")
    assert info.subtype == "PCM_24" and info.frames == len(primary)
    audio, _ = sf.read(tmp_path / "render/dialogue.flac", dtype="float32")
    np.testing.assert_allclose(audio, primary, atol=2**-23)
    manifest = json.loads((tmp_path / "render/source-map.json").read_text())
    assert manifest["output"]["subtype"] == "PCM_24"


def test_export_refuses_existing_destination_and_changed_source(session, tmp_path):
    store, pid, _, second, _, _ = session
    out = tmp_path / "render"
    out.mkdir()
    (out / "keep").write_text("keep")
    with pytest.raises(ExportError, match="exists"):
        export_project(store, pid, out)
    assert (out / "keep").read_text() == "keep"
    cache = store.source_path(pid, second.id, "cache")
    with cache.open("r+b") as handle:
        handle.write(b"bad!")
    with pytest.raises(ProjectIntegrityError):
        export_project(store, pid, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_cancelled_export_never_publishes_partial_outputs(session, tmp_path):
    store, pid, *_ = session
    with pytest.raises(ExportCancelled):
        export_project(store, pid, tmp_path / "cancelled", cancelled=lambda: True)
    assert not (tmp_path / "cancelled").exists()
    assert not list(tmp_path.glob(".cancelled.*"))


def test_reaper_session_references_existing_stems_and_editable_weight_envelopes(session, tmp_path):
    store, pid, first, second, *_ = session
    store.add_repair(
        pid,
        start_frame=12_000,
        end_frame=24_000,
        kind="manual",
        source_id=second.id,
        confidence=1,
        reason="Reviewed",
        status="accepted",
        fade_ms=10,
    )
    out = tmp_path / "render"
    export_project(store, pid, out)
    text = (out / "session.rpp").read_text()
    assert text.startswith("<REAPER_PROJECT")
    assert text.count("<VOLENV2") == 2
    assert f'FILE "stems/{first.id}.wav"' in text
    assert f'FILE "stems/{second.id}.wav"' in text
    assert "PT 0.25 " in text
    assert "PT 0.5 " in text
    assert str(tmp_path) not in text


def test_finishing_meets_loudness_and_peak_targets_preserving_frames_and_input(tmp_path):
    rate = 48_000
    time = np.arange(rate * 12) / rate
    original = (0.015 * np.sin(2 * np.pi * 440 * time)).astype(np.float32)
    source, target = tmp_path / "quiet.wav", tmp_path / "finished.wav"
    sf.write(source, original, rate, subtype="FLOAT")
    before = source.read_bytes()
    result = finish_audio(source, target)
    assert result["status"] == "finished"
    assert result["target_met"] is True
    assert result["warnings"] == []
    assert abs(result["measured"]["integrated_lufs"] - (-16)) < 0.3
    assert abs(result["loudness_error_lu"]) <= result["loudness_tolerance_lu"]
    assert result["measured"]["true_peak_dbtp"] <= -0.9
    assert result["measured"]["method"] == "ffmpeg ebur128"
    assert sf.info(target).frames == len(original)
    assert source.read_bytes() == before


def test_silent_finishing_has_an_explicit_unmodified_result(tmp_path):
    source, target = tmp_path / "silence.wav", tmp_path / "finished.wav"
    sf.write(source, np.zeros(48_000), 48_000, subtype="FLOAT")
    result = finish_audio(source, target)
    assert result["status"] == "skipped"
    assert result["target_met"] is False
    assert result["loudness_error_lu"] is None
    assert result["warnings"]
    assert "measurable" in result["reason"]
    audio, _ = sf.read(target)
    assert not np.any(audio)


def test_finishing_target_miss_warns_without_changing_unmastered_export(tmp_path):
    fixture = Path(__file__).parent / "engine/data/ES2004a_0324-0344_Headset-0.wav"
    speech, rate = sf.read(fixture, dtype="float32")
    # Three real speech passages with increasing levels force dynamic normalization.
    # Its true-peak-limited output misses the integrated target by several LU.
    source = tmp_path / "varying-speech.wav"
    sf.write(
        source,
        np.concatenate([speech * 0.01, speech * 0.1, speech]),
        rate,
        subtype="FLOAT",
    )
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Varying speech")
    store.import_source(project.id, source)
    export_project(store, project.id, tmp_path / "plain")
    result = export_project(store, project.id, tmp_path / "finished", finish=True)
    provenance = json.loads((tmp_path / "finished/source-map.json").read_text())
    processing = provenance["processing"][0]

    assert processing["measured"]["integrated_lufs"] < -17
    assert processing["measured"]["true_peak_dbtp"] <= -0.9
    assert processing["status"] == "finished"
    assert processing["target_met"] is False
    assert processing["loudness_error_lu"] < -1
    assert processing["loudness_tolerance_lu"] == 0.5
    assert result["warnings"] == provenance["warnings"] == processing["warnings"]
    assert any("target" in warning and "LUFS" in warning for warning in result["warnings"])
    assert sf.info(tmp_path / "finished/dialogue-finished.wav").frames == 2_880_000
    # The FLOAT WAV PEAK timestamp may differ between independent exports.
    unmastered, _ = sf.read(tmp_path / "finished/dialogue.wav", dtype="float32")
    plain, _ = sf.read(tmp_path / "plain/dialogue.wav", dtype="float32")
    np.testing.assert_array_equal(unmastered, plain)
    assert (
        provenance["output"]["sha256"]
        == hashlib.sha256((tmp_path / "finished/dialogue.wav").read_bytes()).hexdigest()
    )
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert (
        processing["sha256"]
        == hashlib.sha256((tmp_path / "finished/dialogue-finished.wav").read_bytes()).hexdigest()
    )


def test_skipped_finishing_warning_reaches_export_result_and_source_map(tmp_path):
    source = tmp_path / "silence.wav"
    sf.write(source, np.zeros(48_000), 48_000, subtype="FLOAT")
    before = source.read_bytes()
    store = ProjectStore(tmp_path / "workspace")
    project = store.create("Silence")
    store.import_source(project.id, source)
    result = export_project(store, project.id, tmp_path / "export", finish=True)
    provenance = json.loads((tmp_path / "export/source-map.json").read_text())
    processing = provenance["processing"][0]

    assert result["warnings"]
    assert result["warnings"] == provenance["warnings"] == processing["warnings"]
    assert processing["status"] == "skipped"
    assert processing["target_met"] is False
    assert processing["loudness_error_lu"] is None
    assert source.read_bytes() == before
    for name in ("dialogue.wav", "dialogue-finished.wav"):
        samples, rate = sf.read(tmp_path / "export" / name)
        assert rate == 48_000 and len(samples) == 48_000
        assert not np.any(samples)


@pytest.mark.slow
def test_long_ffmpeg_measurement_retains_its_final_summary(tmp_path):
    from cleantake.exports import _ffmpeg

    source = tmp_path / "one-second.wav"
    sf.write(
        source, 0.1 * np.sin(2 * np.pi * 440 * np.arange(48_000) / 48_000), 48_000, subtype="FLOAT"
    )
    log = _ffmpeg(
        source,
        "aloop=loop=-1:size=48000,atrim=end_sample=345600000,ebur128=peak=true",
        ["-f", "null", "-"],
        None,
    )
    assert len(log.encode()) <= 4 * 1024**2
    assert "Summary:" in log
    assert "Integrated loudness:" in log.rsplit("Summary:", 1)[-1]
    assert "Peak:" in log.rsplit("Summary:", 1)[-1]
