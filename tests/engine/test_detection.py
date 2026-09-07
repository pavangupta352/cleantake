import numpy as np
from test_alignment import speech

from cleantake.engine import Alignment, CandidateTrack, find_repairs


def track(data, status="aligned", name="backup"):
    return CandidateTrack(name, data, Alignment(confidence=1, anchors=9, status=status))


def test_missing_signal_uses_intact_recording_and_contextual_gain():
    clean = speech(6)
    primary = clean.copy()
    primary[16000:20000] = 0
    proposals = find_repairs(primary, [track(clean * 0.5)], 8000)
    repairs = [r for r in proposals if r.source_id == "backup"]
    assert len(repairs) == 1
    repair = repairs[0]
    assert (repair.start_frame, repair.end_frame, repair.kind) == (16000, 20000, "dropout")
    assert repair.status == "proposed"
    assert repair.confidence >= 0.8
    assert abs(repair.gain_db - 6.0206) < 0.1


def test_clean_primary_shared_silence_and_natural_quiet_do_not_propose():
    primary = speech(6)
    primary[8000:16000] = 0
    primary[24000:32000] *= 0.0001
    assert find_repairs(primary, [track(primary * 0.5)], 8000) == []


def test_clipped_primary_needs_unclipped_donor_and_retains_unresolved():
    clean = speech(6)
    primary = clean.copy()
    primary[16000:20000] = np.clip(clean[16000:20000] * 8, -0.25, 0.25)
    proposals = find_repairs(primary, [track(clean)], 8000)
    assert any(p.kind == "clipping" and p.source_id == "backup" for p in proposals)
    damaged = find_repairs(primary, [track(primary)], 8000)
    assert damaged
    assert all(p.source_id is None and p.status == "unresolved" for p in damaged)


def test_uncertain_or_absent_donors_never_supply_repairs():
    clean = speech(6)
    primary = clean.copy()
    primary[16000:20000] = 0
    assert not any(p.source_id for p in find_repairs(primary, [track(clean, "uncertain")], 8000))
    assert not any(p.source_id for p in find_repairs(primary, [track(clean[:8000])], 8000))


def test_unrelated_sound_in_silence_does_not_masquerade_as_recovery():
    primary = speech(6)
    primary[16000:20000] = 0
    proposals = find_repairs(primary, [track(speech(6, seed=999), "manual")], 8000)
    assert not any(p.source_id for p in proposals)


def test_damaged_alternative_cannot_hide_inside_long_interval():
    clean = speech(6)
    primary = clean.copy()
    primary[16000:24000] = 0
    damaged = clean.copy()
    damaged[19000:22000] = 0
    proposals = find_repairs(primary, [track(damaged), track(clean, name="intact")], 8000)
    assert any(p.source_id == "intact" for p in proposals)
    assert not any(p.source_id == "backup" for p in proposals)


def test_proposal_does_not_raise_weak_alignment_confidence():
    clean = speech(6)
    primary = clean.copy()
    primary[16000:20000] = 0
    donor = CandidateTrack("backup", clean, Alignment(confidence=0.2, status="aligned"))
    proposals = find_repairs(primary, [donor], 8000)
    assert proposals
    assert all(proposal.confidence <= 0.2 for proposal in proposals)


def test_quiet_intact_microphone_is_evaluated_after_bounded_level_match():
    clean = speech(6)
    primary = clean.copy()
    primary[16000:20000] = 0
    proposals = find_repairs(primary, [track(clean * 0.2)], 8000)
    assert len(proposals) == 1
    assert proposals[0].source_id == "backup"
    assert abs(proposals[0].gain_db - 13.9794) < 0.1


