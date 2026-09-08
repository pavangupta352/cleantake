# Assemble a native release

`scripts/assemble_native_release.py` validates downloaded Actions artifacts and
creates a **new** release directory. It does not build, run tests, sign, publish,
or create attestations. Run it from the release checkout so its trusted FFmpeg
and SoundFile source pins match the intended release.

## Inputs

Download artifacts from the explicitly selected, successful native workflow run
using authenticated GitHub CLI. Set `CLEANTAKE_NATIVE_RUN_ID` to the reviewed run
ID and `CLEANTAKE_RELEASE_COMMIT` to its complete 40-character commit first.

```sh
gh run view "$CLEANTAKE_NATIVE_RUN_ID" --json headSha,conclusion,url
gh run download "$CLEANTAKE_NATIVE_RUN_ID" --pattern 'native-*' --dir .local/native/downloads
uv run python scripts/assemble_native_release.py \
  --inputs .local/native/downloads \
  --version 0.2.0 \
  --commit "$CLEANTAKE_RELEASE_COMMIT" \
  --retained .local/release/validated-python-assets.json \
  --electron-source build/native/electron \
  --output .local/release/native-0.2.0
```

The input directory must contain exactly twelve folders:
`native-packages-PLATFORM-ARCH` and `native-evidence-PLATFORM-ARCH`, for
`mac`, `win`, `linux` and each of `x64`, `arm64`. Do not merge artifact contents
across their named folders or combine downloads from different runs.

Actions preserves these package paths:

```text
native-packages-PLATFORM-ARCH/
  dist/native/CleanTake-VERSION-PLATFORM-ARCH.EXT
  build/native/media/{manifest.json,licenses/,source/}
  build/native/soundfile/{manifest.json,licenses/,source/}
```

The x64 Debian artifact uses `amd64` in its filename. Evidence paths are:

```text
native-evidence-PLATFORM-ARCH/
  evidence/runtime.json
  evidence/install.json
  evidence/installed-app/desktop-smoke.json
  runtime/cleantake-runtime/runtime-manifest.json
  media/manifest.json
  soundfile/manifest.json
```

Build logs and other evidence files may also be present. The assembler preserves
the verified JSON reports in the source asset, including the original installer
report with dependency and retention details. Screenshots and generated audio
remain in the Actions evidence artifact.

## Required gates and correspondence

All six targets are required. Each runtime and app report must record the exact
requested commit, expected platform and architecture. The runtime's top-level
`version`, runtime manifest's `cleantake_version`, app's
`packaged_first_launch_empty_PATH.version`, and installer filename must agree
with `--version`.

Each frozen runtime must pass all thirteen gates, including export, WavPack
import, real media-tree cancellation, owner-crash cleanup and immediate reopen.
Each installed app must pass all nine gates, including actual audio playback,
native history/text editing, downloads, saved work and process cleanup. Its
launch report must confirm a packaged app with sandbox/context isolation and
without renderer Node integration. Installer evidence must report overall
success, actual installed-app success, matching dependency architecture, and
successful uninstall/reinstall retention of saved files.

The installer bytes must match the SHA-256 in that install report. The frozen
runtime manifest must match the hash in its runtime report. Its embedded media
and SoundFile manifests must equal both the package and evidence copies.
FFmpeg sources, signatures, keys and Linux musl sources must match the release
checkout's pins. Every source file and license is checked against its complete
inventory; SoundFile archives, library identity, component notices and upstream
recipe hashes are also checked against the checkout's exact pins.

Missing reports, failed/skipped required gates, mixed commits or versions,
duplicate gates/JSON fields, changed files, missing sources, unknown installers,
unsafe paths, symbolic links and special files cause rejection. Old evidence
without commit fields or a retained runtime manifest is rejected; the assembler
does not infer those missing facts. It checks content consistency; the recorded
Actions origin comes from the authenticated download, not a newly fabricated
attestation.

`--electron-source` is also mandatory. It points to the common verified
`manifest.json`, `licenses/` and `source/` stage produced by
`scripts/stage_electron_sources.py`. The assembler calls that stage's source
validator, requires its version to match the checked-in Electron package lock,
and checks its complete inventory before preserving it under `electron/` in
the source asset. Electron's separate LGPL FFmpeg and other copyleft components
are not covered by the standalone media-tool or SoundFile sources.

## Previously validated Python and demo files

`--retained` requires an explicit JSON declaration for exactly one wheel, source
distribution and demo archive. These are preserved without rerunning their prior
checks. Their version must match this release. Paths are relative to the
declaration file; paths may not traverse upward or pass through symbolic links.

The declaration has `schema_version: 1` and an `assets` array. Each asset contains:

| Field | Required value |
| --- | --- |
| `kind` | `wheel`, `sdist` or `demo`, each exactly once |
| `path` | Existing validated file; basename is `cleantake-VERSION-py3-none-any.whl`, `cleantake-VERSION.tar.gz` or `cleantake-demo.zip` |
| `version` | The exact release version |
| `status` | `passed`, entered after its prior validation succeeds |
| `bytes`, `sha256` | Byte length and lowercase SHA-256 of that validated file |
| `validation` | Object with `path`, `bytes`, `sha256` identifying the preserved actual validation report or log |

Do not generate a passing declaration before running the corresponding checks.
The assembler verifies the declared file/report hashes and labels them as
explicitly supplied prior validation; it does not turn them into build
attestations or claim those checks ran during assembly. The declaration and
validation reports are retained inside the source asset.

## Portable Linux packages

Linux `.tar.xz` app packages are excluded by default, even when a file is present.
The summary records their exclusion. Primary installer evidence must still
report success; an old failed overall install run is not relabeled successful.

To include portable apps, add `--include-portable`. Both Linux architectures must
then have their own successful `portable-desktop` install gate, full
`evidence/portable-app/desktop-smoke.json`, and a matching
`install.json.portable` object containing the exact archive name and SHA-256.
Successful Debian-package testing alone cannot qualify a portable archive.

## Output and preservation

The assembler records source and evidence hashes before validating any target
or retained asset, then carries those same hashes through archive creation.
It creates the release in a temporary sibling directory, copies and rechecks artifacts,
creates and rechecks the source archive, writes the summary/checksums, and moves
the completed directory into place. An existing output is never replaced;
rejection leaves no partial release directory.

The result contains verified native installers, the three explicitly retained
Python/demo assets, and:

- `CleanTake-VERSION-native-sources.tar.xz`: every target's complete FFmpeg and
  SoundFile source/recipe/notice payload, all original source manifests, the
  common Electron corresponding-source stage, the verified runtime/app/install
  evidence, and prior Python/demo validation.
  Sources remain separately identifiable per target. A `SOURCE-INDEX.json`
  records every member's SHA-256 and size. Archives are preserved byte for byte;
  the assembler never extracts their untrusted contents onto disk.
- `NATIVE-RELEASE.json`: exact native commit/version, platforms, verified gate
  names, installer hashes, signing status, runner information, report hashes,
  retained-asset validation provenance, source-asset hash and exclusions.
- `SHA256SUMS`: every release file except the checksum file itself.

Tar headers use stable ownership and timestamps. Original source, notice and
report bytes are preserved. Signing/trust limitations in the native evidence
remain visible; assembly does not upgrade an ad-hoc or unsigned development
build to publisher-signed status. GitHub publication is a separate maintainer
step after reviewing the output.
