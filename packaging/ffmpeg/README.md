# Standalone media tools

CleanTake distributes separate FFmpeg and FFprobe executables. They are built
from the official, unmodified FFmpeg 9.0.1 archive. The archive SHA-256 is
`cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635`.
The builder also verifies its detached signature against release-key fingerprint
`FCF986EA15E6E293A5644F10B4322F04D67658D8`, using an isolated temporary GnuPG home.
The checked-in public key and detached signature have their own pinned hashes
in `sources.json`.

Sources and keys come from [FFmpeg's official download service](https://ffmpeg.org/download.html).
The effective build is LGPL-2.1-or-later. The bundled MIT application invokes
these programs through subprocesses; it does not relabel their licenses.

## Build prerequisites

These are **developer/build-machine** prerequisites. Application users do not
need them. Use Python 3.12 or newer, GnuPG and a native toolchain. Builds support
these target recipes; a recipe is not a substitute for a passing native CI job.

| Native machine | Toolchain and packages |
| --- | --- |
| macOS ARM64 | Xcode command-line tools and `gnupg` |
| macOS x64 | Xcode command-line tools, `gnupg`, `nasm` |
| Windows x64 | MSYS2 **UCRT64** shell; `make diffutils pkgconf gnupg mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-nasm` |
| Windows ARM64 | MSYS2 **CLANGARM64** shell; `make diffutils pkgconf gnupg mingw-w64-clang-aarch64-clang` |
| Linux x64 | `build-essential binutils gnupg nasm` |
| Linux ARM64 | `build-essential binutils gnupg` |

On Windows, launch the command below inside the matching MSYS2 shell, with the
native Windows Python/uv executable on PATH. The build uses MSYS2's `bash`,
`cygpath`, `make`, compiler and GnuPG. `MSYSTEM` must match the native Python
architecture. Release checks execute the resulting tools with only Windows
System32 on PATH, outside the compiler environment. ARM64EC and emulated x64
builds do not establish native ARM64 support.

Linux builds first compile pinned [musl 1.2.6 source](https://musl.libc.org/releases/musl-1.2.6.tar.gz)
with GCC, then statically link the media executables with musl. Its SHA-256 is
`d585fd3b613c66151fc3249e8ed44f77020cb5e6c1e635a616d3f9f82460512a`.
This musl pin is an HTTPS-source hash; the script does not claim detached-signature
verification for musl. FFmpeg's static linkage does not change the frozen Python
application's separate Linux compatibility requirements.

## Build and verify

From the repository root:

```sh
python scripts/build_media_tools.py --output build/native/media --jobs 8
python scripts/build_media_tools.py --output build/native/media --verify
```

The first command requires a **new** output directory. It downloads only missing
source archives into `.local/native/downloads`, validates them before extraction,
builds, audits and tests the executables, then atomically publishes the complete
directory. An invalid cached archive fails explicitly. No unverified download is
accepted as a cache hit.

Optional arguments:

- `--cache PATH`: source-archive cache, including pinned musl on Linux.
- `--source-archive PATH`: use the exact pinned FFmpeg archive from a local file.
- `--jobs N`: parallel compiler jobs, 1–128; default at most eight.
- `--work-dir PATH`: new directory that retains intermediates and build logs
  after success or failure. Without it, temporary intermediates are removed.
- `--verify`: check the manifest and every shipped binary/license hash without
  rebuilding. This checks integrity; it does not repeat native execution probes.

For retained logs, choose a short build directory without spaces on Windows.
The **installed application** is separately tested from paths containing spaces
and non-ASCII characters. The build script does not promise all compiler suites
support arbitrary source-tree paths.

## Build contract and audits

The default built-in codecs, demuxers, parsers, encoders and filters stay enabled.
External autodetection, GPL, version-3-only and nonfree components, network access,
capture devices/libavdevice, hardware acceleration and GPU integrations are
disabled. No `--disable-everything` or maintained codec allowlist is used. The
application applies its own conservative import format and file/pipe restrictions.

macOS uses Apple Clang with the explicit SDK for target and host compilation,
targeting macOS 14.0. FFmpeg libraries are static; Apple system libraries remain
dynamic. Windows uses static GCC/compiler-rt runtime linkage and native Win32
threads. Linux requires a fully static ELF without an interpreter or DT_NEEDED.
The script rejects the wrong executable architecture and unexpected dynamic
dependencies. Compiler versions, SDK, flags, Windows package versions, capability
listings, licenses and dependency inspection results are recorded.

Each build executes real FLAC, WavPack, AAC/M4A, AIFF, Opus/Ogg, Vorbis/Ogg and MP3
decoding, MOV video with AAC audio, channel selection and 44.1-to-48 kHz resampling.
It also runs both loudness passes, checks the exact output sample count, and uses
independent `ebur128` measurement. WavPack must identify its demuxer as `wv`.
The validator uses no lavfi capture device and no hardware acceleration.

Autodetection being off intentionally excludes optional external libraries such
as zlib. Rare compressed-container variants that require those libraries are
outside this build's verified capabilities. Add a pinned static dependency,
source, notices and a real regression if one becomes required.

## Payload and corresponding source

```text
bin/ffmpeg[.exe]
bin/ffprobe[.exe]
licenses/FFmpeg/LICENSE.md
licenses/FFmpeg/COPYING.*
licenses/                         # applicable musl/compiler/runtime notices
manifest.json                     # read-only, hashes every binary and notice
source/upstream/                  # exact source archive, signature and public key
source/scripts/build_media_tools.py
source/packaging/ffmpeg/           # pins, fixtures, notices, this rebuild guide
source/results/                   # flags, compiler, capabilities and FFmpeg config
source/SOURCE-MANIFEST.json        # hashes every corresponding-source file
```

Ship `bin`, `licenses` and `manifest.json` in the application. Publish the complete
`source` directory, compressed as a release asset, **in the same release** as its
installers. Keep it available while the corresponding binaries are distributed.
No FFmpeg source patch is applied; the build manifest records an empty patch list.
Full original source, including the standalone program frontends, is supplied
so recipients can modify and rebuild these statically linked programs.

To rebuild from an extracted source asset, enter its root and run:

```sh
python scripts/build_media_tools.py --output rebuilt-media --cache upstream \
  --source-archive upstream/ffmpeg-9.0.1.tar.xz
```

Use the corresponding native toolchain recorded in `results/build-manifest.json`.
The source is rebuildable; byte-for-byte identical output across different
compiler/SDK versions is not claimed. `SOURCE_DATE_EPOCH` is fixed, no native-CPU
instruction tuning is requested, and recorded temporary build paths are replaced
with `$BUILD_ROOT`. The source archive itself remains byte-for-byte untouched.
The matching manifest records the actual released executable hashes.

FFmpeg's complete upstream license files are retained, including those for
inactive optional components. On Linux, musl's full COPYRIGHT and GCC's runtime
exception notices are added. On Windows, copy the actual installed MinGW runtime
notices, together with the applicable GCC or LLVM/compiler-rt license text.
macOS includes the LLVM/compiler-rt notice for Apple's Clang runtime archive.
Static compiler support code is covered by those runtime exceptions; these
notices do not change FFmpeg's effective LGPL license.

References: [FFmpeg legal guidance](https://ffmpeg.org/legal.html),
[FFmpeg platform notes](https://ffmpeg.org/platform.html),
[MSYS2 environments](https://www.msys2.org/docs/environments/),
[GCC runtime exception](https://www.gnu.org/licenses/gcc-exception.html).
