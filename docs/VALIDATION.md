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

[Release 0.1.0](https://github.com/pavangupta352/cleantake/releases/tag/v0.1.0) is tagged at `2992f23`, which adds only three release documents to the verified software revision above. Its wheel is byte-identical to the independently checked and freshly installed wheel (`SHA256: 8bc8dcc3bd91f0bdd0e3ccfd6a5b9f9fcf536690d6cadac5f317443c170299b7`). The release includes checksums for the wheel, source archive and licensed portable demo.

## Native desktop · 0.2.0

[Native run 34177076224](https://github.com/pavangupta352/cleantake/actions/runs/34177076224)
completed successfully for commit
[`43ad902829714aeb02e9773b65abdb0cbc0b042f`](https://github.com/pavangupta352/cleantake/commit/43ad902829714aeb02e9773b65abdb0cbc0b042f)
on September 8, 2026 UTC. Each target built its native media tools and processing
runtime, created an installer, installed it and exercised the installed app.
The published native manifest identifies this build commit separately from later
release documentation.

| Actual verification environment | Architecture | Frozen runtime | Installed app | Native binaries inspected | Saved files retained after uninstall and reinstall |
|---|---|---|---|---|---|
| [macOS 14.8.9](https://github.com/pavangupta352/cleantake/actions/runs/34177076224/job/101908503298) | ARM64 | 13 passed | 9 passed | 121 | 24 / 24 |
| [macOS 15.7.9](https://github.com/pavangupta352/cleantake/actions/runs/34177076224/job/101908503216) | x64 | 13 passed | 9 passed | 121 | 24 / 24 |
| [Windows 11, build 26200](https://github.com/pavangupta352/cleantake/actions/runs/34177076224/job/101908503285) | ARM64 | 13 passed | 9 passed | 181 | 24 / 24 |
| [Windows Server 2025, build 26100](https://github.com/pavangupta352/cleantake/actions/runs/34177076224/job/101908503325) | x64 | 13 passed | 9 passed | 184 | 24 / 24 |
| [Ubuntu 24.04, glibc 2.39](https://github.com/pavangupta352/cleantake/actions/runs/34177076224/job/101908503350) | ARM64 | 13 passed | 9 passed | 122 | 24 / 24 |
| [Ubuntu 22.04, glibc 2.35](https://github.com/pavangupta352/cleantake/actions/runs/34177076224/job/101908503125) | x64 | 13 passed | 9 passed | 126 | 24 / 24 |

The frozen checks cover bundled-resource integrity, tool discovery with an empty
search path, first-run sample creation, actual spawned processing, export and
archive workflows, WavPack import, media-process cancellation, control-pipe EOF,
parent-crash cleanup and immediate reopening. All six bundles use the pinned
native CPython 3.12.13 distribution, build 20260504.

The nine installed-app gates check the actual packaged window with its sandbox
and context isolation enabled, first-run sample and advancing audio clock,
repair/undo/redo, native project history and text editing, WAV and archive save
flows, denied external navigation, single-instance focus, quit without orphan
workers, and reopening saved edits. File hashes establish that removing and
reinstalling each application retained all 24 saved workspace files. Dependency
inspection accepts only bundled components and operating-system libraries.

The Ubuntu x64 portable archive separately passed its nine app gates. On Ubuntu
24 ARM, the portable archive was refused by the system's SUID/user-namespace
sandbox policy; the Debian-installed app passed. That failure remains in the
report, with the portable route marked unsupported. Neither Linux portable
archive is included in the public 0.2.0 release. No operating-system sandbox or
protection policy was disabled.

[Checks run 34177076215](https://github.com/pavangupta352/cleantake/actions/runs/34177076215)
at the same commit also passed: **340 Python tests and 5 scoped skips** on each
of Linux Python 3.12, 3.13 and 3.14, macOS Python 3.12 and Windows Python 3.12.
Each job built the wheel/source archive and passed the fresh installed-package
smoke. Unix skips four Windows API checks; Windows skips four POSIX-only checks.
Each also skips one optional frozen-bundle diagnostic in the source-only job.
The browser workflow passed **24 tests across Chromium, Firefox and WebKit**, then
**8 against the bundled studio and its production security headers**.

The separately retained release wheel was installed in a fresh environment
outside the checkout on macOS ARM64. Its actual smoke verified the packaged
studio, sample repair, exact timing and archive round trip. The unchanged public
portable demo imported two sources and one accepted repair, then exported finite
48 kHz audio with 960,000 frames and the original samples preserved outside the
repair. This Python package check used the host's external FFmpeg, as documented
for that edition; native app checks used bundled tools.

The results above come from hosted build runners and a local package installation.
The native app ran with developer tools absent from its search path, but the
hosts themselves had build tools installed. This is not pristine physical-device
certification, a test of every OS version, or proof of audible output through
every sound device. The Windows per-user installer was exercised under the
runner account; consumer UAC interactions need separate observation.

Mac signatures passed integrity checks but are **ad-hoc**, with Gatekeeper
assessment returning **rejected**. The apps are not notarized. Windows app,
installer and uninstaller were all **NotSigned**; Linux packages are unsigned.
The additional Mac browser-download check below observed successful per-app
approval. Consumer Windows SmartScreen/Smart App Control acceptance has not
been established. See the
[desktop guide](DESKTOP.md) for conditional platform instructions and limits.

`NATIVE-RELEASE.json` and `SHA256SUMS` accompany the installers. The native source
supplement preserves the exact component-source inventories and the runtime,
installed-app and installer reports used by
[release assembly](../packaging/release/README.md). Hash correspondence does not
upgrade unsigned or ad-hoc artifacts to a verified-publisher release.

### Browser download and first open on Mac

On September 8, 2026, the public `CleanTake-0.2.0-mac-arm64.dmg` was downloaded
through a browser and installed through Finder on the maintainer's Mac running
macOS 26.5.2 ARM64. Its 188,982,117 bytes matched the published SHA-256:
`6e6d7ec5576841ba249177bdb5c5002d179191082bfb6759d26167ec12aea3ca`.
All 681 regular files and 14 symlinks in the Applications copy matched the
mounted installer, and the ad-hoc signature passed integrity verification.

macOS blocked the first open. The observed route was **Privacy & Security →
Open Anyway**, a second **Open Anyway** confirmation, and an administrator
authentication prompt. After authentication was completed outside the test
controls, the same pending application process started normally. Download
quarantine was retained and Gatekeeper assessments remained enabled; no global
security setting was changed. This verifies that approval route on this Mac,
not notarization or acceptance under every managed-device policy.

The installed app preserved all nine existing project files, totaling 9,289,112
bytes, before the sample was edited. The visible workflow then verified:

- Original, Source and Repair playback with advancing audio clocks.
- Accepting the sample repair, native Undo and native Redo, each saving exactly
  one revision; the final project had one accepted repair at revision 6.
- Saving WAV and portable project archive files through the native save dialogs.
  The WAV contained 960,000 finite mono frames at 48 kHz and matched the expected
  rendered audio exactly at FLOAT32 precision. All 936,086 frames outside the
  repair were identical to the primary cache. The archive's five members passed
  integrity checks and preserved both original recordings, caches and decisions.
- Native Quit leaving no application, backend or helper processes, then ejecting
  the installer and reopening CleanTake from Applications. The accepted repair
  remained visible and the saved project was unchanged; no repeat trust warning
  appeared.

Only the included sample was edited. This manual check complements the six
native CI targets; it does not certify every computer or audio device, or an
independent listening preference.
