from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cleantake.models import (
    AlignmentRecord,
    AudioCacheRecord,
    ProjectRecord,
    RepairRecord,
    SourceRecord,
    project_to_public,
)


def _now() -> datetime:
    return datetime(2026, 9, 8, tzinfo=UTC)


def _source(source_id: str, *, frames: int = 48_000) -> SourceRecord:
    return SourceRecord(
        id=source_id,
        name="Primary",
        original_filename="take.wav",
        original_path=f"originals/{source_id}/media",
        sha256="a" * 64,
        imported_at=_now(),
        audio=AudioCacheRecord(
            path=f"cache/{source_id}.f32le",
            cache_sha256="b" * 64,
            sample_rate=48_000,
            channels=1,
            frames=frames,
            format="float32le",
            bytes_per_frame=4,
            selected_stream=0,
            selected_channel=None,
            channel_mode="downmix",
            source_sample_rate=44_100,
            source_channels=2,
            source_frames=44_100,
            source_duration_seconds=1.0,
            codec_name="pcm_s16le",
            container_name="wav",
        ),
        alignment=AlignmentRecord(status="reference", confidence=1.0, anchors=1),
    )


def test_project_validation_rejects_nonfinite_or_unknown_repair_state() -> None:
    """A NaN confidence or unknown donor must never enter persisted state."""

    source_id = "18f92591-e72a-49ea-a17e-f920da100ec5"
    project_id = "c3338282-18f6-4187-905a-0751d239060c"
    repair_id = "e596ed91-9976-4895-ad18-8fd638dd50f3"
    common = dict(
        schema_version=1,
        id=project_id,
        name="Session",
        created_at=_now(),
        updated_at=_now(),
        revision=0,
        sample_rate=48_000,
        primary_source_id=source_id,
        duration_frames=48_000,
        sources=[_source(source_id)],
        transcripts=[],
        warnings=[],
        status="ready",
    )

    with pytest.raises(ValidationError, match="finite"):
        ProjectRecord(
            **common,
            repairs=[
                RepairRecord(
                    id=repair_id,
                    start_frame=100,
                    end_frame=200,
                    kind="dropout",
                    source_id=source_id,
                    confidence=math.nan,
                    reason="evidence",
                )
            ],
        )

    with pytest.raises(ValidationError, match="known source"):
        ProjectRecord(
            **common,
            repairs=[
                RepairRecord(
                    id=repair_id,
                    start_frame=100,
                    end_frame=200,
                    kind="manual",
                    source_id="39ca6049-df13-441e-8866-f1f2c2455cf5",
                    confidence=0.5,
                    reason="manual",
                )
            ],
        )


def test_project_validation_rejects_repair_outside_primary_duration() -> None:
    """A repair ending after the primary clock must fail validation."""

    source_id = "18f92591-e72a-49ea-a17e-f920da100ec5"
    with pytest.raises(ValidationError, match="duration"):
        ProjectRecord(
            schema_version=1,
            id="c3338282-18f6-4187-905a-0751d239060c",
            name="Session",
            created_at=_now(),
            updated_at=_now(),
            revision=0,
            primary_source_id=source_id,
            duration_frames=1_000,
            sources=[_source(source_id, frames=1_000)],
            repairs=[
                RepairRecord(
                    id="e596ed91-9976-4895-ad18-8fd638dd50f3",
                    start_frame=900,
                    end_frame=1_001,
                    kind="manual",
                    source_id=source_id,
                    confidence=1.0,
                    reason="manual",
                )
            ],
        )


def test_public_project_omits_owned_file_locations_and_retains_transcripts() -> None:
    """API serialization must not disclose internal original or cache paths."""

    source_id = "18f92591-e72a-49ea-a17e-f920da100ec5"
    project = ProjectRecord(
        schema_version=1,
        id="c3338282-18f6-4187-905a-0751d239060c",
        name="Session",
        created_at=_now(),
        updated_at=_now(),
        revision=0,
        primary_source_id=source_id,
        duration_frames=48_000,
        sources=[_source(source_id)],
        repairs=[],
        transcripts=[{"format": "json", "turns": [{"text": "literal <b>text</b>"}]}],
        warnings=[],
        status="ready",
    )

    payload = project_to_public(project).model_dump(mode="json")

    assert payload["sources"][0]["audio"]["frames"] == 48_000
    assert payload["sources"][0]["audio"]["cache_sha256"] == "b" * 64
    assert payload["transcripts"][0]["turns"][0]["text"] == "literal <b>text</b>"
    assert "original_path" not in payload["sources"][0]
    assert "path" not in payload["sources"][0]["audio"]


