# Electron 44.2.0 source supplement

CleanTake's desktop shell redistributes the official Electron **44.2.0** runtime,
which embeds Chromium **152.0.7977.76**. This supplement accompanies the same
CleanTake version's `native-sources` release asset, beside the installers at
https://github.com/pavangupta352/cleantake/releases. It is separate from the
backend's FFmpeg 9.0.1 and SoundFile/libsndfile source packages. Electron's FFmpeg
is a different, Chromium-modified library; the backend's FFmpeg source is not a
substitute for it.

The installers retain `LICENSE.electron.txt` and `LICENSES.chromium.html`.
Individual covered-source files retain their upstream notices and licenses.
This supplement includes complete selected upstream source archives, unmodified
license copies, Electron's patches, generated FFmpeg configurations, and the
source metadata used to identify them. `source/pins.json` records each archive's
origin, commit, extraction destination, byte length and SHA-256. The enclosing
`manifest.json` inventories every delivered file. No source archive is an
unversioned download or a promise to provide source later.

## Exact identities

| Repository | Revision |
| --- | --- |
| Electron | `aa650d74597c652878629df0038a50485e156a09` (tag `v44.2.0`) |
| Chromium | `0d89dfa2dd7c1ec4b8a14b9f303f887bb63b6174` (tag `152.0.7977.76`) |
| Chromium's FFmpeg fork | `2b68d2babae73714846961fb0ee47e3b3d2e39a9` |
| Eigen | `d53ac33805ba0a23fa139adaf24227fb6707e6fa` |
| Hunspell dictionaries | `cccf64a8acc951afe3f47fee023908e55699bc58` |
| axe-core preferred source | `281653df3794f429b71327fe3afa37ca0fadb1c7` |

Electron's `DEPS` selects Chromium; Chromium's `DEPS` selects FFmpeg, Eigen and
the dictionary repository. The other Chromium subtrees are taken directly from
the Chromium revision above. The vendored Symphonia 0.6.0 family records upstream
revision `980bf5830a90e069fd64641d9c38f067ab772a24` in its `README.chromium` files.
The vendored sources, generated GN definitions, Cargo metadata and Chromium
patches are included together. The Electron source archive contains the entire
ordered `patches/` tree and the scripts that apply it.

## Components and scope

| Source family | License facts and delivery scope |
| --- | --- |
| Chromium FFmpeg | LGPL 2.1 or later for the configured library. All six supplied Chrome target configurations disable GPL, nonfree and version3 features. Full FFmpeg fork, configuration/build scripts, Electron's ordered FFmpeg patch and its statically linked BSD Opus dependency are supplied. NASM integration and source are included for the assembly build route. |
| Blink/WebKit | A mixture of file-specific permissive and GNU Library/Lesser GPL terms; the whole tree cannot be treated as BSD. The complete renderer, public, common and tools subtrees plus top-level license/DEPS metadata are supplied. These include the inherited DOM and WTF source files, interface definitions and build rules. Browser test corpora are omitted. |
| libusbx | LGPL 2.1; Chromium's modified source, patches, headers and build configuration. The pinned GN file restricts this integration to macOS. |
| Symphonia | MPL 2.0; all eight vendored 0.6.0 crates, their Chromium GN metadata, patches and audio-decoder glue. The shipped Mac framework contains actual FLAC/MP3 Symphonia decoder strings. |
| NSPR, Mozilla certificate helpers, URL parser, ISimpleDOM | Chromium's complete selected forks with their file-specific MPL 1.1/2.0 and permissive notices. Windows-specific code is retained in this common source asset. Available alternative license terms are not removed. |
| Hunspell and dictionaries | Chromium's modified Hunspell source, its MPL/alternative license notices, and the exact complete dictionary repository including `.dic`, `.aff`, README/license files and conversion inputs. The desktop GN configuration uses the renderer spell checker on Windows/Linux and the OS spell checker on macOS. Individual dictionary terms differ. |
| Eigen | Complete exact upstream source and Chromium integration, with MPL 2.0 and file-specific alternatives preserved. Included conservatively across desktop targets. |
| Hyphenation patterns | Chromium's exact text-pattern sources, generated data, generation script and original per-language notices. Terms differ by language, including LGPL/MPL and permissive licenses. |
| axe-core | Chromium's vendored build plus its exact preferred upstream source (the vendored minified JavaScript alone is not the preferred form). MPL 2.0. Included conservatively; its README describes a test integration, not proof that it runs in CleanTake. |

The generated Chromium credits contain 779 entries and cover more platforms and
build features than CleanTake ships. Android/ChromeOS components are not assumed
to be present solely because they appear there. Linux system libraries loaded
from the operating system are not copied into the installer by this source
stage. Dual MIT/GPL notices (for example JSZip) do not establish that the GPL
alternative was selected. The table intentionally distinguishes actual observed
Mac integrations from conservative cross-platform source coverage.

## Inspect, modify and rebuild

The source archives are supplied for inspection and modification. Their `root`
fields in `pins.json` name locations relative to Chromium's `src/` directory;
Electron's archive uses `src/electron` relative to the checkout root. The
axe-core archive is an independent upstream source tree. GitHub archives have
one top-level directory (`strip_components: 1`); Gitiles subtree archives have
no added root directory. Always inspect an archive and extract only into a new,
owned directory. Preserve file names and license headers.

