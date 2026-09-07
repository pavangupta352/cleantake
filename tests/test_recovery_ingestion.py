"""Real licensed microphone recovery through the public media/project path."""

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cleantake.exports import export_project
from cleantake.projects import ProjectStore


@pytest.mark.media
def test_resampled_microphone_dropout_is_recovered_from_import_to_export(tmp_path):
    """Resampling fringes must not hide a gap or leave whole silent edge windows."""
    fixtures = Path(__file__).parent / "engine" / "data"
    primary, source_rate = sf.read(fixtures / "ES2004a_0324-0344_Headset-0.wav")
    assert source_rate == 16_000
    # Injected fault on licensed simultaneous speech, meeting time 341–341.5 s.
    primary[272_000:280_000] = 0
    damaged_path = tmp_path / "headset-injected-dropout.wav"
    sf.write(damaged_path, primary, source_rate, subtype="PCM_16")
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Resampled microphone recovery")
    headset = store.import_source(project.id, damaged_path)
    lapel = store.import_source(project.id, fixtures / "ES2004a_0324-0344_Lapel-0.wav")

    analyzed = store.analyze(project.id, expected_revision=2)

    assert analyzed.sample_rate == 48_000
    assert analyzed.duration_frames == 960_000
    assert len(analyzed.repairs) == 1
    repair = analyzed.repairs[0]
    assert repair.source_id == lapel.id and repair.kind == "dropout"
    assert repair.status == "proposed"
    # Allow sub-2 ms filter ringing, but never lose a complete 20 ms evidence frame.
    assert 816_000 <= repair.start_frame < 816_096
    assert 839_904 < repair.end_frame <= 840_000
    donor_source = next(source for source in analyzed.sources if source.id == lapel.id)
    assert donor_source.alignment.status == "aligned"
    store.update_repair(project.id, repair.id, {"status": "accepted"}, expected_revision=3)
    reopened = ProjectStore(tmp_path / "projects")
    output = tmp_path / "export"
    export_project(reopened, project.id, output, expected_revision=4)

    rendered, rate = sf.read(output / "dialogue.wav", dtype="float32")
    original = reopened.source_samples(project.id, headset.id)
    donor = reopened.source_samples(project.id, lapel.id)
    assert rate == 48_000 and len(rendered) == len(original) == 960_000
    np.testing.assert_array_equal(rendered[:repair.start_frame], original[:repair.start_frame])
    np.testing.assert_array_equal(rendered[repair.end_frame:], original[repair.end_frame:])
    # Independently reconstruct actual donor samples, including both former lost edges.
    clock = donor_source.alignment
    positions = np.arange(816_720, 839_280) * (1 + clock.drift_ppm / 1e6)
    positions += clock.offset_seconds * rate
    expected = np.interp(positions, np.arange(len(donor)), donor)
    expected *= clock.polarity * 10 ** (repair.gain_db / 20)
    np.testing.assert_allclose(rendered[816_720:839_280], expected, atol=1e-7, rtol=1e-6)
    assert np.sqrt(np.mean(rendered[816_720:816_960] ** 2)) > 0.001
    assert np.sqrt(np.mean(rendered[839_040:839_280] ** 2)) > 0.001
    provenance = json.loads((output / "source-map.json").read_text())
    assert provenance["output"]["frames"] == 960_000
    assert any(
        len(span["contributors"]) == 2
        and {item["source_id"] for item in span["contributors"]} == {headset.id, lapel.id}
        for span in provenance["spans"]
    )
