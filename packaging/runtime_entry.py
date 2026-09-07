"""Minimal entry point: dispatch frozen workers before application imports."""

if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()

    import sys

    if "--desktop" in sys.argv[1:]:
        from cleantake.desktop import main

        raise SystemExit(main())
    else:
        from cleantake.cli import app

        app()
