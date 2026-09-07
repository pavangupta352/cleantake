"""Validated records for durable CleanTake projects.

Internal records deliberately keep project-relative media locations.  Use
``project_to_public`` at an HTTP/UI boundary: its DTO types have no path fields.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from numbers import Integral
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1
WORKING_SAMPLE_RATE = 48_000

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_id(value: str) -> str:
    """Return a canonical UUID identifier or raise ``ValueError``."""

    if not isinstance(value, str):
        raise ValueError("identifier must be a UUID string")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError("identifier must be a UUID string") from error
    if str(parsed) != value:
        raise ValueError("identifier must use canonical lowercase UUID form")
    return value


def _relative_path(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("file location must be a safe project-relative path")
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or "\x00" in value
        or ":" in path.parts[0]
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("file location must be a safe project-relative path")
    return path.as_posix()


def _finite(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("number must be numeric and finite")
    try:
        numeric = float(value)
    except OverflowError as error:
        raise ValueError("number must be finite") from error
    if not math.isfinite(numeric):
        raise ValueError("number must be finite")
    return numeric


def _strict_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError("value must be an integer")
    return int(value)


def _json_safe(value: Any, *, location: str = "value") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{location} must contain only finite numbers")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _json_safe(item, location=f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{location} keys must be strings")
            _json_safe(item, location=f"{location}.{key}")
        return
    raise ValueError(f"{location} must be JSON safe")


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AlignmentRecord(StrictRecord):
    """Persisted form of :class:`cleantake.engine.Alignment`."""

    offset_seconds: float = 0.0
    drift_ppm: float = 0.0
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    anchors: int = Field(default=0, ge=0)
    residual_ms: float = Field(default=0.0, ge=0.0)
    status: Literal["aligned", "uncertain", "manual", "reference"] = "uncertain"
    polarity: Literal[-1, 1] = 1

    @field_validator("offset_seconds", "drift_ppm", "confidence", "residual_ms", mode="before")
    @classmethod
    def finite_numbers(cls, value: float) -> float:
        return _finite(value)

    @field_validator("anchors", mode="before")
    @classmethod
    def integer_anchors(cls, value: Any) -> int:
        return _strict_int(value)

    @model_validator(mode="after")
    def positive_clock(self) -> AlignmentRecord:
        if 1 + self.drift_ppm / 1_000_000 <= 0:
            raise ValueError("alignment clock must have a positive scale")
        return self


class AudioCacheRecord(StrictRecord):
    """Metadata for a mono float32 working cache and its selected input."""

    path: str
    cache_sha256: str
    sample_rate: Literal[48_000] = WORKING_SAMPLE_RATE
    channels: Literal[1] = 1
    frames: int = Field(ge=1)
    format: Literal["float32le"] = "float32le"
    bytes_per_frame: Literal[4] = 4
    selected_stream: int = Field(ge=0)
    selected_channel: int | None = Field(default=None, ge=0)
    channel_mode: str
    source_sample_rate: int = Field(gt=0)
    source_channels: int = Field(gt=0)
    source_frames: int | None = Field(default=None, gt=0)
    source_duration_seconds: float = Field(gt=0.0)
    codec_name: str
    container_name: str

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        return _relative_path(value)

    @field_validator("cache_sha256")
    @classmethod
    def valid_cache_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("cache_sha256 must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("source_duration_seconds", mode="before")
    @classmethod
    def finite_duration(cls, value: float) -> float:
        return _finite(value)

    @field_validator(
        "frames",
        "selected_stream",
        "selected_channel",
        "source_sample_rate",
        "source_channels",
        "source_frames",
        mode="before",
    )
    @classmethod
    def integer_metadata(cls, value: Any) -> int | None:
        return None if value is None else _strict_int(value)

    @model_validator(mode="after")
    def valid_channel_selection(self) -> AudioCacheRecord:
        expected_mode = (
            "downmix" if self.selected_channel is None else f"channel:{self.selected_channel}"
        )
        if self.channel_mode != expected_mode:
            raise ValueError("channel_mode does not match selected_channel")
        if self.selected_channel is not None and self.selected_channel >= self.source_channels:
            raise ValueError("selected_channel is outside source channel count")
        return self


class SourceRecord(StrictRecord):
    id: str
    name: str = Field(min_length=1, max_length=200)
    original_filename: str = Field(min_length=1, max_length=255)
    original_path: str
    sha256: str
    imported_at: datetime
    audio: AudioCacheRecord
    alignment: AlignmentRecord = Field(default_factory=AlignmentRecord)
    speaker: str | None = Field(default=None, max_length=200)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        return validate_id(value)

    @field_validator("name", "speaker")
    @classmethod
    def trimmed_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        clean = value.strip()
        if not clean:
            raise ValueError("text must not be blank")
        return clean

    @field_validator("original_filename")
    @classmethod
    def filename_only(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
            raise ValueError("original_filename must be a filename, not a path")
        return value

    @field_validator("original_path")
    @classmethod
    def valid_original_path(cls, value: str) -> str:
        return _relative_path(value)

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("imported_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value


class RepairRecord(StrictRecord):
    id: str
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    kind: Literal["dropout", "clipping", "noise", "manual"]
    source_id: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=2_000)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["proposed", "accepted", "rejected", "unresolved"] = "proposed"
    gain_db: float = Field(default=0.0, ge=-24.0, le=24.0)
    fade_ms: float = Field(default=12.0, ge=0.0, le=1_000.0)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        return validate_id(value)

    @field_validator("source_id")
    @classmethod
    def valid_source_id(cls, value: str | None) -> str | None:
        return None if value is None else validate_id(value)

    @field_validator("confidence", "gain_db", "fade_ms", mode="before")
    @classmethod
    def finite_numbers(cls, value: float) -> float:
        return _finite(value)

    @field_validator("start_frame", "end_frame", mode="before")
    @classmethod
    def integer_frames(cls, value: Any) -> int:
        return _strict_int(value)

    @field_validator("alternatives")
    @classmethod
    def valid_alternatives(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _json_safe(value, location="alternatives")
        return value

    @model_validator(mode="after")
    def valid_range_and_acceptance(self) -> RepairRecord:
        if self.end_frame <= self.start_frame:
            raise ValueError("end_frame must be greater than start_frame")
        if self.status == "accepted" and self.source_id is None:
            raise ValueError("accepted repair requires a source_id")
        return self


class ProjectRecord(StrictRecord):
    schema_version: Literal[1] = SCHEMA_VERSION
    id: str
    name: str = Field(min_length=1, max_length=200)
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=0)
    sample_rate: Literal[48_000] = WORKING_SAMPLE_RATE
    primary_source_id: str | None = None
    duration_frames: int = Field(default=0, ge=0)
    sources: list[SourceRecord] = Field(default_factory=list, max_length=4)
    repairs: list[RepairRecord] = Field(default_factory=list)
    transcripts: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: Literal["empty", "ready", "analyzing", "analyzed", "error"] = "empty"
    error: str | None = Field(default=None, max_length=4_000)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        return validate_id(value)

    @field_validator("primary_source_id")
    @classmethod
    def valid_primary_id(cls, value: str | None) -> str | None:
        return None if value is None else validate_id(value)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("name must not be blank")
        return clean

    @field_validator("created_at", "updated_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @field_validator("revision", "duration_frames", mode="before")
    @classmethod
    def integer_counters(cls, value: Any) -> int:
        return _strict_int(value)

    @field_validator("transcripts")
    @classmethod
    def valid_transcripts(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _json_safe(value, location="transcripts")
        return value

    @model_validator(mode="after")
    def coherent_timeline_and_references(self) -> ProjectRecord:
        source_ids = [source.id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source identifiers must be unique")
        repair_ids = [repair.id for repair in self.repairs]
        if len(repair_ids) != len(set(repair_ids)):
            raise ValueError("repair identifiers must be unique")

        if not self.sources:
            if self.primary_source_id is not None or self.duration_frames != 0:
                raise ValueError("empty project cannot have a primary source or duration")
        else:
            if self.primary_source_id not in source_ids:
                raise ValueError("primary_source_id must name a known source")
            primary = next(source for source in self.sources if source.id == self.primary_source_id)
            if self.duration_frames != primary.audio.frames:
                raise ValueError("duration_frames must equal primary source cache frames")

        sources_by_id = {source.id: source for source in self.sources}
        for source in self.sources:
            clock = source.alignment
            scale = 1 + clock.drift_ppm / 1_000_000
            offset = clock.offset_seconds * self.sample_rate
            try:
                coordinates = (
                    offset,
                    self.duration_frames * scale + offset,
                    -offset / scale,
                    (source.audio.frames - 1 - offset) / scale,
                )
            except OverflowError as error:
                raise ValueError("alignment clock exceeds supported frame bounds") from error
            if not all(math.isfinite(value) for value in coordinates):
                raise ValueError("alignment clock exceeds supported frame bounds")

        accepted = []
        for repair in self.repairs:
            if repair.end_frame > self.duration_frames:
                raise ValueError("repair range exceeds primary duration")
            if repair.source_id is not None and repair.source_id not in source_ids:
                raise ValueError("repair source_id must name a known source")
            if repair.status == "accepted" and repair.source_id == self.primary_source_id:
                raise ValueError("accepted repair source cannot be the primary source")
            if repair.status == "accepted":
                donor = sources_by_id[repair.source_id]
                if donor.alignment.status not in {"aligned", "manual", "reference"}:
                    raise ValueError("accepted repair requires verified or manual alignment")
                scale = 1 + donor.alignment.drift_ppm / 1_000_000
                offset = donor.alignment.offset_seconds * self.sample_rate
                first = repair.start_frame * scale + offset
                last = (repair.end_frame - 1) * scale + offset
                if first < 0 or last > donor.audio.frames - 1:
                    raise ValueError("accepted repair exceeds donor coverage")
                accepted.append(repair)
            for alternative in repair.alternatives:
                alternative_id = alternative.get("source_id")
                if alternative_id is not None and alternative_id not in source_ids:
                    raise ValueError("repair alternative must name a known source")
        accepted.sort(key=lambda repair: repair.start_frame)
        if any(
            left.end_frame > right.start_frame
            for left, right in zip(accepted, accepted[1:], strict=False)
        ):
            raise ValueError("accepted repairs overlap")
        return self


class PublicAudioRecord(StrictRecord):
    cache_sha256: str
    sample_rate: int
    channels: int
    frames: int
    format: str
    selected_stream: int
    selected_channel: int | None
    channel_mode: str
    source_sample_rate: int
    source_channels: int
    source_frames: int | None
    source_duration_seconds: float
    codec_name: str
    container_name: str


class PublicSourceRecord(StrictRecord):
    id: str
    name: str
    original_filename: str
    sha256: str
    imported_at: datetime
    audio: PublicAudioRecord
    alignment: AlignmentRecord
    speaker: str | None


class PublicProjectRecord(StrictRecord):
    schema_version: int
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    revision: int
    sample_rate: int
    primary_source_id: str | None
    duration_frames: int
    sources: list[PublicSourceRecord]
    repairs: list[RepairRecord]
    transcripts: list[dict[str, Any]]
    warnings: list[str]
    status: str
    error: str | None


class ProjectSummary(StrictRecord):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    revision: int
    status: str
    duration_frames: int
    source_count: int
    repair_count: int


def project_to_public(project: ProjectRecord) -> PublicProjectRecord:
    """Create the path-free representation safe for API and UI serialization."""

    sources = []
    for source in project.sources:
        audio_payload = source.audio.model_dump(exclude={"path", "bytes_per_frame"})
        sources.append(
            PublicSourceRecord(
                **source.model_dump(exclude={"original_path", "audio"}),
                audio=PublicAudioRecord(**audio_payload),
            )
        )
    return PublicProjectRecord(
        **project.model_dump(exclude={"sources"}),
        sources=sources,
    )


def project_summary(project: ProjectRecord) -> ProjectSummary:
    """Return the compact project shelf representation."""

    return ProjectSummary(
        id=project.id,
        name=project.name,
        created_at=project.created_at,
        updated_at=project.updated_at,
        revision=project.revision,
        status=project.status,
        duration_frames=project.duration_frames,
        source_count=len(project.sources),
        repair_count=len(project.repairs),
    )


__all__ = [
    "AlignmentRecord",
    "AudioCacheRecord",
    "ProjectRecord",
    "ProjectSummary",
    "PublicAudioRecord",
    "PublicProjectRecord",
    "PublicSourceRecord",
    "RepairRecord",
    "SCHEMA_VERSION",
    "SourceRecord",
    "WORKING_SAMPLE_RATE",
    "project_summary",
    "project_to_public",
    "validate_id",
]
