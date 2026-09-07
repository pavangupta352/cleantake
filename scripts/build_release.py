"""Build the locked studio, bundle its notices, and produce Python distributions."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments: str, cwd: Path = ROOT):
    subprocess.run(arguments, cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-only", action="store_true", help="Refresh bundled assets only")
    args = parser.parse_args()
    studio = ROOT / "studio"
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("Node.js and npm are needed to rebuild the studio.")
    run(npm, "ci", cwd=studio)
    run(npm, "run", "build", cwd=studio)
    static = ROOT / "src/cleantake/static"
    if static.exists():
        shutil.rmtree(static)
    shutil.copytree(studio / "dist", static)
    notices = [
        "# Bundled studio notices\n\n"
        "The following notices apply to code included in the browser bundle.\n"
    ]
    for name, filename in (
        ("react", "LICENSE"),
        ("react-dom", "LICENSE"),
        ("scheduler", "LICENSE"),
        ("lucide-react", "LICENSE"),
        ("vite", "LICENSE.md"),
    ):
        package = studio / "node_modules" / name
        version = json.loads((package / "package.json").read_text(encoding="utf-8"))["version"]
        notices.append(
            f"\n## {name} {version}\n\n" + (package / filename).read_text(encoding="utf-8")
        )
    (static / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(notices), encoding="utf-8")
    if not args.assets_only:
        uv = shutil.which("uv")
        if not uv:
            raise SystemExit("Install uv to build the Python wheel and source distribution.")
        run(uv, "build")
        version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
            "version"
        ]
        artifacts = sorted((ROOT / "dist").glob(f"cleantake-{version}-*.whl")) + [
            ROOT / "dist" / f"cleantake-{version}.tar.gz"
        ]
        checksums = "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in artifacts
        )
        (ROOT / "dist/SHA256SUMS").write_text(checksums, encoding="utf-8")
        print(checksums, end="")


if __name__ == "__main__":
    main()
