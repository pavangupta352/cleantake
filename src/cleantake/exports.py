"""Portable, source-traceable exports of accepted dialogue decisions."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from cleantake import __version__
from cleantake.engine import (
    Alignment,
    CandidateTrack,
    RepairProposal,
    contributor_spans,
    render_range,
    sample_aligned,
)
from cleantake.media import sha256_file
from cleantake.models import ProjectRecord
from cleantake.projects import ProjectConflictError, ProjectStore


class ExportError(ValueError):
    """An export cannot safely produce the requested artifact."""


class ExportCancelled(ExportError):
    """Cancellation stopped an export before publication."""


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise ExportCancelled("Export cancelled")


def project_audio(store: ProjectStore, project: ProjectRecord):
    """Open immutable disk-backed inputs using the saved project clocks."""
    if project.primary_source_id is None or project.duration_frames < 1:
        raise ExportError("Import a primary recording before rendering")
    reference = store.source_samples(project.id, project.primary_source_id)
    candidates = [
        CandidateTrack(
            source.id,
            store.source_samples(project.id, source.id),
            Alignment(**source.alignment.model_dump()),
        )
        for source in project.sources
        if source.id != project.primary_source_id
    ]
    repairs = [RepairProposal(**repair.model_dump(exclude={"id"})) for repair in project.repairs]
    return reference, candidates, repairs


def _write_audio(path, frames, rate, read, *, subtype="FLOAT", cancelled=None):
    with sf.SoundFile(path, "w", samplerate=rate, channels=1, subtype=subtype) as output:
        for start in range(0, frames, rate * 10):
            _check_cancelled(cancelled)
            samples = read(start, min(start + rate * 10, frames))
            if not np.isfinite(samples).all():
                raise ExportError("Rendered audio contains non-finite samples")
            if subtype != "FLOAT" and np.max(np.abs(samples), initial=0) > 1:
                raise ExportError("Audio exceeds full scale; use float WAV or reduce edit gain")
            output.write(samples)


def _reaper_text(project, stems, spans):
    # Quoting follows REAPER's quoted text tokens; filenames are generated UUID paths.
    def quote(value):
        return (
            '"'
            + value.replace("\\", "/").replace('"', "'").replace("\r", " ").replace("\n", " ")
            + '"'
        )

    def number(value):
        return f"{value:.12g}"

    rate = project.sample_rate
    lines = [
        "<REAPER_PROJECT 0.1 7.0 1",
        f"  SAMPLERATE {rate} 1 0",
        "  TEMPO 120",
        "  MASTER_VOLUME 1",
        "  RIPPLE 0",
    ]
    for source in project.sources:
        if source.id not in stems:
            continue
        points = {}
        for span in spans:
            matching = [c for c in span["contributors"] if c["source_id"] == source.id]
            start_value = sum(c["weight"]["start"] * 10 ** (c["gain_db"] / 20) for c in matching)
            end_value = sum(c["weight"]["end"] * 10 ** (c["gain_db"] / 20) for c in matching)
            points[span["start_frame"]] = start_value
            points[span["end_frame"] - 1] = end_value
        points[project.duration_frames] = points.get(project.duration_frames - 1, 0)
        lines.extend(
            [
                "  <TRACK",
                f"    NAME {quote(source.name)}",
                "    VOLPAN 1 0 1 -1",
                "    MUTESOLO 0 0 0",
                "    <VOLENV2",
                "      ACT 1 -1",
                "      VIS 1 1 1",
                "      ARM 1",
                "      DEFSHAPE 0 -1 -1",
            ]
        )
        for frame, value in sorted(points.items()):
            lines.append(f"      PT {number(frame / rate)} {number(value)} 0")
        lines.extend(
            [
                "    >",
                "    <ITEM",
                "      POSITION 0",
                "      SNAPOFFS 0",
                f"      LENGTH {number(project.duration_frames / rate)}",
                "      SOFFS 0",
                "      VOLPAN 1 0 1 -1",
                "      FADEIN 1 0 0",
                "      FADEOUT 1 0 0",
                "      PLAYRATE 1 1 0 -1 0 0.0025",
                "      <SOURCE WAVE",
                f"        FILE {quote(stems[source.id])}",
                "      >",
                "    >",
                "  >",
            ]
        )
    lines.append(">")
    return "\n".join(lines) + "\n"


def export_project(
    store: ProjectStore,
    project_id: str,
    output_dir: Path,
    *,
    format: str = "wav",
    finish: bool = False,
    expected_revision: int | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Publish an entire export directory only after every artifact succeeds."""
    if format not in {"wav", "flac"}:
        raise ExportError("Export format must be wav or flac")
    destination = Path(output_dir)
    if destination.exists() or destination.is_symlink():
        raise ExportError("Export destination already exists")
    _check_cancelled(cancelled)
    project = store.get(project_id)
    if expected_revision is not None and project.revision != expected_revision:
        raise ProjectConflictError("Project revision changed; refresh before exporting")
    store.validate_sources(project_id)
    reference, candidates, repairs = project_audio(store, project)
    spans = contributor_spans(
        reference,
        candidates,
        repairs,
        0,
        project.duration_frames,
        project.sample_rate,
        primary_source_id=project.primary_source_id,
    )
    source_lookup = {source.id: source for source in project.sources}
    for span in spans:
        for contributor in span["contributors"]:
            source = source_lookup[contributor["source_id"]]
            ratio = source.audio.source_sample_rate / project.sample_rate
            contributor["original_clock_start_frame"] = contributor["source_start_frame"] * ratio
            contributor["original_clock_end_frame"] = contributor["source_end_frame"] * ratio
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    warnings = list(project.warnings)
    subtype = "FLOAT" if format == "wav" else "PCM_24"
    dialogue_name = f"dialogue.{format}"
    try:
        _write_audio(
            stage / dialogue_name,
            project.duration_frames,
            project.sample_rate,
            lambda start, end: render_range(
                reference, candidates, repairs, start, end, project.sample_rate
            ),
            subtype=subtype,
            cancelled=cancelled,
        )
        (stage / "stems").mkdir()
        stems = {}
        for source in project.sources:
            if source.alignment.status == "uncertain" and source.id != project.primary_source_id:
                warnings.append(f"{source.name}: no aligned stem; source alignment needs review")
                continue
            name = f"stems/{source.id}.wav"
            samples = (
                reference
                if source.id == project.primary_source_id
                else next(track.samples for track in candidates if track.source_id == source.id)
            )
            alignment = Alignment(**source.alignment.model_dump())
            _write_audio(
                stage / name,
                project.duration_frames,
                project.sample_rate,
                lambda start, end, audio=samples, clock=alignment: sample_aligned(
                    audio, start, end, project.sample_rate, clock
                ),
                cancelled=cancelled,
            )
            stems[source.id] = name
        (stage / "session.rpp").write_text(_reaper_text(project, stems, spans), encoding="utf-8")
        processing = []
        if finish:
            finishing = finish_audio(
                stage / dialogue_name, stage / "dialogue-finished.wav", cancelled=cancelled
            )
            processing.append(finishing)
            warnings.extend(finishing["warnings"])
        sources = []
        for source in project.sources:
            sources.append(
                {
                    "id": source.id,
                    "name": source.name,
                    "original_filename": source.original_filename,
                    "sha256": source.sha256,
                    "audio": source.audio.model_dump(exclude={"path"}),
                    "alignment": source.alignment.model_dump(),
                    "aligned_stem": stems.get(source.id),
                }
            )
        provenance = {
            "schema_version": 1,
            "software": {"name": "CleanTake", "version": __version__},
            "project_id": project.id,
            "project_revision": project.revision,
            "created_at": datetime.now(UTC).isoformat(),
            "sample_rate": project.sample_rate,
            "output": {
                "file": dialogue_name,
                "frames": project.duration_frames,
                "channels": 1,
                "subtype": subtype,
                "sha256": sha256_file(stage / dialogue_name),
            },
            "clock_mapping": "source = project * (1 + drift_ppm / 1000000) + offset_seconds",
            "original_clock_note": "Original frame positions are decoded-stream time coordinates. "
            "The cache records FFmpeg resampling and channel selection; "
            "these are not original codec packet or resampler tap indices.",
            "sources": sources,
            "repairs": [r.model_dump() for r in project.repairs],
            "spans": spans,
            "processing": processing,
            "warnings": warnings,
        }
        (stage / "source-map.json").write_text(
            json.dumps(provenance, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _check_cancelled(cancelled)
        if store.get(project_id).revision != project.revision:
            raise ProjectConflictError("Project changed during export; export again")
        artifacts = []
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                media_type = {
                    ".wav": "audio/wav",
                    ".flac": "audio/flac",
                    ".json": "application/json",
                    ".rpp": "text/plain",
                }[path.suffix]
                artifacts.append(
                    {
                        "name": path.relative_to(stage).as_posix(),
                        "size": path.stat().st_size,
                        "media_type": media_type,
                    }
                )
        if destination.exists() or destination.is_symlink():
            raise ExportError("Export destination already exists")
        os.rename(stage, destination)
        return {"revision": project.revision, "artifacts": artifacts, "warnings": warnings}
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _ffmpeg(source, filter_text, output_args, cancelled):
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise ExportError("FFmpeg is required for loudness finishing")
    command = [
        binary,
        "-hide_banner",
        "-nostats",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        filter_text,
        *output_args,
    ]
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log)
        started = time.monotonic()
        try:
            while process.poll() is None:
                _check_cancelled(cancelled)
                if time.monotonic() - started > 3600:
                    raise ExportError("Loudness processing timed out")
                time.sleep(0.05)
            if process.returncode != 0:
                raise ExportError("FFmpeg could not finish this audio")
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - 4 * 1024 * 1024))
            return log.read(4 * 1024 * 1024).decode("utf-8", errors="replace")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def finish_audio(source: Path, destination: Path, *, cancelled=None):
    """Two-pass -16 LUFS finishing, verified on the output by EBU R128."""
    source, destination = Path(source), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ExportError("Finished audio destination already exists")
    _check_cancelled(cancelled)
    info = sf.info(source)
    if info.samplerate != 48_000 or info.channels != 1 or info.frames < 1:
        raise ExportError("Finishing requires nonempty 48 kHz mono audio")
    first_log = _ffmpeg(
        source, "loudnorm=I=-16:TP=-1:LRA=11:print_format=json", ["-f", "null", "-"], cancelled
    )
    blocks = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', first_log, flags=re.S)
    if not blocks:
        raise ExportError("FFmpeg did not return loudness measurements")
    measured = json.loads(blocks[-1])
    stats = {
        key: float(measured[key])
        for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".finished.", suffix=".wav", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    result = {
        "operation": "loudness",
        "target_lufs": -16,
        "true_peak_ceiling_dbtp": -1,
        "loudness_tolerance_lu": 0.5,
        "target_met": False,
        "loudness_error_lu": None,
        "warnings": [],
        "source_file": source.name,
        "output_file": destination.name,
    }
    try:
        if not all(math.isfinite(value) for value in stats.values()):
            _write_audio(
                temporary,
                info.frames,
                48_000,
                lambda start, end: sf.read(source, start=start, stop=end, dtype="float32")[0],
                cancelled=cancelled,
            )
            result.update(
                status="skipped", reason="No measurable integrated loudness; audio retained"
            )
            result["warnings"].append(
                f"Finishing skipped for {destination.name}: "
                "no measurable integrated loudness; audio retained."
            )
        else:
            filter_text = (
                "loudnorm=I=-16:TP=-1:LRA=11:linear=true:print_format=json"
                f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
                f":measured_LRA={stats['input_lra']}"
                f":measured_thresh={stats['input_thresh']}"
                f":offset={stats['target_offset']}"
                f",aresample=48000,apad,atrim=end_sample={info.frames}"
            )
            second_log = _ffmpeg(
                source,
                filter_text,
                ["-ar", "48000", "-c:a", "pcm_f32le", str(temporary)],
                cancelled,
            )
            blocks = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', second_log, flags=re.S)
            normalization = json.loads(blocks[-1]) if blocks else {}
            verification = _ffmpeg(temporary, "ebur128=peak=true", ["-f", "null", "-"], cancelled)
            summary = verification.rsplit("Summary:", 1)[-1]
            integrated = re.search(r"I:\s*([-\d.]+) LUFS", summary)
            peak = re.search(r"Peak:\s*([-\d.]+) dBFS", summary)
            if integrated is None or peak is None:
                raise ExportError("Could not verify finished loudness and true peak")
            final_i, final_tp = float(integrated[1]), float(peak[1])
            if not math.isfinite(final_i) or not math.isfinite(final_tp) or final_tp > -0.9:
                raise ExportError("Finished audio did not meet its true-peak ceiling")
            if sf.info(temporary).frames != info.frames:
                raise ExportError("Loudness finishing changed the recording duration")
            loudness_error = round(final_i - result["target_lufs"], 3)
            target_met = abs(loudness_error) <= result["loudness_tolerance_lu"]
            result.update(
                status="finished",
                target_met=target_met,
                loudness_error_lu=loudness_error,
                normalization=normalization.get("normalization_type"),
                measured={
                    "integrated_lufs": final_i,
                    "true_peak_dbtp": final_tp,
                    "method": "ffmpeg ebur128",
                },
            )
            if not target_met:
                result["warnings"].append(
                    f"Loudness target not met in {destination.name}: "
                    f"measured {final_i:g} LUFS, target {result['target_lufs']:g} LUFS "
                    f"(±{result['loudness_tolerance_lu']:g} LU). Review levels before delivery."
                )
        _check_cancelled(cancelled)
        if destination.exists() or destination.is_symlink():
            raise ExportError("Finished audio destination already exists")
        os.rename(temporary, destination)
        result["sha256"] = sha256_file(destination)
        return result
    finally:
        temporary.unlink(missing_ok=True)
