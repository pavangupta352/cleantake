# Cleanroom baseline record

A real single-file mastering baseline was executed through the official Cleanroom macOS application. A multitrack alignment/mix comparison was **not executed**. This record does not establish comparative rescue quality, listening preference or editing speed.

## Exact application and scope

- Repository: [bluejacketblackhawk/cleanroom](https://github.com/bluejacketblackhawk/cleanroom).
- Published release: [v0.1.1](https://github.com/bluejacketblackhawk/cleanroom/releases/tag/v0.1.1), tag commit `50d8a0fd954bfa4380e394d0f673d1a2e666a6ae`.
- Asset: `Cleanroom-macos-arm64.dmg`, 92,892,805 bytes; SHA-256 `f68b9715f256c7552f772ca48438ff91c826fcd1e40f9acdc743091b77bd825c`, matching the publisher's release checksum file.
- The copied private application passed macOS deep/strict code-signature verification. Its visible interface reported **v0.1.0**, despite the release asset being distributed under v0.1.1. Both identities are retained rather than silently reconciled.
- The release bundle contains the desktop application and media/model helpers, but no standalone `anvil` CLI. Nothing was installed into the system Applications folder or redistributed in CleanTake.

The [pinned CLI source](https://github.com/bluejacketblackhawk/cleanroom/blob/50d8a0fd954bfa4380e394d0f673d1a2e666a6ae/crates/anvil-cli/src/main.rs) supports single-file mastering. The [multitrack library](https://github.com/bluejacketblackhawk/cleanroom/blob/50d8a0fd954bfa4380e394d0f673d1a2e666a6ae/crates/anvil-multitrack/src/lib.rs) implements alignment, drift handling, bleed control, ducking and mixdown. Those capabilities must not be described as absent merely because the CLI lacks a multitrack subcommand.

The desktop multitrack screen was opened during this run. Its add-track route requires a native file drop; the global file picker opens the Master screen instead. A multitrack run was not completed within the available interaction path. Building a library harness was inspected but not attempted: this machine had no Rust toolchain, and the actual dependency path includes DSP, model-runtime and binary/model build dependencies. These are execution limits of this experiment, not measured failures of Cleanroom's multitrack engine.

## Executed workflow

The source was the unmodified AMI development excerpt **ES2004a, headset 0, original seconds [300, 360)**: mono 16 kHz PCM16, SHA-256 `243024bd5e1795cb8b50f27ccace25c0452d702dbb28b9bb901e2f7608640668`.

In Cleanroom, onboarding was dismissed, the file was selected using the normal file picker, and Master was run using the default **Standard tier** and **Podcast Stereo preset, −16 LUFS**. The visible processing report listed an 80 Hz high-pass, mouth/impulse repair, DeepFilterNet3, −6 dB breath processing, de-essing and neutral automatic EQ. The finished file was exported as mono WAV; the application reported successful completion. The actual output was then independently decoded and metered.

CleanTake imported the exact same original into its normal 48 kHz working cache and exported with finishing enabled and **no repair decisions**. Its chain used two-pass FFmpeg loudness normalization targeting −16 LUFS, −1 dBTP and LRA 11. It does not reproduce Cleanroom's enhancement chain. Cleanroom exported PCM16; CleanTake exported floating-point WAV. These differences are part of the comparison, not hidden controls.

## First measured outcome

The [initial measurement record](results/2026-09-08/baseline-mastering.json) is retained, including a CleanTake target miss discovered by this experiment.

| File | Duration | Rate / format | Integrated loudness | True peak | Loudness range |
|---|---:|---|---:|---:|---:|
| Original | 60.000 s | 16 kHz / PCM16 mono | −32.9 LUFS | −8.1 dBTP | 15.3 LU |
| Cleanroom Standard/Podcast | 60.000 s | 48 kHz / PCM16 mono | −16.1 LUFS | −1.0 dBTP | 20.6 LU |
| CleanTake initial finishing | 60.000 s | 48 kHz / float mono | **−18.7 LUFS** | −1.0 dBTP | 14.0 LU |

Measurements use the actual exported WAVs and the same local FFmpeg EBU R128 meter. Cleanroom's displayed post-processing LRA was 15.2 LU; the independent output measurement was 20.6 LU. The different numbers are reported without assuming the display and independent meter use identical definitions or data.

CleanTake's first output missed the requested loudness by 2.7 LU and still reported `status=finished` without a warning. The source map did record the actual measured −18.7 LUFS. The missing-warning defect was subsequently corrected and independently rechecked below. The initial result remains in the evidence record.

These measurements do not say which file sounds better. Additional processing can alter noise, breaths, transients, timbre and dynamics. No blind listener or editor-time outcome was collected.

## Reporting correction independently verified

A [separate same-input recheck](results/2026-09-08/baseline-mastering-corrected.json) verified the corrected reporting through the real importer/exporter and the same independent meter. The finished file still measures **−18.7 LUFS / −1.0 dBTP**; the requested −16 LUFS target is **still unmet**. The processing record now reports `target_met: false`, a signed error of −2.7 LU and a tolerance of ±0.5 LU. Its warning names the measured and requested levels and reaches the export response, processing record and top-level source map.

`status: finished` continues to mean that a rendered file exists. It does not mean the loudness target was attained; consumers must inspect `target_met` and warnings. This resolves the missing-warning defect without claiming improved loudness attainment.

The corrected finished WAV has the same SHA-256 as the initial output: `e772d9b229d8915e00279f9512149a8e1156804736354ee9a3c00cd031baa75a`. The unmastered PCM is also sample-identical, and the 60-second duration and original source hash are unchanged. The correction changed reporting, not this audio. Four targeted finishing regressions passed. The recheck records its exact source hashes, measurements and all eleven verification checks; the original failure records were preserved.

## Repeat a same-input measurement

1. Prepare the licensed AMI inputs using [README.md](README.md).
2. Open `ES2004a_0300-0360_Headset-0.wav` in the specified Cleanroom release, choose the settings above, run Master and export WAV. Record the actual version, settings and destination.
3. From the CleanTake repository, run:

```sh
uv run python eval/compare_mastering.py \
  --input .local/evaluation/excerpts/ES2004a_0300-0360_Headset-0.wav \
  --comparison /path/to/cleanroom-output.wav \
  --output .local/mastering-repeat
```

The output directory must be new. The helper uses CleanTake's real importer/exporter, records source and output hashes, preserves the source map and measurements, and saves independent FFmpeg meter logs. Only the measurements and settings are public here; neither third-party application binaries nor full raw corpus/output media are redistributed.

A future multitrack comparison must execute the actual desktop path or a clearly identified harness calling the real `align_buffers`/`mix_buffers` APIs. A single-file mastering result cannot substitute for that work.
