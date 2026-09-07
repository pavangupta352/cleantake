"""Run the real loopback API in an isolated workspace for browser checks."""

from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from cleantake.server import create_app

if __name__ == "__main__":
    with TemporaryDirectory(prefix="cleantake-browser-") as directory:
        uvicorn.run(
            create_app(Path(directory), token="cleantake-browser-test-session"),
            host="127.0.0.1",
            port=8765,
            access_log=False,
            log_level="warning",
        )
