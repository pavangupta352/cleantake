const assert = require("node:assert/strict");
const { test } = require("node:test");
const { once } = require("node:events");
const { Backend } = require("../lib/backend.cjs");

const token = "a".repeat(43);
const launch = `http://127.0.0.1:43123/#token=${token}`;
const childCode = `
  process.stdout.write(JSON.stringify({event:'ready',version:'0.2.0',url:'${launch}'})+'\\n');
  process.stdin.on('data', chunk => {if(chunk.toString().includes('shutdown')) process.exit(0)});
  process.stdin.on('end', () => process.exit(0));
`;

test("real backend process completes handshake then exits through the control pipe", async () => {
  const logs = [];
  const backend = new Backend({ executable: process.execPath, args: ["-e", childCode], onLog: text => logs.push(text) });
  const ready = await backend.start();
  assert.equal(ready.url, launch);
  assert.ok(backend.pid > 0);
  const pid = backend.pid;
  await backend.stop();
  assert.throws(() => process.kill(pid, 0));
  assert.ok(!logs.join("").includes(token));
});

test("a startup failure is actionable and does not leave the child running", async () => {
  const backend = new Backend({ executable: process.execPath, args: ["-e", "process.stdout.write(JSON.stringify({event:'error',code:'workspace_busy',message:'Close the other studio and try again.'})+'\\n');process.exit(2)" ] });
  await assert.rejects(backend.start(), /Close the other studio/);
  await backend.stop();
});

test("rejects invalid handshake and bounds a child that never becomes ready", async () => {
  for (const code of [
    "process.stdout.write(JSON.stringify({event:'ready',version:'0.2.0',url:'https://evil.test/#token=x'})+'\\n');setInterval(()=>{},1000)",
    "setInterval(()=>{},1000)",
  ]) {
    const backend = new Backend({ executable: process.execPath, args: ["-e", code], startupTimeout: 150, stopTimeout: 80 });
    await assert.rejects(backend.start());
    const pid = backend.pid;
    await backend.stop();
    if (pid) assert.throws(() => process.kill(pid, 0));
  }
});

test("unexpected exit after startup is reported once", async () => {
  const backend = new Backend({ executable: process.execPath, args: ["-e", childCode] });
  await backend.start();
  const failure = once(backend, "unexpected-exit");
  process.kill(backend.pid, "SIGTERM");
  const [event] = await failure;
  assert.ok(event.signal || event.code !== 0);
  await backend.stop();
});

test("a missing executable rejects cleanly", async () => {
  const backend = new Backend({ executable: "/missing-cleantake-runtime", startupTimeout: 500 });
  await assert.rejects(backend.start(), /could not start/);
  await backend.stop();
});

test("a diagnostic token split across pipe chunks is still redacted", async () => {
  const logs = [];
  const code = `process.stderr.write('http://127.0.0.1:43123/#tok');setTimeout(() => {process.stderr.write('en=private-secret\\n');${childCode}}, 30);`;
  const backend = new Backend({ executable: process.execPath, args: ["-e", code], onLog: line => logs.push(line) });
  await backend.start();
  await backend.stop();
  assert.ok(!logs.join("").includes("private-secret"));
});
