#!/usr/bin/env python3
"""Measure a local long-session import, analysis, render and cooperative cancellation."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

from cleantake.engine import render_range
from cleantake.exports import ExportCancelled, export_project, project_audio
from cleantake.projects import ProjectStore

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def rss():
    try:
        import resource
    except ImportError:
        return {"available": False}
    divisor = 1024**2 if platform.system() == "Darwin" else 1024
    return {
        "available": True,
        "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor,
        "largest_finished_child_peak_rss_mib": resource.getrusage(
            resource.RUSAGE_CHILDREN
        ).ru_maxrss
        / divisor,
        "scope": (
            "Peak resident mappings included. Process and largest finished child "
            "reported separately; not aggregate concurrent RSS."
        ),
    }


def write_inputs(directory, seconds, rate):
    rng = np.random.default_rng(832019)
    filter_coefficients = butter(3, [180, 3_200], fs=rate, btype="bandpass", output="sos")
    state = np.zeros((len(filter_coefficients), 2))
    offset = round(0.375 * rate)
    gap = (seconds // 2 * rate, seconds // 2 * rate + rate // 2)
    paths = [directory / "main.wav", directory / "backup.wav"]
    with (
        sf.SoundFile(paths[0], "w", rate, 1, subtype="FLOAT") as primary,
        sf.SoundFile(paths[1], "w", rate, 1, subtype="FLOAT") as donor,
    ):
        donor.write(np.zeros(offset, dtype="float32"))
        for second in range(seconds):
            noise, state = sosfilt(filter_coefficients, rng.normal(size=rate), zi=state)
            t = second + np.arange(rate) / rate
            envelope = 0.02 + 0.18 * np.sin(3.71 * t) ** 4
            clean = (noise * envelope).astype("float32")
            main = clean.copy()
            if second == seconds // 2:
                main[: rate // 2] = 0
            primary.write(main)
            donor.write(clean * 0.5)
    return paths, gap


def run(seconds, output):
    rate = 48_000
    started = time.perf_counter()
    result = {
        "schema": 1,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "description": "Deterministic nonperiodic filtered numerical PCM, not recorded speech.",
        "seconds": seconds,
        "sample_rate": rate,
        "tracks": 2,
        "clock": {"offset_seconds": 0.375, "drift_ppm": 0},
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in sorted((ROOT / "src/cleantake").rglob("*.py"))
        },
        "runner_sha256": digest(__file__),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "phases": {},
    }
    with tempfile.TemporaryDirectory(prefix="cleantake-long-", dir=ROOT / ".local") as temporary:
        base = Path(temporary)
        phase = time.perf_counter()
        paths, gap = write_inputs(base, seconds, rate)
        result["input_sha256"] = {p.name: digest(p) for p in paths}
        result["input_bytes"] = sum(p.stat().st_size for p in paths)
        result["phases"]["generate_seconds"] = time.perf_counter() - phase
        print("Generated long inputs", flush=True)
        store = ProjectStore(base / "projects")
        project = store.create("Long recording evaluation")
        phase = time.perf_counter()
        imported = [store.import_source(project.id, path) for path in paths]
        result["phases"]["import_seconds"] = time.perf_counter() - phase
        print("Imported both sources", flush=True)
        phase = time.perf_counter()
        analyzed = store.analyze(project.id)
        result["phases"]["analyze_seconds"] = time.perf_counter() - phase
        result["alignment"] = analyzed.sources[1].alignment.model_dump()
        result["automatic_proposals"] = [p.model_dump(mode="json") for p in analyzed.repairs]
        print("Analyzed long project", flush=True)
        # Manual acceptance is deliberate so resource coverage does not depend on recall.
        store.update_source(project.id, imported[1].id, {"alignment": {"offset_seconds": 0.375}})
        store.add_repair(
            project.id,
            start_frame=gap[0],
            end_frame=gap[1],
            kind="manual",
            source_id=imported[1].id,
            confidence=1,
            reason="Known injected interval",
            status="accepted",
            gain_db=20 * np.log10(2),
            fade_ms=12,
        )
        saved = store.get(project.id)
        before = (store.root / project.id / "project.json").read_bytes()
        phase = time.perf_counter()
        export_project(store, project.id, base / "export", expected_revision=saved.revision)
        result["phases"]["export_seconds"] = time.perf_counter() - phase
        result["export_bytes"] = sum(
            p.stat().st_size for p in (base / "export").rglob("*") if p.is_file()
        )
        print("Exported full dialogue, two stems and source map", flush=True)
        phase = time.perf_counter()
        reference, candidates, repairs = project_audio(store, saved)
        max_error = 0.0
        outside_unchanged = True
        read_frames = 0
        with sf.SoundFile(base / "export/dialogue.wav") as rendered:
            for start in range(0, saved.duration_frames, rate * 10):
                end = min(start + rate * 10, saved.duration_frames)
                actual = rendered.read(end - start, dtype="float32")
                expected = render_range(reference, candidates, repairs, start, end, rate)
                max_error = max(max_error, float(np.max(np.abs(actual - expected))))
                frames = np.arange(start, end)
                outside = (frames < gap[0]) | (frames >= gap[1])
                outside_unchanged &= np.array_equal(actual[outside], reference[start:end][outside])
                read_frames += len(actual)
        result["verification"] = {
            "export_frames": read_frames,
            "duration_retained": read_frames == seconds * rate,
            "outside_accepted_edit_exact": bool(outside_unchanged),
            "float32_export_max_abs_rounding_error": max_error,
            "project_unchanged_by_export": before
            == (store.root / project.id / "project.json").read_bytes(),
        }
        result["phases"]["verify_seconds"] = time.perf_counter() - phase
        cancel_observed = None
        cancellation_checks = 0

        def cancel_after_audio_written():
            nonlocal cancel_observed, cancellation_checks
            cancellation_checks += 1
            # Trigger after actual output bytes exist, not before work begins.
            partials = list(base.glob(".cancelled.*/dialogue.wav"))
            requested = any(p.stat().st_size > rate * 4 * 15 for p in partials)
            if requested and cancel_observed is None:
                cancel_observed = time.perf_counter()
            return requested

        phase = time.perf_counter()
        try:
            export_project(
                store, project.id, base / "cancelled", cancelled=cancel_after_audio_written
            )
        except ExportCancelled:
            result["cancellation"] = {
                "status": "cancelled",
                "seconds_until_request": cancel_observed - phase
                if cancel_observed is not None
                else None,
                "response_seconds": time.perf_counter() - cancel_observed
                if cancel_observed is not None
                else None,
                "checks": cancellation_checks,
                "published_output_absent": not (base / "cancelled").exists(),
                "staging_cleaned": not list(base.glob(".cancelled.*")),
                "project_unchanged": before
                == (store.root / project.id / "project.json").read_bytes(),
            }
        else:
            result["cancellation"] = {"status": "unexpected_completion"}
        result["resources"] = rss()
        # Release read-only mappings before Windows directory cleanup.
        del reference, candidates, repairs
        gc.collect()
    result["total_seconds"] = time.perf_counter() - started
    result["completed_at_utc"] = datetime.now(UTC).isoformat()
    result["source_hashes_unchanged"] = all(
        digest(ROOT / p) == sha for p, sha in result["source_sha256"].items()
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "eval/results/2026-09-08/long-session.json"
    )
    args = parser.parse_args()
    if args.seconds < 10:
        parser.error("Use at least ten seconds")
    result = run(args.seconds, args.output)
    checks = result["verification"]
    cancellation = result["cancellation"]
    valid = (
        checks["duration_retained"]
        and checks["outside_accepted_edit_exact"]
        and checks["project_unchanged_by_export"]
        and checks["float32_export_max_abs_rounding_error"] <= 2**-24
        and cancellation["status"] == "cancelled"
        and cancellation.get("published_output_absent")
        and cancellation.get("staging_cleaned")
        and cancellation.get("project_unchanged")
        and result["source_hashes_unchanged"]
    )
    if not valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
