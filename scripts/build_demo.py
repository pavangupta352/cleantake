"""Produce the public, labeled listening example from actual CleanTake exports."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import soundfile as sf

from cleantake import __version__
from cleantake.demo import ASSETS, create_demo
from cleantake.exports import export_project
from cleantake.portability import export_archive
from cleantake.projects import ProjectStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New listening-example directory"
    )
    parser.add_argument("--archive", type=Path, help="Optional new portable archive destination")
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Output directory already exists")
    with TemporaryDirectory(prefix="cleantake-public-demo-") as temporary:
        work = Path(temporary)
        store = ProjectStore(work / "projects")
        demo = create_demo(store)
        pid = demo["project_id"]
        project = store.get(pid)
        proposals = [item for item in project.repairs if item.status == "proposed"]
        if len(proposals) != 1:
            raise RuntimeError("Expected one automatic sample proposal; inspect before publication")
        decision = proposals[0]
        store.update_repair(pid, decision.id, {"status": "accepted"})
        project = store.get(pid)
        export_project(store, pid, work / "export")
        rendered, rate = sf.read(work / "export/dialogue.wav")
        primary = store.source_samples(pid, project.primary_source_id)
        assert np.array_equal(primary[: decision.start_frame], rendered[: decision.start_frame])
        assert np.array_equal(primary[decision.end_frame :], rendered[decision.end_frame :])
        assert len(rendered) == len(primary) == 960_000
        args.output.mkdir(parents=True)
        excerpt = slice(14 * rate, 20 * rate)
        sf.write(args.output / "before.wav", primary[excerpt], rate, subtype="PCM_24")
        sf.write(args.output / "after.wav", rendered[excerpt], rate, subtype="PCM_24")
        del primary
        shutil.copyfile(work / "export/source-map.json", args.output / "source-map.json")
        attribution = (ASSETS / "ATTRIBUTION.md").read_text(encoding="utf-8")
        attribution += (
            "\n## Listening example modifications\n\n"
            "`before.wav` and `after.wav` cover local project seconds 14 to 20 "
            "(original AMI meeting seconds 338 to 344). The headset was zeroed at "
            "local seconds 17 to 17.5. CleanTake aligned the independent lapel "
            "and proposed the repair recorded in manifest.json. That proposal "
            "was explicitly accepted by this reproducible script without manual "
            "boundary or gain adjustment. Both clips are 48 kHz mono PCM24; "
            "the primary outside the repair is preserved before PCM24 rounding. "
            "There is no loudness finishing. Source-map.json covers the full "
            "20-second project, so add 14 seconds to a listening-clip position. "
            "These modified recordings retain the CC BY 4.0 license above.\n"
        )
        (args.output / "ATTRIBUTION.md").write_text(attribution, encoding="utf-8")
        manifest = {
            **demo,
            "pending_repairs": 0,
            "accepted_repairs": 1,
            "next": "Listen to the labeled before/after excerpts and inspect the source map.",
            "cleantake_version": __version__,
            "sample_rate": rate,
            "listening_excerpt_project_seconds": [14, 20],
            "decision": decision.model_dump(mode="json") | {"status": "accepted"},
            "intervention": "Script explicitly accepted the sole automatic proposal; "
            "no manual alignment, boundary, source, gain or fade changes.",
            "processing": "PCM24 listening excerpts from the unmastered float export",
            "unchanged_primary_outside_repair_before_quantization": True,
            "duration_frames": len(rendered),
            "source_manifest": json.loads((ASSETS / "manifest.json").read_text()),
            "sha256": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(args.output.iterdir())
            },
        }
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if args.archive:
            export_archive(store, pid, args.archive)
    print("Created labeled before/after audio, exact source map and modification manifest.")


if __name__ == "__main__":
    main()
