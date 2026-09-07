"""Exercise the installed wheel outside the checkout, including the packaged studio."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import soundfile as sf

from cleantake.projects import ProjectStore


def main():
    with TemporaryDirectory(prefix="cleantake-install-check-") as temporary:
        root = Path(temporary)
        workspace = root / "work"
        command = [sys.executable, "-m", "cleantake.cli", "--workspace", str(workspace)]

        def cli(*arguments):
            completed = subprocess.run(
                [*command, *arguments], cwd=root, capture_output=True, text=True, check=True
            )
            return json.loads(completed.stdout)

        doctor = cli("doctor")
        assert doctor["studio"]["available"], "Wheel is missing the studio"
        demo = cli("demo")
        pid = demo["project_id"]
        project = cli("show", pid)
        proposal = next(item for item in project["repairs"] if item["status"] == "proposed")
        cli("edit", pid, proposal["id"], "--status", "accepted")
        cli("export", pid, "--output", str(root / "export"))
        rendered, rate = sf.read(root / "export/dialogue.wav")
        store = ProjectStore(workspace / "projects")
        saved = store.get(pid)
        primary = store.source_samples(pid, saved.primary_source_id)
        start, end = proposal["start_frame"], proposal["end_frame"]
        assert rate == 48_000 and len(rendered) == 960_000
        assert np.array_equal(rendered[:start], primary[:start])
        assert np.array_equal(rendered[end:], primary[end:])
        assert np.sqrt(np.mean(rendered[start:end] ** 2)) > 0.01
        cli("archive", pid, "--output", str(root / "sample.zip"))
        restored = cli("open-archive", str(root / "sample.zip"))
        assert restored["id"] != pid and restored["repairs"][0]["status"] == "accepted"
        del primary
        log = root / "server-output.txt"
        with log.open("w") as output:
            server = subprocess.Popen(
                [*command, "studio", "--no-browser", "--print-link"],
                cwd=root,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                match = re.search(r"(http://127\.0\.0\.1:\d+/)#token=([^\s]+)", log.read_text())
                if match:
                    base, token = match.groups()
                    try:
                        urllib.request.urlopen(base + "api/health", timeout=1).close()
                        break
                    except OSError:
                        pass
                if server.poll() is not None:
                    raise AssertionError("Installed studio exited before startup")
                time.sleep(0.1)
            else:
                raise AssertionError("Installed studio did not become ready")

            def fetch(path):
                request = urllib.request.Request(base + path, headers={"X-CleanTake-Token": token})
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.read()

            html = fetch("").decode()
            script = re.search(r'src="(/assets/[^\"]+\.js)"', html)
            assert script and len(fetch(script.group(1).lstrip("/"))) > 10_000
            assert json.loads(fetch(f"api/projects/{pid}"))["id"] == pid
            assert len(fetch("THIRD_PARTY_NOTICES.txt")) > 1000
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        print("Installed package: real sample recovery, exact timing, archive and studio passed.")


if __name__ == "__main__":
    main()
