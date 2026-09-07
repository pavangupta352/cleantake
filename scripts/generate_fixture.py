"""Generate deterministic non-speech audio with a known gap, clock offset and drift."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="A new output directory")
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Output directory already exists")
    rate, seconds, seed = 48_000, 20, 352
    rng = np.random.default_rng(seed)
    time = np.arange(rate * seconds) / rate
    clean = sosfilt(
        butter(3, [180, 3800], fs=rate, btype="bandpass", output="sos"),
        rng.normal(size=len(time)),
    )
    clean *= (0.2 + 0.8 * np.sin(2 * np.pi * 1.7 * time) ** 2) * 0.12
    primary = clean.copy()
    primary[7 * rate : round(7.5 * rate)] = 0
    offset, drift, gain = 0.375, 120, 0.8
    source_time = np.arange(round((seconds + 1) * rate)) / rate
    backup = gain * np.interp(
        (source_time - offset) / (1 + drift / 1e6), time, clean, left=0, right=0
    )
    args.output.mkdir(parents=True)
    for name, audio in (("primary.wav", primary), ("backup.wav", backup), ("clean.wav", clean)):
        sf.write(args.output / name, audio, rate, subtype="FLOAT")
    manifest = {
        "fixture": "deterministic filtered numerical noise, not recorded speech",
        "seed": seed,
        "sample_rate": rate,
        "duration_seconds": seconds,
        "injected_dropout_seconds": [7.0, 7.5],
        "backup_offset_seconds": offset,
        "backup_drift_ppm": drift,
        "backup_gain": gain,
        "clock": "source_seconds = primary_seconds * (1 + drift_ppm / 1e6) + offset_seconds",
        "license": "MIT; generated numerical fixture from this script",
        "sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(args.output.glob("*.wav"))
        },
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
