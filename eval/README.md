# Reproducible evaluation

This directory separates measured behavior from product claims. The checked-in [results](results/2026-09-08/summary.json) include missed repairs and uncertain sources. The full interpretation is in [EVALUATION.md](../docs/EVALUATION.md).

The corpus is **real AMI meeting audio with explicitly injected faults**. It is not a collection of naturally damaged production sessions. No raw corpus audio, third-party binaries or private project files are checked in here.

## Repeat the corpus run

Run from the repository root with the development environment installed and FFmpeg available:

```sh
uv sync --dev
uv run python eval/run.py prepare --corpus .local/evaluation
uv run python eval/run.py lock --output .local/evaluation-repeat
uv run python eval/run.py corpus --corpus .local/evaluation --output .local/evaluation-repeat
uv run python eval/summarize.py .local/evaluation-repeat
```

`prepare` downloads six original WAVs (181.3 MB), verifies their SHA-256 hashes, and recreates eighteen exact 60-second excerpts (34.6 MB). Files already present are verified and reused. Downloading the full corpus is unnecessary. Container hash differences are errors, not silently accepted substitutions. [corpus.json](corpus.json) records original URLs, hashes, channels, half-open intervals and the unchanged PCM preparation.

`lock` refuses to overwrite an existing experiment. It records the exact Git revision, dirty state, source-file hashes, protocol, corpus hashes, split and dependency versions **before audio is opened**. `corpus` refuses changed locked code and saves every case as it completes. A nonzero exit means a specified clock/rendering/shared-damage invariant failed, an input changed, or execution failed; it does not assert a minimum repair recall. Do not treat a zero exit code as proof of universal recovery.

The split was declared before algorithm tuning: ES2004a for development, IS1009a for reserved evaluation. Once a reserved meeting has been inspected, subsequent tuning against its results must call it development data and reserve new recordings. The published run did not alter the engine after opening IS1009a.

## What the fixed protocol executes

[protocol.json](protocol.json) defines all conditions without looking for successful repair spans:

- Four known-clock transformations of each of six headset excerpts: positive/negative offsets, positive/negative drift, and one polarity inversion. These use the same source recording to provide exact injected ground truth.
- Six three-microphone conditions per excerpt group: unmodified, primary dropout, primary clipping, dropout in every source, clipping operation on every source, and dropout plus alternate-recorder offset/drift.
- Two fixed half-second fault intervals, [20, 20.5) and [40, 40.5), in each minute. They can include silence, another speaker or overlap. Clipping multiplies samples by eight and clamps at ±0.25; quiet intervals may not reach that ceiling.
- Full output rendering with all donor proposals explicitly marked accepted by the harness, unchanged samples outside accepted intervals, unchanged duration, pending decisions leaving audio untouched, and independent reconstruction from the public source-map contract.

The harness acceptance is a test action. It does not represent a person listening, the application's default behavior, or an endorsement of every suggestion. Unmodified source material is not assumed to be free of organic defects, so unrequested flags are reported without inventing ground-truth false-positive labels.

## Repeat resource and regression checks

```sh
uv run python eval/long_session.py --seconds 1800 --output .local/long-session.json
uv run pytest tests/test_long_recordings.py -q
```

The long run creates nonperiodic numerical audio in a temporary directory, imports both 48 kHz tracks through FFmpeg, analyzes a known 375 ms offset, renders a reviewed repair plus aligned stems and a source map, verifies every output sample in chunks, and cancels a second export after bytes have been written. Temporary media is removed on exit. Allow about 3 GB of free space for the default run. It records process peak RSS and the largest completed child separately when supported; these include resident mapped pages and are not a constant-memory or concurrency guarantee.

[long_session.py](long_session.py) is a separate resource experiment. It does not read or tune on the reserved corpus. The five-minute regression uses disk-backed read-only arrays and irregular render chunks to catch altered seam behavior or content outside the accepted interval.

See [ATTRIBUTION.md](ATTRIBUTION.md) for corpus licensing and [BASELINE.md](BASELINE.md) for the exact scope of the Cleanroom comparator.
