"""Explicit resource ceilings for the local server."""

from dataclasses import dataclass


@dataclass
class Limits:
    max_upload_bytes: int = 8 * 1024**3
    max_archive_bytes: int = 50 * 1024**3
    max_recording_seconds: int = 14_400
    max_sources: int = 4
    preview_seconds: int = 120
    waveform_bins: int = 4096
    workers: int = 2
    queued_jobs: int = 16
    json_bytes: int = 2 * 1024**2
