"""Bounded, argument-safe media inspection and mono cache decoding."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from cleantake.runtime import RuntimeDependencyError, media_binary, subprocess_options

WORKING_SAMPLE_RATE = 48_000
_COPY_CHUNK_BYTES = 1024 * 1024
# Only self-contained recording containers may provide an imported source.
# Playlists and virtual demuxers can consume bytes outside the hashed original.
_INPUT_OPTIONS = [
    "-format_whitelist",
    "wav,flac,mp3,ogg,mov,matroska,webm,avi,aiff,asf,aac,ac3,eac3,wv,ape,mpeg,mpegts",
    "-protocol_whitelist",
    "file,pipe",
]


class MediaError(ValueError):
    """The selected file cannot produce a valid CleanTake audio cache."""


@dataclass(frozen=True)
class AudioStreamInfo:
    """Actual metadata for one audio stream, addressed by audio-stream ordinal."""

    audio_index: int
    stream_index: int
    codec_name: str
    sample_rate: int
    channels: int
    duration_seconds: float
    frames: int | None


@dataclass(frozen=True)
class MediaProbe:
    container_name: str
    duration_seconds: float
    audio_streams: tuple[AudioStreamInfo, ...]


@dataclass(frozen=True)
class DecodedAudio:
    """Metadata for a completed raw little-endian float32 mono cache."""

    sample_rate: int
    channels: int
    frames: int
    format: str
    bytes_per_frame: int
    selected_stream: int
    selected_channel: int | None
    channel_mode: str
    source_sample_rate: int
    source_channels: int
    source_frames: int | None
    source_duration_seconds: float
    codec_name: str
    container_name: str


def _checked_regular_file(path: Path) -> Path:
    candidate = Path(path)
    try:
        file_stat = candidate.lstat()
    except FileNotFoundError as error:
        raise MediaError(f"audio source does not exist: {candidate.name}") from error
    if stat.S_ISLNK(file_stat.st_mode):
        raise MediaError("audio source must not be a symbolic link")
    if not stat.S_ISREG(file_stat.st_mode):
        raise MediaError("audio source must be a regular file")
    if file_stat.st_size == 0:
        raise MediaError("audio source is empty")
    return candidate


def _binary(name: str) -> str:
    try:
        return media_binary(name)
    except RuntimeDependencyError as error:
        raise MediaError(str(error)) from error


def _positive_float(raw: Any, fallback: float | None = None) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        if fallback is None:
            raise MediaError("audio stream has no usable duration metadata") from None
        return fallback
    if not (value > 0.0):
        if fallback is None:
            raise MediaError("audio stream has no usable duration metadata")
        return fallback
    return value


def _source_frames(stream: dict[str, Any], sample_rate: int, duration: float) -> int | None:
    duration_ts = stream.get("duration_ts")
    time_base = stream.get("time_base")
    if duration_ts is not None and time_base:
        try:
            seconds = int(duration_ts) * float(Fraction(str(time_base)))
            frames = round(seconds * sample_rate)
            return frames if frames > 0 else None
        except (ValueError, ZeroDivisionError):
            pass
    estimated = round(duration * sample_rate)
    return estimated if estimated > 0 else None


def inspect_media(path: Path, *, timeout_seconds: float = 60.0) -> MediaProbe:
    """Inspect real container metadata with FFprobe without following source symlinks."""

    source = _checked_regular_file(path)
    command = [
        _binary("ffprobe"),
        "-v",
        "error",
        *_INPUT_OPTIONS,
        "-show_entries",
        (
            "format=format_name,duration:"
            "stream=index,codec_type,codec_name,sample_rate,channels,duration,duration_ts,time_base"
        ),
        "-of",
        "json",
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            **subprocess_options(),
        )
    except subprocess.TimeoutExpired as error:
        raise MediaError("audio inspection timed out") from error
    except OSError as error:
        raise MediaError("Cannot run ffprobe; reinstall CleanTake or FFmpeg.") from error
    if completed.returncode != 0:
        raise MediaError("file has no readable audio; it may be malformed or unsupported")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise MediaError("audio inspection returned invalid metadata") from error

    format_payload = payload.get("format") or {}
    try:
        container_duration = _positive_float(format_payload.get("duration"))
    except MediaError:
        container_duration = 0.0
    streams: list[AudioStreamInfo] = []
    for raw in payload.get("streams") or []:
        if raw.get("codec_type") != "audio":
            continue
        try:
            sample_rate = int(raw["sample_rate"])
            channels = int(raw["channels"])
            stream_index = int(raw["index"])
        except (KeyError, TypeError, ValueError) as error:
            raise MediaError("audio stream metadata is incomplete") from error
        if sample_rate <= 0 or channels <= 0:
            raise MediaError("audio stream metadata has invalid rates or channels")
        duration = _positive_float(raw.get("duration"), container_duration or None)
        streams.append(
            AudioStreamInfo(
                audio_index=len(streams),
                stream_index=stream_index,
                codec_name=str(raw.get("codec_name") or "unknown"),
                sample_rate=sample_rate,
                channels=channels,
                duration_seconds=duration,
                frames=_source_frames(raw, sample_rate, duration),
            )
        )
    if not streams:
        raise MediaError("file has no readable audio stream")
    duration = container_duration or max(stream.duration_seconds for stream in streams)
    return MediaProbe(
        container_name=str(format_payload.get("format_name") or "unknown"),
        duration_seconds=duration,
        audio_streams=tuple(streams),
    )


def decode_to_cache(
    source_path: Path,
    cache_path: Path,
    *,
    stream: int = 0,
    channel: int | None = None,
    sample_rate: int = WORKING_SAMPLE_RATE,
    timeout_seconds: float = 600.0,
) -> DecodedAudio:
    """Stream one audio selection to an atomically published float32 mono cache.

    ``stream`` is the zero-based audio-stream ordinal. ``channel=None`` records an
    FFmpeg mono downmix; an integer selects that source channel exactly. FFmpeg
    writes directly to disk, so input duration does not determine Python memory.
    """

    if sample_rate != WORKING_SAMPLE_RATE:
        raise MediaError(f"working sample rate must be {WORKING_SAMPLE_RATE}")
    if isinstance(stream, bool) or not isinstance(stream, int) or stream < 0:
        raise MediaError("audio stream must be a non-negative integer")
    if channel is not None and (
        isinstance(channel, bool) or not isinstance(channel, int) or channel < 0
    ):
        raise MediaError("audio channel must be a non-negative integer or null")

    source = _checked_regular_file(source_path)
    probe = inspect_media(source)
    if stream >= len(probe.audio_streams):
        raise MediaError(f"audio stream {stream} does not exist")
    selected = probe.audio_streams[stream]
    if channel is not None and channel >= selected.channels:
        raise MediaError(f"audio channel {channel} does not exist in stream {stream}")

    destination = Path(cache_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise MediaError("audio cache destination must not be a symbolic link")
    decoder = _binary("ffmpeg")
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(temporary_fd)
    temporary = Path(temporary_name)
    command = [
        decoder,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        *_INPUT_OPTIONS,
        "-i",
        str(source),
        "-map",
        f"0:a:{stream}",
        "-vn",
    ]
    if channel is not None:
        command.extend(["-af", f"pan=mono|c0=c{channel}"])
    command.extend(
        [
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-acodec",
            "pcm_f32le",
            "-f",
            "f32le",
            str(temporary),
        ]
    )
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            **subprocess_options(),
        )
        if completed.returncode != 0:
            raise MediaError("audio decode failed; the selection may be malformed or unsupported")
        size = temporary.stat().st_size
        if size == 0 or size % 4:
            raise MediaError("audio decode produced an empty or invalid float32 cache")
        frames = size // 4
        decoded_samples = np.memmap(temporary, dtype="<f4", mode="r", shape=(frames,))
        try:
            for start in range(0, frames, 262_144):
                if not np.isfinite(decoded_samples[start : start + 262_144]).all():
                    raise MediaError("audio decode produced non-finite PCM samples")
        finally:
            del decoded_samples
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except subprocess.TimeoutExpired as error:
        raise MediaError("audio decode timed out") from error
    except OSError as error:
        raise MediaError(
            "Cannot decode audio; check disk permissions or reinstall the audio tools."
        ) from error
    finally:
        temporary.unlink(missing_ok=True)

    return DecodedAudio(
        sample_rate=sample_rate,
        channels=1,
        frames=frames,
        format="float32le",
        bytes_per_frame=4,
        selected_stream=stream,
        selected_channel=channel,
        channel_mode="downmix" if channel is None else f"channel:{channel}",
        source_sample_rate=selected.sample_rate,
        source_channels=selected.channels,
        source_frames=selected.frames,
        source_duration_seconds=selected.duration_seconds,
        codec_name=selected.codec_name,
        container_name=probe.container_name,
    )


def sha256_file(path: Path) -> str:
    """Hash a regular file in fixed-size chunks."""

    source = _checked_regular_file(path)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while chunk := handle.read(_COPY_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file_with_hash(source_path: Path, destination_path: Path) -> str:
    """Copy and hash a source in bounded chunks, publishing it atomically."""

    source = _checked_regular_file(source_path)
    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise MediaError("media destination must not be a symbolic link")
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    digest = hashlib.sha256()
    try:
        with os.fdopen(temporary_fd, "wb") as output, source.open("rb") as input_file:
            while chunk := input_file.read(_COPY_CHUNK_BYTES):
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, destination)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    return digest.hexdigest()


__all__ = [
    "AudioStreamInfo",
    "DecodedAudio",
    "MediaError",
    "MediaProbe",
    "copy_file_with_hash",
    "decode_to_cache",
    "inspect_media",
    "sha256_file",
]
