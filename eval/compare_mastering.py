#!/usr/bin/env python3
"""Measure an existing comparison WAV and CleanTake's finishing of the same original."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from cleantake.exports import export_project
from cleantake.projects import ProjectStore


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def measure(path, log_path):
    data, rate = sf.read(path, dtype="float64")
    process = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-i",
            str(path),
            "-filter_complex",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    log_path.write_text(process.stderr)
    summary = process.stderr.rsplit("Summary:", 1)[-1]
    patterns = {
        "integrated_lufs": r"I:\s+([-\d.]+) LUFS",
        "loudness_range_lu": r"LRA:\s+([-\d.]+) LU",
        "true_peak_dbtp": r"Peak:\s+([-\d.]+) dBFS",
    }
    values = {}
    for key, pattern in patterns.items():
        found = re.search(pattern, summary)
        if found is None:
            raise ValueError(f"No finite {key} measurement for {path.name}")
        values[key] = float(found[1])
    info = sf.info(path)
    return {
        "filename": path.name,
        "sha256": digest(path),
        "sample_rate": rate,
        "frames": len(data),
        "duration_seconds": len(data) / rate,
        "channels": info.channels,
        "subtype": info.subtype,
        "sample_peak": float(np.abs(data).max()),
        "rms": float(np.sqrt(np.mean(data * data))),
        "finite": bool(np.isfinite(data).all()),
        **values,
    }


def compare(original, comparison, output):
    repository = Path(__file__).resolve().parents[1]
    production_hashes = {
        str(p.relative_to(repository)): digest(p)
        for p in sorted((repository / "src/cleantake").rglob("*.py"))
    }
    output.mkdir(parents=True, exist_ok=False)
    store = ProjectStore(output / "projects")
    project = store.create("Same-input finishing comparison")
    source = store.import_source(project.id, original)
    export_project(store, project.id, output / "cleantake", finish=True)
    source_map = json.loads((output / "cleantake/source-map.json").read_text())
    measurements = {}
    for name, path in {
        "input": original,
        "comparison": comparison,
        "cleantake_finish": output / "cleantake/dialogue-finished.wav",
    }.items():
        measurements[name] = measure(path, output / f"{name}-ebur128.log")
    result = {
        "schema": 1,
        "scope": "Single-file finishing measurements; no comparative listening or quality ranking.",
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True
        ).strip(),
        "production_sha256": production_hashes,
        "source_hashes_unchanged": all(
            digest(repository / path) == checksum for path, checksum in production_hashes.items()
        ),
        "runner_sha256": digest(Path(__file__)),
        "original_sha256": source.sha256,
        "cache_sha256": source.audio.cache_sha256,
        "cleantake_processing": source_map["processing"],
        "measurement_tool": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[
            0
        ],
        "measurements": measurements,
        "comparison_settings": "Record the actual product version and settings separately.",
    }
    (output / "measurements.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--comparison", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = compare(args.input, args.comparison, args.output)
    if not result["source_hashes_unchanged"]:
        raise SystemExit("Source files changed during the measurement; inspect the saved result")


if __name__ == "__main__":
    main()