def test_licensed_distinct_microphones_propose_and_render_injected_missing_speech():
    from pathlib import Path

    import soundfile as sf

    from cleantake.engine import estimate_alignment, render_range

    base = Path(__file__).resolve().parent / "data"
    clean, rate = sf.read(base / "ES2004a_0324-0344_Headset-0.wav")
    donor, _ = sf.read(base / "ES2004a_0324-0344_Lapel-0.wav")
    broken = clean.copy()
    # Original meeting time 341.0–341.5 s; independently chosen voiced passage.
    broken[272000:280000] = 0
    alignment = estimate_alignment(broken, donor, rate)
    candidate = CandidateTrack("lapel", donor, alignment)
    assert alignment.status == "aligned"
    assert find_repairs(clean, [candidate], rate) == []
    proposals = find_repairs(broken, [candidate], rate)
    assert len(proposals) == 1
    repair = proposals[0]
    assert (repair.start_frame, repair.end_frame, repair.source_id) == (272000, 280000, "lapel")
    assert repair.status == "proposed"
    repair.status = "accepted"
    result = render_range(broken, [candidate], proposals, 0, len(broken), rate)
    np.testing.assert_array_equal(result[:272000], broken[:272000])
    np.testing.assert_array_equal(result[280000:], broken[280000:])
    assert np.sqrt(np.mean(result[273000:279000] ** 2)) > 0.005
    assert np.isfinite(result).all()
    assert np.max(np.abs(result)) <= 1


def test_shared_silence_with_backup_room_noise_is_not_speech_recovery():
    from cleantake.engine import estimate_alignment

    reference = speech(6)
    reference[16000:20000] = 0
    donor = reference * 0.5 + np.random.default_rng(334).normal(0, 0.003, len(reference))
    alignment = estimate_alignment(reference, donor, 8000)
    proposals = find_repairs(reference, [CandidateTrack("backup", donor, alignment)], 8000)
    assert not [p for p in proposals if p.source_id is not None], proposals


def test_room_noise_rejection_is_relative_to_background_across_recording_levels():
    from cleantake.engine import estimate_alignment

    for gain, noise_rms in [(0.2, 0.0005), (0.5, 0.01), (1.0, 0.02)]:
        primary = speech(6)
        primary[16000:20000] = 0
        donor = primary * gain + np.random.default_rng(91).normal(0, noise_rms, len(primary))
        alignment = estimate_alignment(primary, donor, 8000)
        assert alignment.status == "aligned"
        proposals = find_repairs(primary, [CandidateTrack("backup", donor, alignment)], 8000)
        assert not [p for p in proposals if p.source_id], (gain, noise_rms, proposals)


def test_intact_speech_with_room_noise_can_still_rescue_actual_missing_speech():
    from cleantake.engine import estimate_alignment

    clean = speech(6)
    primary = clean.copy()
    primary[16000:20000] = 0
    donor = clean * 0.5 + np.random.default_rng(91).normal(0, 0.003, len(clean))
    alignment = estimate_alignment(primary, donor, 8000)
    proposals = find_repairs(primary, [CandidateTrack("backup", donor, alignment)], 8000)
    assert len(proposals) == 1
    assert proposals[0].source_id == "backup"
    assert (proposals[0].start_frame, proposals[0].end_frame) == (16000, 20000)


def test_dropout_boundaries_retain_samples_between_the_analysis_grid_and_gap_edges():
    """A valid off-grid zero run is recovered through its actual silent samples."""
    clean = speech(6)
    primary = clean.copy()
    primary[16023:19971] = 0
    proposals = find_repairs(primary, [track(clean)], 8000)
    assert len(proposals) == 1
    assert (proposals[0].start_frame, proposals[0].end_frame) == (16023, 19971)


def test_donor_damage_in_partial_edge_window_cannot_supply_the_gap():
    clean = speech(6)
    primary = clean.copy()
    primary[16023:19971] = 0
    donor = clean.copy()
    donor[19950:19971] = 1
    assert find_repairs(primary, [track(donor)], 8000) == []


def test_refined_dropout_does_not_overlap_neighboring_overload_repairs():
    from cleantake.engine import render_range

    clean = speech(6)
    primary = clean.copy()
    primary[15840:16080] = 0.25
    primary[16080:19920] = 0
    primary[19920:20160] = 0.25
    candidate = track(clean)
    proposals = find_repairs(primary, [candidate], 8000)
    assert any(proposal.kind == "dropout" for proposal in proposals)
    assert any(proposal.kind == "clipping" for proposal in proposals)
    assert all(
        left.end_frame <= right.start_frame
        for left, right in zip(proposals, proposals[1:], strict=False)
    )
    for proposal in proposals:
        proposal.status = "accepted"
    rendered = render_range(primary, [candidate], proposals, 0, len(primary), 8000)
    assert len(rendered) == len(primary)
    np.testing.assert_array_equal(rendered[:15840], primary[:15840])
    np.testing.assert_array_equal(rendered[20160:], primary[20160:])
