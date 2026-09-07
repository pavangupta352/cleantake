# CleanTake studio

The local React/TypeScript editor for CleanTake. The production build is served by the Python loopback server; it uses the API documented in [docs/API.md](../docs/API.md).

## Build and test

Install the Python project with `uv sync --locked` from the repository root and make FFmpeg available on `PATH`. Then, in this directory:

```sh
npm ci
npm run build
npx playwright install chromium firefox webkit
npm run test:e2e
```

On Linux, use `npx playwright install --with-deps chromium firefox webkit` to
install the browser system libraries as well.

The browser tests start the real Python API in an isolated temporary workspace on port 8765 and a Vite server on port 5173. Those ports must be available. Test workspaces are removed on shutdown. The fixed session token in the test launcher is exclusively for this temporary test service; normal studio launches generate their own token.

Tests import the licensed, distinct microphone recordings in `tests/engine/data`, with explicitly injected dropout and level-change fixtures made in temporary directories. See the fixture [attribution](../tests/engine/data/ATTRIBUTION.md). The playback continuity test repeats actual recorded material for a longer test window. No sample projects or generated waveforms are supplied to the production interface. Network fault checks hold actual server responses to test underrun and edit races.

For frontend development, `npm run dev` proxies `/api` to the loopback server on port 8765 while preserving the browser origin. Requests require the studio session fragment supplied by the running Python process. Do not include session tokens in issue reports or screenshots.

## Listening and persistence

The primary recording defines project time. Waveform bins come from the server's actual sample minima and maxima. Uncertain sources are labeled as using their own clock and cannot supply synchronized playback until aligned.

Playback schedules 20-second WAV windows on one Web Audio clock, keeps at most two scheduled buffers, and cancels stale requests on seek, project changes, or revisions. Original, Repair, and Source comparisons retain the current project position. An underrun stops at the last heard frame.

Edits carry the current revision. Conflicts refresh the project and ask the editor to review the newer state. Only accepted repairs reach the output. Export downloads use short-lived tickets scoped to one artifact; portable archives explicitly include original media.