A complete Chromium/Electron compilation also needs the remaining exact
permissive source dependencies and the upstream compiler/SDK toolchain. This
supplement is not a full offline Chromium checkout. The included Electron and
Chromium `DEPS` files pin those dependencies, and the complete Electron build
scripts and Chromium `build/` and `buildtools/` trees are provided. Follow the
included versioned `docs/development/build-instructions-gn.md`, plus the pinned
Chromium platform build instructions in `source/recipes/upstream-metadata/`.
Those instructions document the substantial toolchain, disk and memory needs
of rebuilding Electron; these are not prerequisites for installing CleanTake.

For a clean reconstruction, install the platform build prerequisites described
there, put Chromium `depot_tools` on the build shell's PATH, and create a new
checkout. The following POSIX-shell outline pins Electron before resolving its
DEPS (use the documented PowerShell quoting on Windows):

```sh
mkdir electron-44.2.0-source
cd electron-44.2.0-source
gclient config --name "src/electron" --unmanaged https://github.com/electron/electron
mkdir -p src
git clone --no-checkout https://github.com/electron/electron src/electron
git -C src/electron checkout aa650d74597c652878629df0038a50485e156a09
gclient sync -f --with_branch_heads --with_tags
cd src
gn gen out/Release --args='import("//electron/build/args/release.gn") target_cpu="arm64"'
ninja -C out/Release electron:electron_dist_zip
```

Choose `target_cpu="arm64"` or `"x64"` for the desired native target. Windows
ARM64 additionally uses `ELECTRON_BUILDING_WOA=1` before synchronization, as the
included Electron instructions specify. On Windows with a locally installed
Visual Studio toolchain, follow the documented `DEPOT_TOOLS_WIN_TOOLCHAIN=0`
configuration. Upstream hooks fetch the pinned build dependencies and apply
Electron's patches; do not apply the same patch twice. In particular,
`patches/ffmpeg/.patches` orders `link_with_loader_path.patch`. Apply your
modifications after that baseline is established. The supplied pre-patch
archives preserve the exact inputs to this process.

`release.gn` selects `is_component_ffmpeg=true`, and `all.gn` selects
`ffmpeg_branding="Chrome"` with proprietary codec support. Preserve those
settings when rebuilding a compatible replacement. The exact generated
configurations are supplied for `Chrome/mac/{arm64,x64}`,
`Chrome/linux/{arm64,x64}`, and `Chrome/win/{arm64,x64}`. The FFmpeg archive also
includes all architecture source lists and its configure/regeneration scripts.
For FFmpeg alone, the GN target is `third_party/ffmpeg:ffmpeg`; use the full
Electron distribution target when changing libraries linked into Electron's
main executable or framework.

## Replace a library or the shell

Work on a copy of the installed application with the same OS and architecture.
Keep the original application until the replacement has been checked.

| Platform | Electron FFmpeg library in the installed application |
| --- | --- |
| macOS | `CleanTake.app/Contents/Frameworks/Electron Framework.framework/Versions/A/Libraries/libffmpeg.dylib` |
| Windows | `ffmpeg.dll` beside `CleanTake.exe` |
| Linux | `libffmpeg.so` beside the `cleantake` application executable |

A compatible FFmpeg build can replace that separate library. Libraries such as
Blink, libusb and the MPL-covered compiled code are linked into Electron's
framework/executable: modify the supplied sources and rebuild the matching
Electron distribution, then package CleanTake with it. CleanTake's MIT source
and `desktop/` packaging configuration are available in the same release's
source checkout. `electron-builder` supports a custom `electronDist` directory;
point it to the unpacked rebuilt distribution and preserve CleanTake's
application resources and frozen backend from the matching release.

On macOS modifying a signed application invalidates its existing signature;
use your own signing identity (or local development signing for your own copy)
after replacement. Do not represent a modified build as retaining the original
signature. Equivalent local trust checks may apply on Windows/Linux. No
CleanTake EULA restricts modification or reverse engineering for debugging
changes to these libraries. Their original license rights remain applicable.

## Verification performed and limits

The staging helper checks the Electron version against the committed npm lock,
checks every pinned source/recipe/notice, rejects symlinks and unexpected files,
and verifies the resulting inventory against trusted pins rather than trusting
a rewritten manifest. The native release assembler repeats that validation.

The official macOS ARM64 Electron ZIP was actually hashed and its FFmpeg member
inspected. The final app's library has a different whole-file hash after local
signing; both values and the six official release ZIP digests are recorded in
`upstream-metadata/native-provenance.json`. The final Mac framework links that
library and contains its LGPL identification plus actual libusb and Symphonia
integration strings. The other five official ZIP digests are upstream release
provenance, not a claim that all five libraries were independently downloaded
and examined in this source audit.

The Electron FFmpeg patch was checked against the exact source BUILD.gn. The
six checked-in target configuration files were verified to disable GPL/nonfree/
version3 features. A full Electron/Chromium rebuild or a binary replacement
experiment was not run for this supplement; it does not claim bit-for-bit
reproducibility, an offline build, or a legal certification.
