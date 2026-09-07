# Matching sources for SoundFile's native libraries

Native CleanTake installers use the unmodified SoundFile 0.14.0 wheels locked
in `uv.lock`. The wheel contains a dynamic libsndfile 1.2.2 library with static
FLAC, Ogg, Vorbis, Opus, mpg123 and LAME dependencies. Plain FLAC export uses
SoundFile directly, so a libsndfile build without FLAC is not interchangeable.

`pins.json` records all six native library hashes, original wheel hashes,
component versions, exact source archive hashes and upstream recipe hashes.
Every native library was independently matched to the Git blob in
[SoundFile's binary submodule](https://github.com/bastibe/libsndfile-binaries/tree/a3e6f9769d0c7e91d2d036cf0fdbe5b4bbf18b87).
The submodule is pinned by the
[SoundFile 0.14.0 release](https://github.com/bastibe/python-soundfile/tree/3162358d0315be769b97f3e4c12545fe18a676bc).

## Stage and verify

From the CleanTake checkout, using its locked bundle environment:

```sh
uv run --group bundle python scripts/stage_soundfile_sources.py --output build/native/soundfile
uv run --group bundle python scripts/stage_soundfile_sources.py --output build/native/soundfile --verify
```

The builder accepts a new output directory, detects the native OS and
architecture, checks the installed library against its pinned hash, and stages:

- `licenses/`: full applicable license texts, authors and notices for the target.
- `source/upstream/`: verified source archives for that target.
- `source/recipes/`: unmodified upstream build scripts and Windows port patches.
- `source/pins.json`, this README and the staging script.
- `manifest.json`: complete file hashes and the library/source provenance.

`--cache-dir DIR` reuses already downloaded archives by their names in
`pins.json`; every cached file is verified. Without it, archives are cached in
`build/source-cache/soundfile`. Official mirrors are used only with the same
pinned bytes and hash. Archive contents are never extracted during staging:
only explicitly named, regular license members are read.

The runtime builder packages the licenses and manifest. Release assets must
also publish the source directory and its manifest alongside the installer;
those source archives are intentionally separate from the installed app.
Run staging on each actual target; a successful local stage is not evidence
that another OS's native library executes correctly.

## Source versions and Windows patch provenance

| Component | macOS / Linux | Windows |
| --- | --- | --- |
| libsndfile | 1.2.2 | 1.2.2 |
| FLAC | 1.4.3 | 1.4.3 |
| Ogg | 1.3.5 | 1.3.5 |
| Vorbis | 1.3.7 | 1.3.7 |
| Opus | 1.4 | 1.5.2 |
| mpg123 | 1.32.3 | 1.32.9, vcpkg port-version 1 |
| LAME | 3.100 | 3.100 |

The macOS and Linux versions and commands are explicit in `upstream-recipes/`.
Windows DLLs were published by the upstream
[December 30, 2024 build change](https://github.com/bastibe/libsndfile-binaries/commit/1ac5f9412cedaac97667bf5f2c7d4d4fea91999e).
Its workflow used the runner's preinstalled vcpkg checkout without recording
that checkout's overall revision. We do not invent that missing revision.

The DLLs preserve vcpkg extraction identifiers `66150af195` for mpg123 and
`81ed242155` for Opus. Recomputing vcpkg's documented source-plus-ordered-patch
hash algorithm with the included source archives and patches reproduces both
identifiers. The relevant seven ports were unchanged between the mpg123 port's
December 10 update and the December 30 DLL publication. The reconstruction
uses the immutable
[December 23 vcpkg source snapshot](https://github.com/microsoft/vcpkg/tree/80d54ff62d528339c626a6fbc3489a7f25956ade),
which supplies those exact source and patch recipes. All seven source archive
SHA-512 hashes match their vcpkg ports. The complete vcpkg snapshot is included
for Windows, along with readable copies of the relevant ports and hash helper.

This establishes the corresponding source and patches. The upstream build did
not pin every compiler/SDK/runner image, so bit-for-bit recompilation is not
claimed. `upstream-recipes/.github/workflows/build-libs.yml` records the
available upstream toolchain and container descriptions without rewriting them.

## Rebuild and replace the library

Work in a fresh directory. Retain the source package unchanged for comparison;
make modifications in a separate copy. Verify archives against `pins.json`
before unpacking them. Standard platform compilers, make, CMake, pkg-config and
archive tools are build prerequisites; installers do not require these tools.

For macOS and Linux, copy `source/recipes/upstream-recipes/` to the working
directory, then copy the target archives from `source/upstream/` alongside it.
The included `mac_build.sh` and `linux_build.sh` are the exact original recipes.
To build entirely from the supplied archive inputs, remove their `curl -LO`
download lines, and use `tar xf ARCHIVE` for each extraction (the original macOS
recipe assumes BSD tar's permissive compression handling). Retain their build
order, flags and the macOS `darwin.cmake` include. On macOS, run
`sh mac_build.sh arm64` or `sh mac_build.sh` on Intel. On Linux, run
`sh linux_build.sh` natively; the recorded ARM cross-build instead sets
`CONFIGURE_FLAGS="--host=aarch64-linux-gnu --build=x86_64-linux-gnu"` with the
corresponding cross compiler. The resulting shared library statically includes
its codec dependencies. The Linux ARM original environment was Debian 10;
Linux x64 used the recorded manylinux 2.28 build environment.

For Windows, unpack the supplied full vcpkg snapshot, bootstrap vcpkg with
Visual Studio C++ tools for the desired target, and copy the included custom
triplets to a working `triplets` directory. Run:

```powershell
.\vcpkg.exe install libsndfile:x64-windows-custom --overlay-triplets=triplets
# Or: libsndfile:arm64-windows-custom
```

Use the included ports from that snapshot. vcpkg applies their ordered patches
automatically. To reuse the bundled source archives, seed vcpkg's `downloads`
directory using the `FILENAME` in `vcpkg_download_distfile` or the archive name
chosen by `vcpkg_from_github`/`vcpkg_from_gitlab` in each port; the port's SHA-512
check identifies the supplied bytes regardless of their source-package name.
vcpkg may also acquire its pinned build tools when bootstrapping. Its resulting
`installed/TRIPLET/bin/sndfile.dll` uses static codec libraries and dynamic CRT,
as specified by the original custom triplets.

Rename the result to the target's `native_library.name` in the manifest and
replace that file under the runtime's `_internal/_soundfile_data/` directory in
a copy of the unpacked app. Keep the same ABI and target architecture. On macOS,
modifying a signed bundle invalidates its original signature; rebuild the
desktop bundle locally with the modified runtime and apply your own signature
if needed. CleanTake's published source includes the runtime and desktop build
recipes. Release verification deliberately rejects an altered upstream library
until its source pins and provenance are updated; this protects distributed
releases without preventing local modification or replacement.

License terms, including modification and redistribution rights, are in
`licenses/` and in the complete source archives. See `NOTICE.md` in this
directory for the linked components' license mapping.
