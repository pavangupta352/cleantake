# Self-contained desktop distribution

## Intended result

The desktop edition installs CleanTake and its required runtimes together. An
editor opens the application, chooses the included sample or imports recordings,
and completes the existing recovery workflow without installing Python, Node.js,
FFmpeg, a separate browser, a model, or a GPU computing driver.

This document describes the native architecture and its acceptance requirements.
The [validation record](VALIDATION.md) identifies actual tested revisions and
platforms; the [desktop guide](DESKTOP.md) covers installation and publisher trust.
The Python/browser edition remains available alongside the native application.

## Architecture

An Electron window presents the existing bundled studio. It starts a native
PyInstaller backend from the application's read-only resources. That backend
contains Python, the scientific libraries, the studio, the offline sample, and
our FFmpeg/FFprobe executables. The numerical engine and saved-project format
remain shared with the CLI/browser edition.

The backend uses a one-folder bundle. Its console bootloader permits a private
stdio control channel; Electron hides the Windows console. Every entry point
calls `multiprocessing.freeze_support()` before importing or dispatching normal
application code. Processing workers therefore enter their intended worker
function instead of recursively launching the desktop application.

Frozen executions resolve the two media tools from an absolute bundle path.
They never silently fall back to a developer's PATH. Source and wheel installs
retain their documented PATH-based tool discovery. Windows media subprocesses
have no console windows. No installer changes the user's global Python or PATH.

## Desktop lifecycle and boundary

The native entry accepts `--desktop`, with an optional explicitly supplied
workspace. It binds a random loopback port, owns the existing workspace lease,
and emits one JSON line on stdout after the service is ready:

```json
{"event":"ready","version":"0.2.0","url":"http://127.0.0.1:PORT/#token=SESSION_TOKEN"}
```

The placeholders above describe the protocol, not literal runtime values.
Diagnostics use stderr and never repeat the private URL or token. Startup
failure emits a bounded JSON error with a stable code and actionable message.
The parent validates the URL as a token-bearing loopback HTTP URL before use.

The parent sends `shutdown\n` through stdin to stop the server. End-of-file also
requests shutdown, so a closed parent pipe cannot leave an unattended service.
Shutdown cancels active jobs, waits for owned children, and releases the
workspace lease. The parent provides a bounded process-tree fallback if graceful
shutdown fails. Tests must exercise actual spawned workers and media children.

Electron allows one application instance. A second launch focuses the existing
window. Reload, close, reopen, backend failure, and a workspace already in use
have explicit behavior. The native shell has normal platform menus and window
controls, remembers usable window bounds, and uses the native save dialog for
exports. Closing the application stops its backend; saved project data remains.

The renderer has no Node integration or privileged preload API. Context
isolation, Chromium sandboxing, web security, and the existing content-security
policy stay enabled. Navigation is restricted to the exact backend origin;
external help links open only vetted HTTPS destinations in the system browser.
Unexpected permission requests and new windows are denied. No remote page is
loaded into the privileged shell. Automatic unsigned-code updates are outside
this release; the Help menu can open the verified release page.

On the first desktop launch, an empty workspace receives the labeled offline
sample with its suggestion pending. An atomic initialization marker prevents
recreating the sample after an editor deliberately removes it. Existing
workspaces and user decisions are not reset. First-run work must complete under
the same workspace lease, before the service accepts editing requests.

## Native build targets

| Family | Architectures | Distribution | Compatibility qualification |
|---|---|---|---|
| macOS | Apple silicon and Intel, separately | DMG containing CleanTake.app | macOS 14+ because of the selected scientific-library wheels |
| Windows | x64 and ARM64, separately | Offline, per-user NSIS installer | Windows 10+ x64; Windows 11 ARM64; actual runner evidence reported separately |
| Linux | x64 and ARM64, separately | Debian package and secondary portable archive | Build x64 on Ubuntu 22.04 and ARM64 on Ubuntu 24.04; inspect actual runtime floors and test declared package dependencies |

Each target requires a native backend, native FFmpeg, matching Electron runtime,
and actual packaged tests. No architecture is advertised as verified merely
because a cross-compilation succeeded. Historical 32-bit systems, mobile
operating systems, unsupported desktop releases, and missing OS audio-device
support are not covered by an "any computer" claim.

The Windows installer includes its payload and creates standard shortcuts. It
does not fetch developer runtimes during installation or erase projects during
uninstall. The macOS app runs from its installed bundle without a writable
working directory. The Linux package declares required desktop libraries and
retains the packager's application-specific sandbox setup. A portable Linux
archive cannot install system policies; its narrower compatibility is labeled.
Do not disable the sandbox, AppArmor, or platform security checks to make a
distribution appear compatible.

## Media tools and licenses

Build FFmpeg 9.0.1 from the official signed archive. Its SHA-256 is
`cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635`.
Keep software codecs, demuxers, parsers, and required audio filters; disable
external autodetection, GPL/nonfree features, network protocols, capture devices,
and GPU dependencies. The application retains its own conservative input format
and file/pipe protocol restrictions. Validate real import formats and loudness
finishing with the resulting binaries, including WavPack's `wv` demuxer name.

Record target architecture, source hashes, configure arguments, compiler,
binary hashes, effective license, and runtime dependencies. Publish corresponding
FFmpeg source and reproducible build instructions alongside the application.
Carry FFmpeg, Python, Python dependency, PyInstaller bootloader, Electron,
Chromium, studio dependency, and AMI sample notices in the distributed bundle.
CleanTake's MIT license does not relabel those components.

## Signing and first-download trust

Dependency-free installation and trusted publisher verification are separate
checks. No usable code-signing identity was present in the inspected local
keychains when this work began. macOS direct distribution requires a Developer
ID signature and successful notarization for the normal trusted-download path.
Ad-hoc signing is useful for build integrity but is not notarization. Windows
Authenticode identifies the publisher; even a signed new release can receive a
SmartScreen reputation prompt.

Build and test the artifacts while signing access is established. Wire signing
and notarization through protected credentials, never committed keys or tokens.
Report actual signature and quarantine results. Never strip quarantine, install
a self-signed trust root, or bypass platform protection as an installer step.

## Acceptance evidence

- Native dependency inspection permits only bundled libraries and explicitly
  documented operating-system libraries. No Homebrew, developer checkout,
  external Python environment, or system FFmpeg path may be required.
- Launch the actual frozen backend with an empty or tightly restricted PATH,
  from a path containing spaces and non-ASCII characters. Create the real sample,
  exercise spawned jobs, render/export, reopen an archive, and test shutdown.
- Launch the actual packaged desktop window. Verify sandbox boundaries, first
  run, sample playback, editing, export download, restart, single-instance
  behavior, and process cleanup. Require an advancing real audio clock in CI.
- Exercise each native installer and its installed payload. Verify architecture,
  installation/uninstallation behavior, signatures, corresponding source,
  checksums, and absence of private build files or paths.
- Keep existing engine, project, API, browser, and installed-wheel checks green.
  Scope every platform claim to its actual build, dependency, and test evidence.

Pinned initial build tools: Electron 44.2.0, electron-builder 26.16.1,
PyInstaller 6.22.2, and Python 3.12.13. Lock dependencies and record any deliberate
version change before building release artifacts.
