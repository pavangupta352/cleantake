# Embedded Python component notices

Native CleanTake builds use **CPython 3.12.13, python-build-standalone release
20260504**, selected by the native workflow's pinned **uv 0.11.11**. Python's main
license does not cover the separate libraries embedded in that distribution.
This directory retains the exact upstream platform metadata and component
notices needed alongside it.

The original optimized full archives were downloaded from the official release
and checked against its SHA-256 asset digests. `archives.json` records all six
immutable archive names, URLs, sizes and hashes. `manifest.json` hashes every
retained metadata/notice file. No full interpreter archive is committed.

| Target | Upstream build options | Retained files |
| --- | --- | ---: |
| aarch64-apple-darwin | pgo+lto | 21 |
| x86_64-apple-darwin | pgo+lto | 21 |
| aarch64-pc-windows-msvc | pgo | 20 |
| x86_64-pc-windows-msvc | pgo | 20 |
| aarch64-unknown-linux-gnu | pgo+lto | 21 |
| x86_64-unknown-linux-gnu | pgo+lto | 21 |

Each target keeps the original `PYTHON.json` and all license files from its full
archive. This is a notice superset for that interpreter distribution, including
optional components; a notice's presence is not a claim that every optional
module is used by CleanTake. The original metadata distinguishes system-library
links, static links, shared modules and built-in modules. It avoids guessing
component versions from another platform's Python installation.

## Build integration

`scripts/build_runtime.py` stages and verifies the matching notices before
freezing, using the same interpreter that builds the runtime:

```sh
python packaging/python/stage_notices.py --output build/native/python-notices
python packaging/python/stage_notices.py --output build/native/python-notices --verify
```

Staging requires a new output directory. It rejects a different interpreter
version, architecture or managed `BUILD` marker, and fails on missing, altered,
unrecorded or symlinked notice files. There is no network download during this
step. The runtime spec includes the entire verified directory under
`licenses/python-components`, in addition to Python's main license. The final
runtime manifest records the component-notice manifest.

When changing the Python version or standalone build, update all archive pins,
metadata and notices deliberately before relaxing the identity gate. Merely
matching the CPython patch version is insufficient: a later standalone release
can rebuild it with different third-party libraries.

## Recreating the subset

Download the six full archives named in `archives.json` into a private directory.
The official Astral mirror URLs in that file serve the same hash-checked content.
Then run:

```sh
python packaging/python/refresh_notices.py --archives /path/to/full-archives \
  --output /path/to/new-notice-subset
```

This developer-only command requires `zstd` on PATH. It verifies complete archive
hashes before streaming extraction, accepts only regular bounded metadata/license
files, checks the target and Python version, and writes a new subset plus its
manifest. Normal application builds use the committed subset and need no zstd.
Compare the regenerated `targets/` and `manifest.json` before updating them.

## Upstream metadata discrepancy

The four Unix `PYTHON.json` files list both zlib and zlib-ng notice paths, but the
full archives contain only `LICENSE.zlib.txt`. The matching build repository
also lacks the named zlib-ng notice file. We preserve those original metadata
bytes and supply the missing referenced notice explicitly, rather than silently
omitting a declared notice or editing upstream metadata.

`supplements/LICENSE.zlib-ng.txt` comes from `LICENSE.md` in the exact
zlib-ng 2.2.4 source archive pinned by the matching build commit
`20f6240400c4c5b9f8cbf115e022f1e92042c575`. The supplemental source archive and
notice hashes, immutable source URL and reason are recorded in `archives.json`
and each affected target manifest. This retains the upstream metadata's full
notice set; it does not claim zlib-ng is linked on all four Unix targets.

Upstream references:

- [The exact standalone release](https://github.com/astral-sh/python-build-standalone/releases/tag/20260504)
- [Distribution metadata and install-only archive format](https://github.com/astral-sh/python-build-standalone/blob/20f6240400c4c5b9f8cbf115e022f1e92042c575/docs/distributions.rst)
- [Embedded-library licensing guidance](https://github.com/astral-sh/python-build-standalone/blob/20f6240400c4c5b9f8cbf115e022f1e92042c575/docs/running.rst)
- [The matching dependency/source pins](https://github.com/astral-sh/python-build-standalone/blob/20f6240400c4c5b9f8cbf115e022f1e92042c575/pythonbuild/downloads.py)
- [The supplemental notice's exact source](https://github.com/python/cpython-source-deps/blob/a502e047655c31db29601def76ad6539acacf43d/LICENSE.md)
