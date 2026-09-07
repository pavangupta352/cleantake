#!/usr/bin/env python3
"""Build a compact digest without discarding the full per-case result record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def summarize(path):
    raw = json.loads((path / "corpus-results.json").read_text())
    summary = {
        "schema": 1,
        "clock_cases": len(raw["clock_cases"]),
        "real_cases": len(raw["cases"]),
        "invariant_failures": raw["failures"],
        "code_lock_unchanged": raw["code_lock_unchanged"],
        "groups": [],
        "known_clock": {},
    }
    for split in ["development", "reserved_evaluation"]:
        clocks = [row for row in raw["clock_cases"] if row["split"] == split]
        summary["known_clock"][split] = {
            "passed": sum(row["passed"] for row in clocks),
            "total": len(clocks),
            "maximum_offset_error_ms": max(abs(row["offset_error_ms"]) for row in clocks),
            "maximum_endpoint_error_ms": max(abs(row["endpoint_error_ms"]) for row in clocks),
        }
        for condition in [
            "clean",
            "dropout",
            "clipping",
            "shared_dropout",
            "shared_clipping",
            "clock_dropout",
        ]:
            rows = [
                row
                for row in raw["cases"]
                if row["split"] == split and row["condition"] == condition
            ]
            summary["groups"].append(
                {
                    "split": split,
                    "condition": condition,
                    "recordings": len(rows),
                    "donor_proposals": sum(row["review_accepted"] for row in rows),
                    "unresolved_flags": sum(
                        p["source_id"] is None for row in rows for p in row["proposals"]
                    ),
                    "donor_proposals_outside_injected_intervals": sum(
                        row["donor_proposals_outside_faults"] for row in rows
                    ),
                    "injected_seconds": sum(row["injected_frames"] for row in rows) / 16000,
                    "injected_seconds_covered_by_proposals": sum(
                        row["fault_frames_covered_by_proposals"] for row in rows
                    )
                    / 16000,
                    "aligned_donors": sum(
                        a["status"] == "aligned" for row in rows for a in row["alignments"]
                    ),
                    "donor_alignment_attempts": sum(len(row["alignments"]) for row in rows),
                    "outside_injection_modified_seconds": sum(
                        row["render"].get("content_changed_outside_injected_fault_frames", 0)
                        for row in rows
                    )
                    / 16000,
                }
            )
    renders = [row["render"] for row in raw["cases"] if "error" not in row["render"]]
    summary["rendering"] = {
        "successful": len(renders),
        "duration_retained": sum(row["duration_retained"] for row in renders),
        "outside_edits_exact": sum(row["outside_edits_exact"] for row in renders),
        "pending_only_exact": sum(row["pending_only_exact"] for row in renders),
        "finite": sum(row["finite"] for row in renders),
        "maximum_peak": max(row["peak"] for row in renders),
        "maximum_provenance_abs_error": max(row["provenance_max_abs_error"] for row in renders),
    }
    (path / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_directory", type=Path)
    summarize(parser.parse_args().result_directory)
