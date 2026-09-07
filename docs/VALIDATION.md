# Validation contract

The thresholds below are chosen engineering acceptance targets, not established product results. Results must name the exact revision, platform, input set and command.

| Area | Required evidence |
|---|---|
| Alignment | Positive/negative offsets, different start/end coverage, level differences, polarity inversion, mixed sample rates and drift; known synthetic offset error ≤2 ms on supported correlated fixtures; drift correction residual ≤3 ms where enough speech anchors exist; unrelated/silent inputs remain uncertain |
| Damage | Dropouts and clipping with an intact alternate; clean passages and shared silence do not generate accepted edits; every-source-damaged passages cannot be labeled recovered; noisy/laughter/overlap examples have documented outcomes |
| Rendering | Original samples retained outside repair/fade support before finishing; output duration unchanged; donor coverage bounds enforced; finite output, bounded gain, no hard clipping introduced; both seam contributors appear in map |
| Persistence | Save/reopen preserves choices; undo/redo and revision conflicts; missing/changed sources detected; interrupted processing cannot publish partial results; archive round-trip with path attacks rejected |
| Transcripts | Explicit milliseconds preserved exactly; generic units declared; raw word timestamps and estimated flags retained; transcript text never changes audio boundaries |
| Local API | Host/origin/token enforcement, path traversal/symlink protections, invalid IDs, unsupported/malformed files, upload/job bounds and cancellation behavior |
| User workflow | Browser test on real server: import → analyze → compare → accept/reject → manual correction → save/reopen → export; keyboard operation and accessible labels; responsive usable editor and no console errors |
| Packaging | Build wheel and source archive; install wheel in a fresh environment and launch packaged studio; CLI help/doctor and a real repair/export run; Linux/macOS/Windows CI results recorded separately |
| Long recordings | Process a documented long recording with bounded-memory caches; record elapsed time, maximum resident memory and cancellation response; do not infer resource guarantees from a short clip |
| Real recording evaluation | Real simultaneous microphones with licensed provenance and documented injected faults; reserve meetings/spans before tuning; show failures and manual intervention; generated speech is not used as real human evidence |
| External comparison | Exercise a named current Cleanroom baseline where comparable; distinguish mastering from rescue. Independent editor timing and blind listening require actual participants and records; never invent these outcomes |

## Fixture tiers

1. Deterministic numerical fixtures: known shifts, drift, polarity, clipping and dropped intervals. These establish algorithmic behavior.
2. Licensed recorded speech with controlled damage: original and manipulated versions plus exact operation list. These establish reproducible recovery on real microphones under known faults.
3. Untuned real damaged sessions: contributor-authorized originals, listening decisions and failure cases. These establish broader usefulness.
4. Independent users: actual completion, intervention counts, editing time and blinded listening choices. These establish usability and preference.

Each tier answers a different question. Do not relabel tier 1 or 2 as organic damage or independent validation. Do not publish private user media without explicit permission.

