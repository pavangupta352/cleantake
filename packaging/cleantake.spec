# Native one-folder backend. Invoked by scripts/build_runtime.py.
import os
import sys
from importlib import metadata
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
media = Path(os.environ["CLEANTAKE_MEDIA_DIR"])
suffix = ".exe" if sys.platform == "win32" else ""
datas = collect_data_files("cleantake", includes=["static/**", "assets/**"])
datas += copy_metadata("cleantake", recursive=True)
datas += copy_metadata("pyinstaller")
datas += [
    (str(media / "licenses"), "media/licenses"),
    (str(media / "manifest.json"), "media"),
    (str(root / "LICENSE"), "licenses/cleantake"),
    (str(root / "THIRD_PARTY_NOTICES.md"), "licenses/cleantake"),
]
python_license = next(
    (
        p
        for p in (
            Path(sys.base_prefix) / "LICENSE.txt",
            Path(sys.base_prefix)
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "LICENSE.txt",
            Path(sys.base_prefix) / "Lib" / "LICENSE.txt",
        )
        if p.is_file()
    ),
    None,
)
if python_license is None:
    raise RuntimeError("The embedded Python license was not found")
datas.append((str(python_license), "licenses/python"))
# Some distributions keep component notices outside their dist-info directory.
for distribution in metadata.distributions():
    name = distribution.metadata["Name"]
    if name.lower() not in {"numpy", "scipy", "soundfile", "pyinstaller"}:
        continue
    for item in distribution.files or []:
        if any(label in item.name.upper() for label in ("LICENSE", "COPYING", "COPYRIGHT")):
            source = Path(distribution.locate_file(item))
            if source.is_file():
                safe_parts = [p for p in item.parts if p not in (".", "..")]
                datas.append((str(source), str(Path("licenses") / name / Path(*safe_parts).parent)))

a = Analysis(
    [str(root / "packaging/runtime_entry.py")],
    pathex=[str(root / "src")],
    binaries=[(str(media / "bin" / (name + suffix)), "media") for name in ("ffmpeg", "ffprobe")],
    datas=datas,
    hiddenimports=[
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.lifespan.on",
        "uvicorn.logging",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "psutil", "IPython", "matplotlib", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cleantake-runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="cleantake-runtime")
