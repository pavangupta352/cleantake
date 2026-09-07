# Take the edit with you

A CleanTake export preserves the duration of the primary recording. Only accepted repairs change the dialogue. Proposed, rejected and unresolved regions retain the primary audio.

Each export contains:

| Artifact | Contents |
|---|---|
| `dialogue.wav` or `dialogue.flac` | The accepted repair mix at 48 kHz, mono |
| `stems/` | Aligned, full-length source WAVs, including polarity and clock correction |
| `session.rpp` | Source tracks with editable volume envelopes for the repair decisions |
| `source-map.json` | Input and cache hashes, source clocks, accepted decisions, contributors, processing and warnings |
| `dialogue-finished.wav`, when requested | A separate loudness-adjusted copy |

WAV uses 32-bit floating-point PCM. It preserves the working samples outside repairs. FLAC uses 24-bit integer PCM, so its source map explicitly records quantization. An integer export that would exceed full scale fails with an actionable error. Originals are never overwritten.

An uncertain source has no aligned stem and is named in the export warnings. Resolve its alignment before using it in an accepted repair. Drift and polarity are applied to aligned stems; the session then uses those stems with ordinary editable gain envelopes.

An interoperability check opened a two-source session in Reaper 7.79 on macOS and rendered its gain-adjusted repair and crossfades. The 48 kHz, 960,000-frame output matched CleanTake's mix within 6.34 × 10⁻⁸ sample amplitude, consistent with the Reaper render's 24-bit quantization. This verifies that tested session and application version, rather than every Reaper configuration.

## Follow a sample back to its recording

The source map uses integer project frames and exclusive end bounds. At each crossfade it names both the primary and the alternate recording, including their respective weights. A weight's `start` and `end` describe the first and last included samples. Linear weights interpolate between those values.

`source_start_frame` and `source_end_frame` are continuous positions on the 48 kHz working cache. `read_start_frame` and `read_end_frame` identify the cache samples used for interpolation. `original_clock_start_frame` and `original_clock_end_frame` project those positions onto the decoded source stream's original sample rate.

Those original-clock coordinates are time references, not exact compressed packet positions or a claim about every resampler filter tap. The source's channel selection, downmix, input rate and cache hash are recorded separately. Clock correction currently uses linear interpolation; fractional positions can attenuate high frequencies.

## Optional loudness finishing

Finishing targets −16 LUFS integrated loudness with a −1 dBTP ceiling. It uses FFmpeg's two-pass `loudnorm` filter and measures the actual output separately with `ebur128`. The result records the measured values and whether linear or dynamic normalization ran. It keeps the same sample count and preserves the unmastered mix beside it. See the [FFmpeg loudness filter documentation](https://ffmpeg.org/ffmpeg-filters.html#loudnorm).

Large changes in recording level can leave the finished copy outside the integrated loudness target. The processing record reports `target_met`, a signed `loudness_error_lu` (measured minus target), and `loudness_tolerance_lu` of 0.5 LU. A `finished` status means the copy was rendered; inspect `target_met` before delivery. A target miss adds a warning to the export result, the source map and the processing record. Both audio files remain available for review, with no extra compression pass applied to force the target. True-peak verification allows 0.1 dB for the meter's one-decimal output and rejects an output above that limit.

A silent or unmeasurable input is retained with `status: "skipped"`, `target_met: false`, a null loudness error and an export warning. It is never reported as meeting the loudness target.

## Portable projects

A `.cleantake.zip` archive includes the saved decisions, complete original recordings and working caches. Treat it as a copy of the recordings themselves when sharing it. Import verifies the manifest, every member location and each media hash before creating a new project identity. It never replaces an existing project. Current decisions survive; undo history starts fresh in the imported copy.

Archives permit at most 64 members, 4 MiB of project metadata and 50 GiB of expanded data. Unsafe paths, links, duplicate members, missing media, unexpected files, encrypted archives and changed bytes are rejected. Cancellation removes unpublished temporary outputs.
