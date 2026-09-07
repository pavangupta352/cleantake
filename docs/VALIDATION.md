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

## Verified build: 65a836d

[Checks run 34163316857](https://github.com/pavangupta352/cleantake/actions/runs/34163316857) completed successfully for commit [`65a836d549f7f6c3e632ba3f7dd2689c4c6a3559`](https://github.com/pavangupta352/cleantake/commit/65a836d549f7f6c3e632ba3f7dd2689c4c6a3559). These are observed results from the hosted runners, collected on September 7, 2026 UTC.

| Native environment | Python | Python tests | Package build and clean installation |
|---|---|---|---|
| [Ubuntu 24.04.4](https://github.com/pavangupta352/cleantake/actions/runs/34163316857/job/101869389538) | 3.12.3 | 242 passed | Passed |
| [Ubuntu 24.04.4](https://github.com/pavangupta352/cleantake/actions/runs/34163316857/job/101869389659) | 3.13.15 | 242 passed | Passed |
| [Ubuntu 24.04.4](https://github.com/pavangupta352/cleantake/actions/runs/34163316857/job/101869389589) | 3.14.7 | 242 passed | Passed |
| [macOS 26.6.2, arm64](https://github.com/pavangupta352/cleantake/actions/runs/34163316857/job/101869389542) | 3.12.10 | 242 passed | Passed |
| [Windows Server 2025, build 26100](https://github.com/pavangupta352/cleantake/actions/runs/34163316857/job/101869389637) | 3.12.10 | 238 passed, 4 skipped | Passed |

Each native job ran Ruff, `uv run pytest --cov=cleantake --cov-report=term-missing`, built the wheel and source archive, and ran `scripts/smoke_installed.py` against a fresh wheel installation outside the checkout. Each Python run reported two upstream deprecation warnings. Windows skipped the POSIX process-tree inspection, two POSIX directory-permission regressions, and the directory-synchronization regression; these four checks passed on Linux and macOS.

The [browser job](https://github.com/pavangupta352/cleantake/actions/runs/34163316857/job/101869389461) passed all **24 tests across Chromium, Firefox and WebKit** in 4.3 minutes, then all **8 Chromium tests against the bundled application and its production security headers** in 1.2 minutes. Both runs used the real local server and recording fixtures. The job also verified that the committed studio assets exactly matched a build from the locked frontend dependencies.

The Linux Firefox audio probe established the runner setup requirement: before PulseAudio started, an actual user gesture left `AudioContext.resume()` pending, with state `suspended` and clock `0`. After starting a PulseAudio 16.1 null sink, the same probe resumed successfully, entered `running`, and advanced to `0.1131972789` seconds. The complete browser assertions then passed unchanged.
