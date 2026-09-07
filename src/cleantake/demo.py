"""An offline, explicitly damaged example from the licensed AMI corpus."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import soundfile as sf

from cleantake.projects import ProjectStore

ASSETS = Path(__file__).parent / "assets" / "demo"


def prepare_demo(destination: Path) -> dict:
    """Write labeled source files to a new directory without changing bundled media."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Sample destination already exists")
    entries = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
    for entry in entries:
        path = ASSETS / entry["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Bundled sample failed its integrity check; reinstall CleanTake")
    destination.mkdir(parents=True)
    try:
        headset, lapel = (ASSETS / entry["file"] for entry in entries)
        shutil.copyfile(headset, destination / "Headset-original.wav")
        shutil.copyfile(lapel, destination / "Lapel-backup.wav")
        audio, rate = sf.read(headset)
        audio[17 * rate : round(17.5 * rate)] = 0
        sf.write(destination / "Headset-injected-dropout.wav", audio, rate, subtype="PCM_24")
        shutil.copyfile(ASSETS / "ATTRIBUTION.md", destination / "ATTRIBUTION.md")
        manifest = {
            "title": "AMI ES2004a: a half-second dropout, two real microphones",
            "license": "CC-BY-4.0",
            "attribution": "AMI Meeting Corpus — AMI Project Consortium",
            "injected_fault_seconds": [17.0, 17.5],
            "changes": "Headset samples set to zero from 17.0 to 17.5 seconds; saved as PCM24. "
            "Original headset and independent lapel excerpt retained unchanged.",
            "automatic_acceptance": False,
            "limitations": "Controlled damage on development audio; not organic damage "
            "or a listening-quality benchmark.",
            "sources": entries,
            "files": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(destination.glob("*.wav"))
            },
        }
        (destination / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return manifest
    except BaseException:
        shutil.rmtree(destination)
        raise


def create_demo(store: ProjectStore) -> dict:
    """Import and analyze the sample, leaving every repair for the listener to review."""
    with TemporaryDirectory(prefix="cleantake-demo-") as temporary:
        directory = Path(temporary) / "recordings"
        manifest = prepare_demo(directory)
        project = store.create("Sample · recover a missing half-second")
        store.import_source(
            project.id, directory / "Headset-injected-dropout.wav", name="Headset · injected gap"
        )
        store.import_source(project.id, directory / "Lapel-backup.wav", name="Lapel · backup")
        project = store.analyze(project.id)
    return {
        "project_id": project.id,
        "project_name": project.name,
        "injected_fault_seconds": manifest["injected_fault_seconds"],
        "license": manifest["license"],
        "attribution": manifest["attribution"],
        "pending_repairs": sum(repair.status == "proposed" for repair in project.repairs),
        "next": "Run cleantake studio with the same workspace, open the sample, "
        "and compare Original and Repair near 17 seconds before accepting the suggestion.",
    }
