"""Faults are injected independently of the production clock sampler."""

import numpy as np
import pytest
from scipy.signal import butter, sosfilt

from cleantake.engine import Alignment, estimate_alignment, sample_aligned


def speech(seconds=12, rate=8000, seed=19):
    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    t = np.arange(n) / rate
    filtered = sosfilt(
        butter(3, [160, 2400], fs=rate, btype="bandpass", output="sos"), rng.normal(size=n)
    )
    return filtered * (0.08 + 0.12 * np.sin(t * 3.71) ** 2)  # non-periodic PCM


@pytest.mark.parametrize(
    "offset,ppm,polarity,gain",
    [
        (0.375, 0, 1, 0.4),
        (-0.220, 0, 1, 1.7),
        (0.375, 120, -1, 0.6),
    ],
)
def test_injected_clock_transform_is_recovered(offset, ppm, polarity, gain):
    rate = 8000
    ref = speech(28)
    # Candidate clock t_c = t_r * scale + offset; inverse constructs the recording.
    ctime = np.arange(len(ref) + 4000) / rate
    donor = (
        np.interp(
            (ctime - offset) / (1 + ppm / 1e6), np.arange(len(ref)) / rate, ref, left=0, right=0
        )
        * gain
        * polarity
    )
    result = estimate_alignment(ref, donor, rate)
    assert result.status == "aligned", result
    assert abs(result.offset_seconds - offset) < 0.002
    assert abs(result.drift_ppm - ppm) < 20
    assert result.residual_ms < 3
    assert result.polarity == polarity
    assert result.anchors >= 3


def test_partial_coverage_is_a_valid_negative_offset():
    ref = speech(20)
    result = estimate_alignment(ref, ref[32000:120000] * 0.7, 8000)
    assert result.status == "aligned", result
    assert abs(result.offset_seconds + 4) < 0.002


@pytest.mark.parametrize("case", ["silent", "unrelated", "tone", "too_short"])
def test_no_evidence_or_ambiguous_evidence_stays_uncertain(case):
    ref = speech(5)
    donor = {
        "silent": np.zeros_like(ref),
        "unrelated": speech(5, seed=37),
        "tone": np.sin(np.arange(len(ref)) * 0.2),
        "too_short": ref[:400],
    }[case]
    if case == "tone":
        ref = donor.copy()
    result = estimate_alignment(ref, donor, 8000)
    assert result.status == "uncertain", result
    assert np.isfinite(result.confidence)


def test_sampling_clock_polarity_and_uncovered_frames_are_literal():
    donor = np.array([0.0, 0.2, 0.4, 0.6, 0.8])
    aligned = sample_aligned(
        donor, 0, 7, 10, Alignment(offset_seconds=-0.1, drift_ppm=0, polarity=-1)
    )
    np.testing.assert_allclose(aligned, [0, 0, -0.2, -0.4, -0.6, -0.8, 0])
    fractional = sample_aligned(donor, 0, 2, 10, Alignment(offset_seconds=0.05))
    np.testing.assert_allclose(fractional, [0.1, 0.3])


def test_disk_backed_inputs_remain_immutable(tmp_path):
    data = speech(4)
    path = tmp_path / "pcm.f32"
    data.astype("float32").tofile(path)
    ref = np.memmap(path, dtype="float32", mode="r")
    result = estimate_alignment(ref, ref, 8000)
    assert result.status == "aligned"
    np.testing.assert_array_equal(ref, data.astype("float32"))


def test_sparse_speech_activity_supplies_anchors_between_regular_grid_points():
    ref = np.zeros(8000 * 30)
    voiced = speech(0.9)
    for start in [8000, 80000, 168000]:
        ref[start : start + 7200] = voiced
    # Unique amplitude-independent content in each bout prevents repeated-take ambiguity.
    ref[80000:87200] = speech(0.9, seed=24)
    ref[168000:175200] = speech(0.9, seed=25)
    donor = np.pad(ref, (3000, 0))
    result = estimate_alignment(ref, donor, 8000)
    assert result.status == "aligned", result
    assert abs(result.offset_seconds - 0.375) < 0.002


