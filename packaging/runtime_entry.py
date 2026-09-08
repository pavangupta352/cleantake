"""Minimal entry point: dispatch frozen workers before application imports."""

def _enable_worker_diagnostics(timeout=30):
    """Expose a stuck frozen worker only during an explicit smoke investigation."""
    import os
    import sys

    if (os.environ.get("CLEANTAKE_SMOKE_DIAGNOSTICS") == "1"
            and "--multiprocessing-fork" in sys.argv[1:]):
        import faulthandler

        faulthandler.enable()
        faulthandler.dump_traceback_later(timeout, repeat=True)


if __name__ == "__main__":
    import multiprocessing

    _enable_worker_diagnostics()
    multiprocessing.freeze_support()

    import sys

    if "--desktop" in sys.argv[1:]:
        from cleantake.desktop import main

        raise SystemExit(main())
    else:
        from cleantake.cli import app

        app()
