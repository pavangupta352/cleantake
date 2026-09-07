#!/usr/bin/env python3
"""Reproduce the fixed corpus protocol; keep source recordings outside version control."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import scipy
import soundfile as sf

from cleantake.engine import (
    CandidateTrack,
    contributor_spans,
    estimate_alignment,
    find_repairs,
    render_range,
)

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def source_hashes():
    paths = sorted((ROOT / "src/cleantake/engine").glob("*.py"))
    paths += [HERE / "run.py", HERE / "protocol.json", HERE / "corpus.json"]
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def lock(path):
    """Persist code and corpus identities BEFORE any holdout PCM is opened."""
    path = Path(path)
    if path.exists():
        raise ValueError("Lock already exists; use a new result directory for a new experiment")
    corpus = json.loads((HERE / "corpus.json").read_text())
    data = {
        "schema": 1,
        "locked_at_utc": datetime.now(UTC).isoformat(),
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "worktree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
        "code_sha256": source_hashes(),
        "production_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in sorted((ROOT / "src/cleantake").rglob("*.py"))
        },
        "corpus_sha256": {x["path"]: x["sha256"] for x in corpus["excerpts"]},
        "split": corpus["split"],
        "platform": platform.platform(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "soundfile": sf.__version__,
    }
    save(path, data)
    return data


def prepare(directory):
    """Download publisher originals, verify them, and recreate exact declared excerpts."""
    directory = Path(directory)
    corpus = json.loads((HERE / "corpus.json").read_text())
    for item in corpus["sources"]:
        destination = directory / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            partial = destination.with_suffix(".part")
            try:
                urllib.request.urlretrieve(item["url"], partial)
                if digest(partial) != item["sha256"]:
                    raise ValueError(f"Publisher source hash mismatch: {item['path']}")
                partial.replace(destination)
            finally:
                partial.unlink(missing_ok=True)
        if digest(destination) != item["sha256"]:
            raise ValueError(f"Source hash mismatch: {item['path']}")
    for item in corpus["excerpts"]:
        destination = directory / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    str(item["start_seconds"]),
                    "-i",
                    str(directory / item["source_path"]),
                    "-t",
                    str(item["end_seconds"] - item["start_seconds"]),
                    "-map",
                    "0:a:0",
                    "-map_metadata",
                    "-1",
                    "-fflags",
                    "+bitexact",
                    "-flags:a",
                    "+bitexact",
                    "-c:a",
                    "pcm_s16le",
                    str(destination),
                ],
                check=True,
            )
        if digest(destination) != item["sha256"]:
            raise ValueError(
                f"Excerpt hash mismatch: {item['path']}; inspect FFmpeg/container differences"
            )


def inject_clock(samples, rate, offset_seconds=0, drift_ppm=0, polarity=1):
    """Independent inverse-clock interpolation, never the production sampler."""
    scale = 1 + drift_ppm / 1e6
    output_frames = int(np.ceil(len(samples) * scale + max(0, offset_seconds) * rate)) + 2
    candidate_frames = np.arange(output_frames, dtype=np.float64)
    reference_frames = (candidate_frames - offset_seconds * rate) / scale
    return np.interp(reference_frames, np.arange(len(samples)), samples, left=0, right=0) * polarity


def reconstruct(spans, arrays, rate, frames):
    """Read the public source-map contract using an independent implementation."""
    result = np.zeros(frames, dtype=np.float64)
    for span in spans:
        lo, hi = span["start_frame"], span["end_frame"]
        for contributor in span["contributors"]:
            data = arrays[contributor["source_id"]]
            clock = contributor["alignment"]
            positions = np.arange(lo, hi) * (1 + clock["drift_ppm"] / 1e6)
            positions = positions + clock["offset_seconds"] * rate
            pcm = np.interp(positions, np.arange(len(data)), data, left=0, right=0)
            weights = np.linspace(
                contributor["weight"]["start"], contributor["weight"]["end"], hi - lo
            )
            result[lo:hi] += pcm * clock["polarity"] * 10 ** (contributor["gain_db"] / 20) * weights
    return result


def clock_metrics(alignment, transform, seconds):
    offset_error = alignment.offset_seconds - transform["offset_seconds"]
    drift_error = alignment.drift_ppm - transform["drift_ppm"]
    return {
        "offset_error_ms": offset_error * 1000,
        "drift_error_ppm": drift_error,
        "endpoint_error_ms": (offset_error + seconds * drift_error / 1e6) * 1000,
        "polarity_correct": alignment.polarity == transform["polarity"],
    }


def corpus_case(primary, donors, rate, condition, protocol):
    before = primary.copy()
    alternatives = [data.copy() for data in donors]
    fault = np.zeros(len(primary), dtype=bool)
    if condition != "clean":
        for a, b in protocol["intervals_seconds"]:
            lo, hi = round(a * rate), round(b * rate)
            fault[lo:hi] = True
            if "dropout" in condition:
                before[lo:hi] = 0
            if "clipping" in condition:
                before[lo:hi] = np.clip(
                    before[lo:hi] * protocol["clipping"]["gain"],
                    -protocol["clipping"]["ceiling"],
                    protocol["clipping"]["ceiling"],
                )
            if condition.startswith("shared_"):
                for alternate in alternatives:
                    alternate[lo:hi] = (
                        0
                        if condition == "shared_dropout"
                        else np.clip(
                            alternate[lo:hi] * protocol["clipping"]["gain"],
                            -protocol["clipping"]["ceiling"],
                            protocol["clipping"]["ceiling"],
                        )
                    )
    transform = (
        protocol["clock_dropout"]
        if condition == "clock_dropout"
        else {"offset_seconds": 0, "drift_ppm": 0, "polarity": 1}
    )
    if condition == "clock_dropout":
        alternatives = [inject_clock(data, rate, **transform) for data in alternatives]
    clocks = [estimate_alignment(before, data, rate) for data in alternatives]
    candidates = [
        CandidateTrack(name, data, clock)
        for name, data, clock in zip(["lapel", "array"], alternatives, clocks, strict=True)
    ]
    proposals = find_repairs(before, candidates, rate)
    accepted = [proposal for proposal in proposals if proposal.source_id is not None]
    for proposal in accepted:
        proposal.status = "accepted"
    touched = np.zeros(len(primary), dtype=bool)
    for proposal in accepted:
        touched[proposal.start_frame : proposal.end_frame] = True
    started = time.perf_counter()
    try:
        output = render_range(before, candidates, accepted, 0, len(before), rate)
        spans = contributor_spans(before, candidates, accepted, 0, len(before), rate)
        rebuilt = reconstruct(
            spans,
            {"primary": before, **{c.source_id: c.samples for c in candidates}},
            rate,
            len(before),
        )
        render = {
            "duration_retained": len(output) == len(before),
            "outside_edits_exact": np.array_equal(output[~touched], before[~touched]),
            "pending_only_exact": np.array_equal(
                render_range(before, candidates, [], 0, len(before), rate), before
            ),
            "finite": bool(np.isfinite(output).all()),
            "peak": float(np.max(np.abs(output))),
            "provenance_max_abs_error": float(np.max(np.abs(output - rebuilt))),
            "content_changed_outside_injected_fault_frames": int(
                np.count_nonzero((output != before) & ~fault)
            ),
            "output_sha256_f64le": hashlib.sha256(output.astype("<f8").tobytes()).hexdigest(),
        }
    except ValueError as error:
        render = {"error": str(error)}
    return {
        "condition": condition,
        "alignments": [
            {
                "source_id": c.source_id,
                **asdict(c.alignment),
                "nominal_clock_errors": clock_metrics(c.alignment, transform, len(primary) / rate),
            }
            for c in candidates
        ],
        "proposals": [asdict(proposal) for proposal in proposals],
        "review_accepted": len(accepted),
        "donor_proposals_outside_faults": sum(
            not np.any(fault[p.start_frame : p.end_frame]) for p in accepted
        ),
        "injected_frames": int(fault.sum()),
        "injected_primary_rms": float(np.sqrt(np.mean(primary[fault] ** 2)))
        if fault.any()
        else None,
        "fault_frames_covered_by_proposals": int((touched & fault).sum()),
        "render": render,
        "render_and_map_seconds": time.perf_counter() - started,
    }


def run_corpus(directory, output):
    output = Path(output)
    frozen = json.loads((output / "lock.json").read_text())
    if source_hashes() != frozen["code_sha256"]:
        raise ValueError("Frozen evaluation code changed; do not silently reuse the lock")
    corpus = json.loads((HERE / "corpus.json").read_text())
    protocol = json.loads((HERE / "protocol.json").read_text())
    groups = {}
    for item in corpus["excerpts"]:
        groups.setdefault((item["meeting"], item["start_seconds"]), []).append(item)
    results = {
        "schema": 1,
        "lock_sha256": digest(output / "lock.json"),
        "cases": [],
        "clock_cases": [],
        "failures": [],
    }
    for (meeting, start), items in sorted(groups.items()):
        split = (
            "development" if meeting in corpus["split"]["development"] else "reserved_evaluation"
        )
        # The lock has already been persisted before this first holdout file read.
        samples = {}
        for item in items:
            path = Path(directory) / item["path"]
            if digest(path) != item["sha256"]:
                raise ValueError(f"Input changed: {item['path']}")
            pcm, rate = sf.read(path, dtype="float64")
            if rate != item["sample_rate"] or len(pcm) != item["frames"]:
                raise ValueError("Unexpected corpus audio shape")
            samples[item["channel"]] = pcm
        primary = samples["Headset-0"]
        for transform in protocol["clock_cases"]:
            injection = {key: transform[key] for key in ("offset_seconds", "drift_ppm", "polarity")}
            candidate = inject_clock(primary, rate, **injection)
            began = time.perf_counter()
            alignment = estimate_alignment(primary, candidate, rate)
            errors = clock_metrics(alignment, injection, len(primary) / rate)
            passed = (
                alignment.status == "aligned"
                and abs(errors["offset_error_ms"]) <= 2
                and abs(errors["endpoint_error_ms"]) <= 3
                and errors["polarity_correct"]
            )
            row = {
                "meeting": meeting,
                "start_seconds": start,
                "split": split,
                "condition": transform["name"],
                "alignment": asdict(alignment),
                **errors,
                "passed": passed,
                "seconds": time.perf_counter() - began,
            }
            results["clock_cases"].append(row)
            if not passed:
                results["failures"].append({"area": "known_clock", **row})
        for condition in protocol["real_cases"]:
            began = time.perf_counter()
            row = corpus_case(
                primary, [samples["Lapel-0"], samples["Array1-01"]], rate, condition, protocol
            )
            row.update(
                meeting=meeting,
                start_seconds=start,
                split=split,
                elapsed_seconds=time.perf_counter() - began,
            )
            results["cases"].append(row)
            render = row["render"]
            failures = []
            if "error" in render:
                failures.append("accepted_proposal_render_rejected")
            else:
                for key in (
                    "duration_retained",
                    "outside_edits_exact",
                    "pending_only_exact",
                    "finite",
                ):
                    if not render[key]:
                        failures.append(key)
                if (
                    render["provenance_max_abs_error"]
                    > protocol["thresholds"]["provenance_max_abs_error"]
                ):
                    failures.append("provenance_reconstruction")
            if condition.startswith("shared_") and row["fault_frames_covered_by_proposals"]:
                failures.append("shared_damage_offered_as_repair")
            if failures:
                results["failures"].append(
                    {
                        "area": "real_case",
                        "meeting": meeting,
                        "start_seconds": start,
                        "condition": condition,
                        "checks": failures,
                    }
                )
            save(output / "corpus-results.json", results)
            print(
                f"{split} {meeting} {start}s {condition}: "
                f"{row['review_accepted']} donor proposals; failures={failures}",
                flush=True,
            )
    results["code_lock_unchanged"] = source_hashes() == frozen["code_sha256"]
    results["completed_at_utc"] = datetime.now(UTC).isoformat()
    save(output / "corpus-results.json", results)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["lock", "prepare", "corpus"])
    parser.add_argument("--corpus", type=Path, default=ROOT / ".local/evaluation")
    parser.add_argument("--output", type=Path, default=HERE / "results/2026-09-08")
    args = parser.parse_args()
    if args.command == "lock":
        lock(args.output / "lock.json")
    elif args.command == "prepare":
        prepare(args.corpus)
    else:
        results = run_corpus(args.corpus, args.output)
        if results["failures"] or not results["code_lock_unchanged"]:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