@pytest.mark.parametrize("confidence", [None, True, "loud", [], float("inf")])
def test_numeric_validation_returns_structured_errors_for_malformed_values(
    confidence: object,
) -> None:
    """Untrusted malformed numbers must become Pydantic errors, never raw TypeErrors."""

    with pytest.raises(ValidationError):
        RepairRecord(
            id="e596ed91-9976-4895-ad18-8fd638dd50f3",
            start_frame=100,
            end_frame=200,
            kind="manual",
            source_id=None,
            confidence=confidence,
            reason="manual",
        )


@pytest.mark.parametrize("start_frame", [True, "100", 1.5, None])
def test_frame_validation_rejects_coercible_non_integer_values(start_frame: object) -> None:
    """Boolean, string, fractional and missing frame values must not be coerced."""

    with pytest.raises(ValidationError, match="integer"):
        RepairRecord(
            id="e596ed91-9976-4895-ad18-8fd638dd50f3",
            start_frame=start_frame,
            end_frame=200,
            kind="manual",
            source_id=None,
            confidence=0.5,
            reason="manual",
        )


def test_other_persisted_integer_fields_reject_boolean_and_string_coercion() -> None:
    """Manifest counters and media selections retain exact integer types."""

    with pytest.raises(ValidationError, match="integer"):
        AlignmentRecord(anchors=True)

    valid_audio = _source("18f92591-e72a-49ea-a17e-f920da100ec5").audio
    with pytest.raises(ValidationError, match="integer"):
        AudioCacheRecord(**valid_audio.model_dump(exclude={"selected_stream"}), selected_stream="0")

    source_id = "18f92591-e72a-49ea-a17e-f920da100ec5"
    with pytest.raises(ValidationError, match="integer"):
        ProjectRecord(
            schema_version=1,
            id="c3338282-18f6-4187-905a-0751d239060c",
            name="Session",
            created_at=_now(),
            updated_at=_now(),
            revision="0",
            primary_source_id=source_id,
            duration_frames=48_000,
            sources=[_source(source_id)],
            status="ready",
        )


@pytest.mark.parametrize(
    "unsafe_path",
    ["../outside", "cache/../outside", "/absolute", r"C:\\outside\\media", r"cache\\outside"],
)
def test_internal_locations_use_normalized_portable_relative_paths(unsafe_path: str) -> None:
    """Persisted locations must remain relative on POSIX and Windows readers."""

    with pytest.raises(ValidationError, match="relative path"):
        AudioCacheRecord(
            path=unsafe_path,
            cache_sha256="b" * 64,
            frames=100,
            selected_stream=0,
            channel_mode="downmix",
            source_sample_rate=48_000,
            source_channels=1,
            source_frames=100,
            source_duration_seconds=100 / 48_000,
            codec_name="pcm_f32le",
            container_name="wav",
        )


def test_original_filename_rejects_windows_or_posix_path_components() -> None:
    """A display filename cannot smuggle path syntax to another platform."""

    source = _source("18f92591-e72a-49ea-a17e-f920da100ec5")
    for filename in ("../take.wav", r"folder\\take.wav", "/tmp/take.wav"):
        with pytest.raises(ValidationError, match="filename"):
            SourceRecord(
                **source.model_dump(exclude={"original_filename"}), original_filename=filename
            )


@pytest.mark.parametrize("drift_ppm", [-1_000_000.0, -1_000_001.0])
def test_alignment_rejects_nonpositive_affine_clock(drift_ppm: float) -> None:
    """A saved source clock must be usable by alignment previews."""

    with pytest.raises(ValidationError, match="clock"):
        AlignmentRecord(drift_ppm=drift_ppm, status="manual")


def test_manual_clock_can_exceed_estimator_search_range() -> None:
    """Manual alignment retains the renderer's positive affine-clock contract."""

    clock = AlignmentRecord(drift_ppm=100_000.0, status="manual")
    assert clock.drift_ppm == 100_000.0


@pytest.mark.parametrize(
    "alignment,frames",
    [
        (AlignmentRecord(drift_ppm=1e308, status="manual"), 2_000_000),
        (AlignmentRecord(offset_seconds=1e300, drift_ppm=-999_999.9999999999), 48_000),
    ],
)
def test_project_rejects_overflowing_forward_or_inverse_clock_bounds(
    alignment: AlignmentRecord,
    frames: int,
) -> None:
    """Finite input fields must still map to finite renderer and preview coordinates."""

    primary_id = "18f92591-e72a-49ea-a17e-f920da100ec5"
    donor_id = "39ca6049-df13-441e-8866-f1f2c2455cf5"
    primary = _source(primary_id, frames=frames)
    donor = SourceRecord(**_source(donor_id).model_dump(exclude={"alignment"}), alignment=alignment)
    with pytest.raises(ValidationError, match="clock"):
        ProjectRecord(
            id="c3338282-18f6-4187-905a-0751d239060c",
            name="Clock bounds",
            created_at=_now(),
            updated_at=_now(),
            revision=0,
            primary_source_id=primary_id,
            duration_frames=frames,
            sources=[primary, donor],
        )
