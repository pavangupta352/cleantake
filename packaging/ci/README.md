# Native installer verification

`.github/workflows/native.yml` builds six native targets and keeps installer,
dependency, media-source, frozen-runtime, and desktop-test evidence together.
The existing `Checks` workflow remains responsible for the full engine and
browser suites. These helpers do not publish releases.

Run the non-mutating verifier tests with:

```sh
uv run pytest packaging/ci -q
actionlint .github/workflows/native.yml
```

The macOS test compiles and runs a small executable with a bundled library. It
also proves the audit rejects the same executable when it depends on an external
build-directory library. That platform-specific test is explicitly skipped on
other operating systems; the corresponding installed dependency audit still
runs on every native target. Windows import inspection includes delayed DLL
loads as well as the ordinary import table.

## Installed artifacts

The workflow invokes:

```sh
uv run --group bundle python scripts/native_ci.py install-smoke --arch arm64
```

Select `x64` on an x64 runner. `--signed` additionally requires accepted macOS
Developer ID/Gatekeeper results, or valid Windows Authenticode signatures on the
application, installer, and uninstaller. A standalone, non-mutating payload
audit is also available:

```sh
uv run python scripts/native_ci.py audit --root /path/to/installed/application \
  --arch arm64 --report build/native/evidence/dependencies.json
```

The installer test mounts a DMG read-only, copies its app to a private test
Applications directory, and detaches the image before launch. Windows runs the
actual offline NSIS installer in silent mode and uses its normal per-user path.
Linux installs the actual Debian package through apt, preserving its original
dependency and application-specific sandbox setup. Linux and Windows installer
mutations require a disposable GitHub Actions runner and refuse an existing
CleanTake installation. macOS only removes the helper's temporary bundle.

The desktop harness receives `CLEANTAKE_APP`, `CLEANTAKE_TEST_WORKSPACE`, and
`CLEANTAKE_TEST_REPORT_DIR`. Its workspace has spaces and non-ASCII characters.
After the actual app test, every saved workspace file is hashed and compared
after uninstall and again after reinstall. The second install does not rerun
the first-run edit script on an already edited project. The desktop harness
separately owns restart/reopen and process-cleanup checks.

Linux also extracts and launches the portable archive after removing the Debian
package. The archive does not receive an AppArmor exception from this helper.
A restricted host may therefore reject that launch; retain the actual result
and scope archive compatibility accordingly. Never change the machine's
user-namespace policy or disable Chromium sandboxing to make that check pass.

## Evidence and its limits

`build/native/evidence/install.json` records the runner, commit, artifact hash,
signature results, native binary architectures/dependencies, desktop checks,
saved-file retention, and cleanup failures. Private session tokens are redacted
from bounded subprocess diagnostics. Post-sign application files are hashed
as installed; the verifier does not compare them with pre-sign Mach-O hashes.
Windows NSIS removal launchers are inventoried separately from the native
application payload because their bootstrap architecture can differ.

Linux dependency resolution includes bundled library directories, and macOS
inspection resolves inherited run paths against bundled native files. Actual
launch checks are required in addition to this static inventory. OS library
locations are reported; external Python, FFmpeg, or scientific-library paths
are rejected. Windows API-set imports represent virtual OS contracts.

Hosted CI images already contain software. Removing developer tools from the
application's PATH and passing dependency checks does not prove a pristine
machine, oldest-version compatibility, physical audio-device behavior, Windows
standard-user/UAC behavior, or first-download quarantine acceptance. Keep those
limits with published evidence. Dedicated Linux PulseAudio and Xvfb provide
real advancing audio and display services; their setup changes no sandbox policy.

Automatic pushes and pull requests build development installers: ad-hoc macOS
signatures and unsigned Windows executables. Manual `sign=true` runs use the
`native-signing` GitHub environment and require configured credentials. Set
maintainer approval and trusted-branch restrictions on that environment before
adding secrets; merely naming an environment does not protect it. macOS needs
`CSC_LINK`, `CSC_KEY_PASSWORD`, `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, and
`APPLE_TEAM_ID`. Windows needs `WIN_CSC_LINK` and `WIN_CSC_KEY_PASSWORD`. Signing
credentials are never injected into a pull-request or automatic push build.