def test_licensed_development_headset_and_lapel_align_with_acoustic_tolerance():
    from pathlib import Path

    import soundfile as sf

    base = Path(__file__).resolve().parent / "data"
    ref_path = base / "ES2004a_0324-0344_Headset-0.wav"
    donor_path = base / "ES2004a_0324-0344_Lapel-0.wav"
    ref, rate = sf.read(ref_path)
    donor, _ = sf.read(donor_path)
    alignment = estimate_alignment(ref, donor, rate)
    assert alignment.status == "aligned", alignment
    assert (
        abs(alignment.offset_seconds) < 0.02
    )  # Same published recording clock; acoustic path differs.
    assert alignment.residual_ms < 3


def test_exact_integer_sampling_does_not_read_unused_neighbor():
    donor = np.array([0.1, 0.2, float("nan")])
    np.testing.assert_array_equal(sample_aligned(donor, 0, 2, 48000, Alignment()), [0.1, 0.2])


def test_fractional_drift_sampling_uses_reference_clock():
    donor = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
    result = sample_aligned(donor, 1, 4, 10, Alignment(drift_ppm=100000))
    np.testing.assert_allclose(result, [0.11, 0.22, 0.33])


def test_working_48khz_offset_and_drift_residual():
    rate = 48000
    ref = speech(15, rate=rate)
    t = np.arange(len(ref)) / rate
    candidate = np.interp((t - 0.375) / 1.00012, t, ref, left=0, right=0)
    result = estimate_alignment(ref, candidate, rate)
    assert result.status == "aligned", result
    assert abs(result.offset_seconds - 0.375) < 0.002
    assert abs(result.drift_ppm - 120) < 25
    assert result.residual_ms < 3


def test_identical_recordings_do_not_lose_edge_coverage_to_fit_roundoff():
    from cleantake.engine import CandidateTrack, RepairProposal, render_range

    ref = np.random.default_rng(1).normal(0, 0.1, 48000 * 4)
    alignment = estimate_alignment(ref, ref.copy(), 48000)
    repair = RepairProposal(
        0, len(ref), "manual", "backup", 1, "Full coverage", status="accepted", fade_ms=0
    )
    actual = render_range(
        ref, [CandidateTrack("backup", ref, alignment)], [repair], 0, len(ref), 48000
    )
    np.testing.assert_array_equal(actual, ref)


def test_detected_piecewise_clock_cannot_be_globally_verified():
    rate = 8000
    reference = speech(40)
    donor = reference.copy()
    donor[30 * rate :] = np.pad(reference[30 * rate : -800], (800, 0))
    actual = estimate_alignment(reference, donor, rate)
    assert actual.status == "uncertain", actual


def test_quiet_late_speech_cannot_hide_a_clock_cut_behind_loud_early_speech():
    rate = 8000
    reference = speech(80)
    reference[20 * rate :] *= 0.08
    donor = reference.copy()
    donor[20 * rate :] = np.pad(reference[20 * rate : -800], (800, 0))
    actual = estimate_alignment(reference, donor, rate)
    assert actual.status == "uncertain", actual


def test_quiet_late_speech_with_one_valid_clock_remains_aligned():
    rate = 8000
    reference = speech(80)
    reference[20 * rate :] *= 0.08
    candidate_times = np.arange(len(reference) + 4000) / rate
    donor = np.interp(
        (candidate_times - 0.375) / 1.00012,
        np.arange(len(reference)) / rate,
        reference,
        left=0,
        right=0,
    )
    actual = estimate_alignment(reference, donor, rate)
    assert actual.status == "aligned", actual
    assert abs(actual.offset_seconds - 0.375) < 0.002
    assert abs(actual.drift_ppm - 120) < 20


def test_noisy_coherent_tail_clock_cut_is_not_explained_away_as_weak_matches():
    reference = speech(40)
    donor = reference.copy()
    donor[240000:] = np.pad(reference[240000:-800], (800, 0))
    donor += np.random.default_rng(619).normal(0, 0.10, len(donor))
    actual = estimate_alignment(reference, donor, 8000)
    assert actual.status == "uncertain", actual
