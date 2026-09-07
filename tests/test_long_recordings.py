"""Known clock injection and bounded disk-backed recording regressions."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from cleantake.engine import Alignment, CandidateTrack, RepairProposal, render_range

SPEC = importlib.util.spec_from_file_location(
    "evaluation_runner", Path(__file__).resolve().parents[1] / "eval/run.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_evaluation_injection_places_known_samples_on_the_declared_clock():
    samples = np.array([0.1, 0.2, 0.3, 0.4])
    positive = runner.inject_clock(samples, 10, offset_seconds=0.2, polarity=-1)
    np.testing.assert_allclose(positive[:6], [0, 0, -0.1, -0.2, -0.3, -0.4])
    negative = runner.inject_clock(samples, 10, offset_seconds=-0.1)
    np.testing.assert_allclose(negative[:3], samples[1:])
    # This large test-only scale makes the inverse transformation unambiguous.
    expanded = runner.inject_clock(samples, 10, drift_ppm=1_000_000)
    np.testing.assert_allclose(expanded[::2][:4], samples)


def test_independent_provenance_reader_obeys_endpoint_weights_and_fractional_clock():
    spans = [
        {
            "start_frame": 0,
            "end_frame": 3,
            "contributors": [
                {
                    "source_id": "donor",
                    "alignment": {"offset_seconds": 0.05, "drift_ppm": 0, "polarity": -1},
                    "weight": {"start": 0.25, "end": 0.75},
                    "gain_db": 0,
                }
            ],
        }
    ]
    actual = runner.reconstruct(spans, {"donor": np.array([0, 0.2, 0.4, 0.6])}, 10, 3)
    np.testing.assert_allclose(actual, [-0.025, -0.15, -0.375], atol=1e-12)


@pytest.mark.slow
def test_five_minute_disk_backed_render_has_identical_seams_and_unchanged_content(tmp_path):
    """Chunk-relative fades or edits outside the declared interval would fail this contract."""
    rate, frames = 8_000, 8_000 * 300
    primary_path, donor_path = tmp_path / "primary.f32", tmp_path / "donor.f32"
    primary = np.memmap(primary_path, dtype="float32", mode="w+", shape=(frames,))
    donor = np.memmap(donor_path, dtype="float32", mode="w+", shape=(frames,))
    rng = np.random.default_rng(802)
    for start in range(0, frames, rate):
        block = rng.uniform(-0.2, 0.2, rate).astype("float32")
        primary[start : start + rate] = block
        donor[start : start + rate] = block * 0.5
    primary.flush()
    donor.flush()
    del primary, donor
    primary = np.memmap(primary_path, dtype="float32", mode="r")
    donor = np.memmap(donor_path, dtype="float32", mode="r")
    candidates = [CandidateTrack("backup", donor, Alignment(status="manual"))]
    repair = RepairProposal(
        149 * rate, 151 * rate, "manual", "backup", 1, "Known interval", status="accepted"
    )
    whole = render_range(primary, candidates, [repair], 148 * rate, 152 * rate, rate)
    chunks = [
        render_range(primary, candidates, [repair], start, min(start + 997, 152 * rate), rate)
        for start in range(148 * rate, 152 * rate, 997)
    ]
    np.testing.assert_array_equal(np.concatenate(chunks), whole)
    np.testing.assert_array_equal(whole[:rate], primary[148 * rate : 149 * rate])
    np.testing.assert_array_equal(whole[3 * rate :], primary[151 * rate : 152 * rate])
    assert not primary.flags.writeable and not donor.flags.writeable
