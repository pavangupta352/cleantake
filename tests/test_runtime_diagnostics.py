"""Bounded failure evidence for the real frozen-runtime smoke harness."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ENTRY = Path(__file__).parents[1] / "packaging/runtime_entry.py"


def test_opt_in_worker_diagnostic_emits_an_actual_python_stack():
    script = (
        "import runpy, sys, time; "
        f"entry=runpy.run_path({str(ENTRY)!r}); "
        "sys.argv=['runtime', '--multiprocessing-fork']; "
        "entry['_enable_worker_diagnostics'](0.02); time.sleep(0.09)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=5,
        env={**os.environ, "CLEANTAKE_SMOKE_DIAGNOSTICS": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert "Timeout" in result.stderr and 'File "<string>"' in result.stderr


@pytest.mark.parametrize("enabled,arguments", [(False, True), (True, False)])
def test_worker_diagnostics_are_silent_without_both_explicit_gates(enabled, arguments):
    script = (
        "import runpy, sys, time; "
        f"entry=runpy.run_path({str(ENTRY)!r}); "
        f"sys.argv={['runtime', '--multiprocessing-fork'] if arguments else ['runtime']!r}; "
        "entry['_enable_worker_diagnostics'](0.02); time.sleep(0.09)"
    )
    env = dict(os.environ)
    env.pop("CLEANTAKE_SMOKE_DIAGNOSTICS", None)
    if enabled:
        env["CLEANTAKE_SMOKE_DIAGNOSTICS"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=5, env=env
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr


def test_smoke_snapshot_preserves_failed_job_and_actual_process_but_redacts_token(tmp_path):
    pytest.importorskip("psutil", reason="Runtime harness needs the optional bundle group")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "smoke_runtime", Path(__file__).parents[1] / "scripts/smoke_runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        session = module.Session.__new__(module.Session)
        session.process = process
        session.workspace = tmp_path
        session.token = "private-smoke-token"
        session.errors = ["blocked at private-smoke-token\n"]
        session.last_job = {"id": "job", "status": "running"}
        session.peak_rss = 123
        session.observed = {}
        (tmp_path / "pending/job/projects").mkdir(parents=True)
        (tmp_path / "pending/job/result.json").write_text('{"ok": true}')
        snapshot = session.diagnostics()
        assert snapshot["job"]["status"] == "running"
        assert snapshot["backend_returncode"] is None
        assert any(p["pid"] == process.pid for p in snapshot["processes"])
        assert snapshot["pending_files"] == [{"path": "job/result.json", "bytes": 12}]
        assert snapshot["pending_results"] == {"job": {"ok": True}}
        assert "private-smoke-token" not in json.dumps(snapshot)
        assert "[redacted]" in snapshot["stderr_tail"]
    finally:
        process.kill()
        process.wait(timeout=5)
