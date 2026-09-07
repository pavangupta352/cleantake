"""Observe only the packaged app's descendants during the desktop smoke test."""

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import psutil

parser = argparse.ArgumentParser()
parser.add_argument("--pid", type=int, required=True)
parser.add_argument("--report", type=Path, required=True)
options = parser.parse_args()
root = psutil.Process(options.pid)
observed = {}
stop = threading.Event()
cleanup = False


def control():
    global cleanup
    cleanup = sys.stdin.readline().strip() == "cleanup"
    stop.set()


threading.Thread(target=control, daemon=True).start()


def live(process):
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def snapshot(final=False):
    result = {
        "root_pid": options.pid,
        "final": final,
        "processes": [
            {"pid": pid, "name": data[1], "worker": data[2], "alive": live(data[0])}
            for pid, data in observed.items()
        ],
    }
    temporary = options.report.with_suffix(".tmp")
    temporary.write_text(json.dumps(result), encoding="utf-8")
    temporary.replace(options.report)


last = 0
while not stop.is_set():
    try:
        for process in root.children(recursive=True):
            try:
                observed[process.pid] = (
                    process,
                    process.name(),
                    "--multiprocessing-fork" in process.cmdline(),
                )
            except psutil.Error:
                pass
    except psutil.Error:
        pass
    if time.monotonic() - last > 0.1:
        snapshot()
        last = time.monotonic()
    stop.wait(0.01)
if cleanup:
    for process, _, _ in reversed(list(observed.values())):
        if live(process):
            try:
                process.kill()
            except psutil.Error:
                pass
snapshot(final=True)
