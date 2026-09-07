# Self-contained desktop implementation plan

**Goal:** Publish native CleanTake installers that include all application
runtimes and media tools, with actual platform and first-run evidence.

**Architecture:** Electron owns the desktop window and backend lifecycle. A
native one-folder PyInstaller bundle serves the existing studio and runs the
existing processing workers using bundled FFmpeg/FFprobe.

**Tech stack:** Python 3.12.13, PyInstaller 6.22.2, FFmpeg 9.0.1,
Electron 44.2.0, electron-builder 26.16.1; the existing locked processing stack.

**Spec:** [Native distribution](../NATIVE-DISTRIBUTION.md).

## Global constraints

- Preserve the complete 0.1.0 workflow, source provenance, private storage,
  processing boundaries, licensing, and Pavan's maintainer identity.
- Target version 0.2.0. Do not alter the published 0.1.0 artifacts or tag.
- Native builds for macOS, Windows, and Linux, each x64 and ARM64. A published
  compatibility claim requires actual matching-architecture evidence.
- No user Python, Node, FFmpeg, model download, or special GPU computing driver.
- No sandbox/security bypass, unsigned auto-update, global PATH mutation,
  silent source-tool fallback in a frozen bundle, or user-project deletion.
- Observe failing behavioral regressions before implementation. Test real
  frozen processes, media, installers, and desktop windows; configuration and
  documentation alone do not need tests that merely mirror their contents.
- Each component ends with targeted verification and independent review.

## Task 1: Reproducible standalone media tools

**Owns:** `scripts/build_media_tools.py`, `packaging/ffmpeg/**`,
`tests/test_media_build.py`, media build/source documentation.

- [ ] Implement a hash-verified official source download and safe extraction.
- [ ] Build native FFmpeg/FFprobe with the specified software-only LGPL setup,
  using Clang on macOS, MSYS2 UCRT64/CLANGARM64 on Windows, and a suitable native
  static toolchain on Linux. Record every effective flag and compiler version.
- [ ] Stage `bin/ffmpeg[.exe]`, `bin/ffprobe[.exe]`, notices, immutable manifest,
  and corresponding-source provenance beneath an explicit output directory.
- [ ] Verify executable architecture, actual shared dependencies, effective
  license, real audio/video demuxing, and required finishing filters.
- [ ] Preserve exact original source and reconstruction instructions for release
  redistribution. Report failures without weakening feature coverage.

## Task 2: Frozen backend, tool discovery, and desktop protocol

**Owns:** `src/cleantake/runtime.py`, `src/cleantake/desktop.py`,
`src/cleantake/{media,exports,cli}.py`, focused tests,
`packaging/runtime_entry.py`, `packaging/cleantake.spec`,
`scripts/build_runtime.py`, `scripts/smoke_runtime.py`.

- [ ] Add regressions for absolute bundled tool discovery and missing/corrupt
  tools without PATH fallback; retain source/wheel behavior.
- [ ] Correct the WavPack `wv` format-whitelist mismatch with a real fixture.
  Hide Windows media subprocess windows while preserving cancellation.
- [ ] Implement early freeze dispatch, first-run sample initialization under the
  workspace lease, structured ready/error output, stdin shutdown/EOF handling,
  and meaningful lifecycle tests with real spawned jobs.
- [ ] Freeze all runtime libraries, static assets, sample media, metadata, and
  notices. Keep the console backend and use the spec's onedir resource layout.
- [ ] Run the actual frozen backend with developer runtimes unavailable on PATH;
  exercise import/analyze/repair/export/archive/restart/cancellation and cleanup.

## Task 3: Desktop window and installation experience

**Owns:** `desktop/**`, scoped native surface brief and design additions.

- [ ] Reuse the studio's reviewed visual world and native window controls. Read
  the craft floor before adding the launch surface; keep setup copy concise.
- [ ] Implement strict backend handshake validation, local-only navigation,
  sandboxed renderer, denied permissions, native exports, normal menus,
  single-instance focus, sensible window bounds, and shutdown/error recovery.
- [ ] Add meaningful node tests for process/protocol/security behavior and
  packaged Electron tests for the complete sample/edit/export/quit path.
- [ ] Configure offline per-user NSIS, architecture-specific DMGs, and Linux
  Debian/portable targets with complete resources and license notices.
- [ ] Inspect actual desktop launch/editing states in one bounded batch, resolve
  material findings, obtain a fresh scoped finish review, and document the built
  native shell without reopening the completed studio design.

## Task 4: Native builds, installation checks, and signing

**Owns:** `.github/workflows/native.yml`, native validation helpers,
packaging manifests, signing integration, release assembly.

- [ ] Lock native build dependencies and run six explicit architecture jobs.
  Cache only hash-keyed build inputs; preserve complete build manifests.
- [ ] Verify frozen payloads, dependency closure, installed native apps, actual
  audio playback and worker lifecycle on each target. Test Linux package
  dependencies and sandbox setup on the declared distribution base.
- [ ] Verify installer behavior and retained project data on uninstall/reinstall.
- [ ] Integrate available signing/notarization credentials securely; record
  actual trust results and any remaining publisher-verification prompts.
- [ ] Resolve material review/CI findings with regressions and bounded rechecks.

## Task 5: Public distribution and continuity

**Owns:** README, install/desktop guides, changelog, licenses, public validation,
GitHub release assets, private continuity records.

- [ ] Put native downloads first, with clear operating-system/architecture
  choices, actual system requirements, and advanced wheel/source alternatives.
- [ ] Publish 0.2.0 only with verified native artifacts, source, license notices,
  complete checksums, and honest signing/platform evidence.
- [ ] Download published assets anonymously, compare hashes, and exercise the
  installed release. Keep 0.1.0 available as historical release evidence.
- [ ] Reconcile the plan and memory with exact SHAs, artifact URLs, CI runs,
  running processes and any external signing input still required.

This plan extends the already completed recovery product. It does not turn
views, stars, universal hardware compatibility, or warning-free installation
into claims without evidence.
