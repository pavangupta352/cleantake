# Evaluation — 8 September 2026

CleanTake completed a frozen, reproducible corpus run and a 30-minute project resource check. The results support exact source rendering and conservative recovery on some controlled faults. They also show missed faults, uncertain microphones and unrequested flags. They do not establish organic-damage recovery, listening preference, editor-time savings or superiority over another product.

## Identity and protocol

The [experiment lock](../eval/results/2026-09-08/lock.json) records Git revision `bde2824`, the dirty source snapshot, SHA-256 hashes of every engine/evaluation file, corpus identifiers, the fixed protocol and runtime versions. The lock was written before the reserved meeting was read. The engine and locked runner hashes remained unchanged throughout the corpus experiment. The timestamp is recorded in UTC; this report is dated in India time.

[ES2004a was assigned to development and IS1009a to reserved evaluation](../eval/corpus.json) before engine tuning. The run uses every previously prepared one-minute span: 120–180, 300–360 and 420–480 seconds of each meeting, with headset, lapel and room-array channels. No interval was dropped for a poor result and no engine change followed inspection of the reserved meeting.

The corpus comprises real, simultaneous AMI recordings at 16 kHz. Dropouts, clipping, shifts and drift are injected by the [separate fixed protocol](../eval/protocol.json). Both half-second fault intervals are fixed at 20 and 40 seconds into each minute. Some intervals can contain little target-speaker speech; they were not selected by listening for recoverable words. These are controlled-fault results, not organic incident reports. [Provenance and license](../eval/ATTRIBUTION.md) accompany the manifests; no full original recordings are checked into the repository.

## Known recording clocks

Each of the six headset excerpts was independently transformed into four alternative recordings: +375 ms, −220 ms, +375 ms/+120 ppm with inverted polarity, and −220 ms/−80 ppm. This same-microphone experiment has exact injected clock ground truth. It is separate from the distinct-microphone repair experiment.

| Split | Passed offset ≤2 ms and endpoint error ≤3 ms | Maximum offset error | Maximum 60-second endpoint error |
|---|---:|---:|---:|
| Development | 12/12 | 0.0030 ms | 0.0079 ms |
| Reserved evaluation | 12/12 | 0.0101 ms | 0.0028 ms |

All 24 cases returned an aligned status and correct polarity. These short, correlated cases do not establish performance on independent hardware clocks, long pauses, changing drift or unrelated recordings. Distinct headset/lapel/array comparisons have acoustic-path delay and cannot supply equally exact clock ground truth. Their individual estimates and nominal errors are retained in the [full results](../eval/results/2026-09-08/corpus-results.json).

## Recovery and conservative failures

Each row below covers three one-minute recordings and **3.0 seconds of fixed injected intervals**. “Covered” means the portion of those intervals inside a donor proposal. It is not an intelligibility score, word recall or editor acceptance rate.

| Split | Condition | Donor proposals overlapping injected intervals | Injected interval covered |
|---|---|---:|---:|
| Development | Primary dropout | 0 | 0.00 / 3.00 s |
| Development | Primary clipping operation | 0 | 0.00 / 3.00 s |
| Development | Dropout with +375 ms/+120 ppm donors | 0 | 0.00 / 3.00 s |
| Reserved evaluation | Primary dropout | 4 | 2.00 / 3.00 s |
| Reserved evaluation | Primary clipping operation | 7 | 1.32 / 3.00 s |
| Reserved evaluation | Dropout with +375 ms/+120 ppm donors | 4 | 2.00 / 3.00 s |

Clipping multiplies the selected samples by eight and clamps them at ±0.25. A quiet interval can remain below that ceiling; the table reports the requested operation, not a guarantee that every selected sample was saturated. The application left many cases for manual review. On the unmodified development recordings, only 3 of 6 donor alignments were accepted; on the reserved recordings, 5 of 6 were accepted. This is a useful limit of the current conservative synchronizer, especially for room-array and off-microphone speech.

There were **zero donor proposals on all six unmodified inputs**, but one reserved excerpt, IS1009a 300–360, received seven unresolved clipping flags. The recordings have not been independently adjudicated as defect-free, so these are unrequested flags rather than verified false positives.

The clipping and shared-clipping variants of that same reserved excerpt also enabled a donor proposal at original meeting time **308.36–308.44 seconds**, outside the injected intervals. The harness accepted it to exercise rendering, changing 80 ms there. This is a disclosed nonlocal suggestion change and needs listening review; it is not counted as recovered injected damage. Pending or rejected proposals never alter the export.

For both fault classes applied to every source, **no donor proposal covered the shared injected intervals** in any of the six recording groups. Shared silence remained unrecovered. The clipping operation applied to all sources is subject to the quiet-sample caveat above; it is not evidence for every possible all-source damage pattern.

