from __future__ import annotations

import contextlib
import multiprocessing
import os
import select
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


def _guarded_worker(connection, gate):
    from cleantake.server.jobs import _guard_worker_lifetime

    gate.wait()
    _guard_worker_lifetime()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    connection.send(child.pid)
    child.wait()


def _broker(connection, gate):
    worker = multiprocessing.get_context("spawn").Process(
        target=_guarded_worker, args=(connection, gate)
    )
    worker.start()
    connection.send(worker.pid)
    time.sleep(60)


@contextlib.contextmanager
def _exit_observer(pid):
    """Observe the actual process identity without mistaking a zombie for a survivor."""
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = ctypes.c_void_p(kernel.OpenProcess(0x100000, False, pid))
        assert handle.value
        try:
            yield lambda timeout: kernel.WaitForSingleObject(handle, int(timeout * 1000)) == 0
        finally:
            kernel.CloseHandle(handle)
    elif sys.platform == "darwin":
        events = select.kqueue()
        events.control(
            [
                select.kevent(
                    pid,
                    filter=select.KQ_FILTER_PROC,
                    flags=select.KQ_EV_ADD,
                    fflags=select.KQ_NOTE_EXIT,
                )
            ],
            0,
            0,
        )
        try:
            yield lambda timeout: bool(events.control([], 1, timeout))
        finally:
            events.close()
    else:
        descriptor = os.pidfd_open(pid)
        try:
            yield lambda timeout: bool(select.select([descriptor], [], [], timeout)[0])
        finally:
            os.close(descriptor)


@pytest.mark.parametrize("parent_dies_before_guard", [False, True])
def test_worker_and_child_exit_when_actual_parent_dies(parent_dies_before_guard):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    gate = context.Event()
    broker = context.Process(target=_broker, args=(sender, gate))
    broker.start()
    sender.close()
    owned = []
    try:
        assert receiver.poll(15), "Broker did not start its worker"
        worker_pid = receiver.recv()
        owned.append(worker_pid)
        with contextlib.ExitStack() as stack:
            worker_exited = stack.enter_context(_exit_observer(worker_pid))
            if not parent_dies_before_guard:
                gate.set()
                assert receiver.poll(15), "Guarded worker did not create its child"
                child_pid = receiver.recv()
                owned.append(child_pid)
                child_exited = stack.enter_context(_exit_observer(child_pid))
            broker.kill()
            broker.join(timeout=5)
            gate.set()
            assert worker_exited(5), "Worker survived its parent"
            owned.remove(worker_pid)
            if not parent_dies_before_guard:
                assert child_exited(5), "Media-style child survived its worker"
                owned.remove(child_pid)
            else:
                assert receiver.poll(1)
                with pytest.raises(EOFError):
                    receiver.recv()
    finally:
        if broker.is_alive():
            broker.kill()
        broker.join(timeout=5)
        broker.close()
        receiver.close()
        for pid in owned:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize(
    "failure", [OSError("unavailable"), subprocess.TimeoutExpired("taskkill", 5)]
)
def test_taskkill_failure_still_stops_and_joins_actual_worker(monkeypatch, failure):
    import cleantake.server.jobs as jobs

    worker = multiprocessing.get_context("spawn").Process(target=time.sleep, args=(60,))
    worker.start()
    try:

        def unavailable(*args, **kwargs):
            raise failure

        monkeypatch.setattr(jobs, "os", SimpleNamespace(name="nt", environ=os.environ))
        monkeypatch.setattr(jobs.subprocess, "run", unavailable)
        jobs.JobManager._stop(None, worker)
        assert not worker.is_alive()
        assert worker.exitcode is not None
    finally:
        if worker.is_alive():
            worker.kill()
        worker.join(timeout=5)
        worker.close()
