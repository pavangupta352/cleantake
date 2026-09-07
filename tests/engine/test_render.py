import numpy as np
import pytest

from cleantake.engine import (
    Alignment,
    CandidateTrack,
    RepairProposal,
    contributor_spans,
    render_range,
)


def setup():
    primary = np.full(12, 0.1)
    donor = CandidateTrack("backup", np.full(12, 0.7), Alignment(status="aligned", confidence=1))
    repair = RepairProposal(4, 10, "manual", "backup", 1, "Chosen", status="accepted", fade_ms=2)
    return primary, [donor], [repair]


def test_accepted_audio_and_two_linear_seams_have_literal_samples():
    primary, donors, repairs = setup()
    actual = render_range(primary, donors, repairs, 0, 12, 1000)
    np.testing.assert_allclose(actual, [0.1, 0.1, 0.1, 0.1, 0.3, 0.5, 0.7, 0.7, 0.5, 0.3, 0.1, 0.1])
    np.testing.assert_array_equal(actual[:4], primary[:4])
    np.testing.assert_array_equal(actual[10:], primary[10:])
    np.testing.assert_array_equal(primary, np.full(12, 0.1))


def test_subranges_exactly_agree_at_every_repair_and_fade_boundary():
    primary, donors, repairs = setup()
    entire = render_range(primary, donors, repairs, 0, 12, 1000)
    chunks = np.concatenate(
        [
            render_range(primary, donors, repairs, a, b, 1000)
            for a, b in [(0, 3), (3, 5), (5, 6), (6, 9), (9, 12)]
        ]
    )
    np.testing.assert_array_equal(chunks, entire)


@pytest.mark.parametrize("status", ["proposed", "rejected", "unresolved"])
def test_unaccepted_edits_retain_original(status):
    primary, donors, repairs = setup()
    repairs[0].status = status
    np.testing.assert_array_equal(render_range(primary, donors, repairs, 0, 12, 1000), primary)


def test_clock_polarity_and_gain_apply_to_actual_recorded_samples():
    primary = np.zeros(8)
    donor = CandidateTrack(
        "backup",
        np.array([0.0, -0.1, -0.2, -0.3, -0.4, -0.5, -0.6, -0.7]),
        Alignment(offset_seconds=0.001, polarity=-1, status="manual"),
    )
    repair = RepairProposal(
        2,
        5,
        "manual",
        "backup",
        1,
        "Chosen",
        status="accepted",
        gain_db=-6.020599913279624,
        fade_ms=0,
    )
    np.testing.assert_allclose(
        render_range(primary, [donor], [repair], 0, 8, 1000), [0, 0, 0.15, 0.20, 0.25, 0, 0, 0]
    )


@pytest.mark.parametrize(
    "fault",
    [
        "overlap",
        "outside",
        "unknown",
        "uncovered",
        "uncertain",
        "gain",
        "fade",
        "nonfinite",
        "fractional",
        "clipping",
    ],
)
def test_invalid_accepted_decisions_raise_instead_of_silently_rendering(fault):
    primary, donors, repairs = setup()
    if fault == "overlap":
        repairs.append(RepairProposal(8, 11, "manual", "backup", 1, "", status="accepted"))
    elif fault == "outside":
        repairs[0].end_frame = 13
    elif fault == "unknown":
        repairs[0].source_id = "missing"
    elif fault == "uncovered":
        donors[0] = CandidateTrack("backup", np.zeros(5), Alignment(status="aligned"))
    elif fault == "uncertain":
        donors[0] = CandidateTrack("backup", np.zeros(12), Alignment())
    elif fault == "gain":
        repairs[0].gain_db = 100
    elif fault == "fade":
        repairs[0].fade_ms = -1
    elif fault == "nonfinite":
        repairs[0].gain_db = float("nan")
    elif fault == "fractional":
        repairs[0].start_frame = 4.5
    elif fault == "clipping":
        repairs[0].gain_db = 6
    with pytest.raises(ValueError):
        render_range(primary, donors, repairs, 0, 12, 1000)


def test_source_map_records_both_contributors_and_original_clock_ranges():
    primary, donors, repairs = setup()
    spans = contributor_spans(primary, donors, repairs, 0, 12, 1000, primary_source_id="main")
    assert [(s["start_frame"], s["end_frame"]) for s in spans] == [
        (0, 4),
        (4, 6),
        (6, 8),
        (8, 10),
        (10, 12),
    ]
    assert [c["source_id"] for c in spans[1]["contributors"]] == ["main", "backup"]
    assert [c["source_id"] for c in spans[2]["contributors"]] == ["backup"]
    assert spans[1]["contributors"][1]["source_start_frame"] == 4
    assert spans[1]["contributors"][1]["source_end_frame"] == 6
    assert spans[1]["contributors"][1]["weight"]["start"] == pytest.approx(1 / 3)
    assert spans[1]["contributors"][0]["weight"]["start"] == pytest.approx(2 / 3)