## Content and source traceability

Across all **36 three-microphone condition runs**, output duration, finite samples, exact primary samples outside accepted edits, and unchanged output when no edits were accepted all passed. Every rendered result was independently rebuilt from source-map clocks, gains and contributor weights; the largest absolute difference was **2.22 × 10⁻¹⁶**. The harness explicitly accepted donor proposals for this check. No person is represented as having approved those edits.

The unmodified excerpts include publisher-annotated laughter, vocal events and simultaneous speakers. All primary samples in those excerpts were retained. The [annotation summary](../eval/annotation-summary.json) describes that content; it is not a listener judgment or a separately annotated interruption benchmark. Nothing in this run authorizes deleting breaths, pauses, interruptions, laughter or overlapping voices.

The corpus runner operates directly on original-rate PCM to isolate the engine. Full 48 kHz FFmpeg ingestion is covered by the separate project integration test and the long-session experiment. The [compact summary](../eval/results/2026-09-08/summary.json) and [complete case records](../eval/results/2026-09-08/corpus-results.json) retain missed intervals, every proposal, uncertain alignments and render identities.

## Long-session resources

The [resource experiment](../eval/long_session.py) processes two **30-minute, 48 kHz** numerical recordings with a known 375 ms offset and an injected half-second dropout. It uses the real project store and FFmpeg importer, then exports a reviewed repair, two aligned stems, a Reaper session and source map. The resource export uses an explicit manual clock/accepted interval so its coverage does not depend on automatic recall. It also records the engine's actual analysis result separately.

The machine was macOS 26.5.2 on arm64, Python 3.12.13. The final recorded run took 21.15 seconds total, with 5.97 seconds for import, 6.42 for analysis and 4.77 for export. Peak process RSS was 742.86 MiB; the largest finished child peaked at 17.03 MiB. Exact phase timings, peak resident memory and source hashes are in [long-session.json](../eval/results/2026-09-08/long-session.json). This run generated approximately 0.69 GB of source WAVs and exported approximately 1.04 GB of artifacts. Every one of the 86,400,000 dialogue frames was checked in bounded chunks. Duration was retained, samples outside the accepted interval were exact, and the project did not change during export. The maximum absolute difference from the float64 render was 6.81 × 10⁻⁹, consistent with the FLOAT WAV conversion.

A second export was cancelled only after actual audio bytes had been written. It removed the temporary output and staging directory and preserved the project manifest. The measured callback-to-completion latency was 2.06 ms. The recorded cancellation latency measures the cooperative export callback to completion; it does not claim browser-click, stalled-storage, process-kill or four-hour session latency. Peak RSS includes resident mapped cache pages, and the largest completed FFmpeg child is reported separately. It is not an aggregate concurrent peak or a fixed memory ceiling for arbitrary recording lengths.

This is one measured machine and one numerical long session. No long-session listening, four-hour stress guarantee, network-storage benchmark or cross-platform resource comparison is claimed.

## External comparison and open evidence

The separate [natural-fault intake packet](../eval/natural/README.md) records a
publisher-documented AMI microphone-loss candidate and a prospective meeting-group
split. Its affected channel and event time remain unidentified; no candidate
audio has been downloaded or evaluated. It adds no result to this study.

The [Cleanroom baseline record](../eval/BASELINE.md) distinguishes its actual multitrack alignment/mix workflow from source-based repair and single-file mastering. A published release is not proof that its benchmark ran. The executed single-file baseline exposed a CleanTake finishing target miss: an output measured −18.7 LUFS against a −16 LUFS request. A [separate independent recheck](../eval/results/2026-09-08/baseline-mastering-corrected.json) verified the reporting correction: `target_met: false`, a −2.7 LU error, ±0.5 LU tolerance and a warning propagated through the export response and source map. The audio remains byte-identical at −18.7 LUFS / −1.0 dBTP; loudness attainment has not improved. The missing-warning defect is resolved, while the target miss remains an explicit limitation. The initial evidence is preserved and is separate from the passing core-rendering checks above. Only observed operations and output are reported there.

The following remain evidence gates before making broader claims:

- Untuned, naturally damaged sessions with owner permission and intact comparison material where possible.
- Independent listeners comparing level-matched, blinded audio, including rejected or harmful repairs.
- Real editors completing the same rescue task, with intervention counts and measured elapsed work.
- Broader microphone, room, hardware-clock, language and long-session coverage.

Reproduction commands, exact source downloads and interpretation rules are in [eval/README.md](../eval/README.md). A passing engineering invariant is evidence for that invariant, not a substitute for those gates.
