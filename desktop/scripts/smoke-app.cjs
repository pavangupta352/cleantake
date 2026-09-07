"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { once } = require("node:events");
const { _electron } = require("playwright");
const { redact } = require("../lib/security.cjs");

const executable = path.resolve(process.env.CLEANTAKE_APP || "");
const workspace = path.resolve(process.env.CLEANTAKE_TEST_WORKSPACE || "");
const directory = path.resolve(process.env.CLEANTAKE_TEST_REPORT_DIR || "");
for (const name of ["CLEANTAKE_APP", "CLEANTAKE_TEST_WORKSPACE", "CLEANTAKE_TEST_REPORT_DIR"]) {
  assert(process.env[name], `${name} is required`);
}
assert(fs.statSync(executable).isFile(), "An actual packaged executable is required");
fs.mkdirSync(directory, { recursive: true });
fs.mkdirSync(path.dirname(workspace), { recursive: true });
const userData = path.join(path.dirname(workspace), "Desktop preferences café");
const fresh = !fs.existsSync(path.join(workspace, ".desktop-initialized.json"));
const env = { ...process.env, PATH: "" };
for (const key of ["ELECTRON_RUN_AS_NODE", "NODE_OPTIONS", "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX"]) delete env[key];
const args = [`--user-data-dir=${userData}`, "--workspace", workspace];
const report = { schema_version: 1, platform: process.platform, architecture: process.arch, started_at: new Date().toISOString(), checks: [] };
let application;
let observer;
let observerPath;
let page;
let run = 0;
const errors = [];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, message, timeout = 60000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const result = await predicate();
    if (result) return result;
    await delay(100);
  }
  throw new Error(message);
}
function passed(name, details = {}) {
  report.checks.push({ name, status: "passed", ...details });
  process.stdout.write(`Passed: ${name}\n`);
}
async function visible(locator) { await locator.waitFor({ state: "visible", timeout: 90000 }); }
async function menuHistory(direction) {
  await application.evaluate(({ Menu, BrowserWindow }, direction) => {
    const edit = Menu.getApplicationMenu().items.find(item => item.label === "Edit");
    const command = edit.submenu.items.find(item => item.role === direction || item.id === `edit-${direction}`);
    if (!command) throw new Error("Native history command is missing");
    command.click(command, BrowserWindow.getAllWindows()[0], {});
  }, direction);
}
async function api(route, body, method = body === undefined ? "GET" : "POST") {
  return page.evaluate(async ({ route, body, method }) => {
    const response = await fetch(route, { method, headers: { "X-CleanTake-Token": sessionStorage.getItem("cleantake-session"), ...(body === undefined ? {} : { "Content-Type": "application/json" }) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    if (!response.ok) throw new Error(`Local test request failed: ${response.status}`);
    return response.json();
  }, { route, body, method });
}
function observed() {
  try { return JSON.parse(fs.readFileSync(observerPath, "utf8")); } catch { return { processes: [] }; }
}
async function launch() {
  run += 1;
  application = await _electron.launch({ executablePath: executable, args, env, chromiumSandbox: true, timeout: 120000 });
  observerPath = path.join(directory, `processes-${run}.json`);
  observer = spawn("uv", ["run", "--group", "bundle", "python", "desktop/scripts/observe-processes.py", "--pid", String(application.process().pid), "--report", observerPath], { cwd: path.resolve(__dirname, "../.."), stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  observer.on("error", error => errors.push(`Process observer: ${error.message}`));
  page = await application.firstWindow({ timeout: 90000 });
  page.on("pageerror", error => errors.push(redact(error.message)));
  await page.addInitScript(() => {
    const NativeContext = window.AudioContext;
    window.__testAudioContexts = [];
    window.AudioContext = class extends NativeContext {
      constructor(...args) { super(...args); window.__testAudioContexts.push(this); }
    };
  });
  await page.waitForURL(/^http:\/\/127\.0\.0\.1:\d+\//, { timeout: 90000 });
  await page.waitForFunction(() => !!sessionStorage.getItem("cleantake-session"));
  // A normal reload also installs the test-only audio-clock observer before app code.
  await page.reload();
  await visible(page.getByRole("button", { name: "Create project", exact: true }));
  await until(() => observed().processes.some(item => item.name.startsWith("cleantake-runtime")), "The real bundled service was not observed");
}
async function close() {
  const start = Date.now();
  const closed = application.waitForEvent("close", { timeout: 25000 });
  await application.evaluate(({ app }) => { setTimeout(() => app.quit(), 0); });
  await closed;
  application = null;
  await until(() => observed().processes.every(item => !item.alive), "An owned process survived desktop shutdown", 12000);
  const finished = once(observer, "exit");
  observer.stdin.end("finish\n");
  const [code] = await finished;
  observer = null;
  assert.equal(code, 0, "Process observer must complete");
  const processes = observed().processes;
  assert(processes.length > 0);
  assert(processes.every(item => !item.alive), "No owned process remains after quit");
  return { elapsed_ms: Date.now() - start, observed_processes: processes.length };
}
async function download(button, name) {
  const destination = path.join(directory, name);
  await application.evaluate(({ session }, destination) => {
    globalThis.__testDownload = new Promise(resolve => {
      session.defaultSession.once("will-download", (_, item) => {
        item.setSavePath(destination);
        item.once("done", (_, state) => resolve(state));
      });
    });
  }, destination);
  await button.click();
  let timer;
  const state = await Promise.race([
    application.evaluate(() => globalThis.__testDownload),
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Native download ${name} did not finish`)), 60000); }),
  ]).finally(() => clearTimeout(timer));
  assert.equal(state, "completed");
  return fs.readFileSync(destination);
}

(async () => {
  try {
    const started = Date.now();
    await launch();
    const shell = await application.evaluate(({ app, BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows()[0];
      const preferences = window.webContents.getLastWebPreferences();
      return { packaged: app.isPackaged, version: app.getVersion(), sandbox: preferences.sandbox, nodeIntegration: preferences.nodeIntegration, contextIsolation: preferences.contextIsolation, visible: window.isVisible(), count: BrowserWindow.getAllWindows().length };
    });
    assert(shell.packaged && shell.sandbox && shell.contextIsolation && !shell.nodeIntegration && shell.visible);
    assert.equal(shell.count, 1);
    assert.equal(await page.evaluate(() => typeof window.require), "undefined");
    assert.equal(await page.evaluate(() => typeof window.process), "undefined");
    assert.equal(new URL(page.url()).hash, "");
    assert.equal(await page.evaluate(async () => (await fetch("/api/projects")).status), 401);
    passed("packaged_first_launch_empty_PATH", { ...shell, elapsed_ms: Date.now() - started, fresh_workspace: fresh });
    await page.screenshot({ path: path.join(directory, "first-launch.png"), fullPage: true });

    const shelf = (await api("/api/projects")).projects;
    assert.equal(shelf.length, 1, "One sample, without duplicate initialization");
    const projectId = shelf[0].id;
    const route = `/api/projects/${projectId}`;
    let project = await api(route);
    assert.equal(project.sources.length, 2);
    assert.equal(project.repairs.length, 1);
    if (fresh) assert.equal(project.repairs[0].status, "proposed");
    else if (project.repairs[0].status !== "proposed") project = await api(`${route}/repairs/${project.repairs[0].id}`, { status: "proposed", expected_revision: project.revision }, "PATCH");
    await page.getByRole("button", { name: /Sample · recover a missing half-second/ }).click();
    await visible(page.getByRole("heading", { name: "Review the performance", exact: true }));
    await page.getByRole("button", { name: /Missing signal/ }).click();
    await visible(page.getByRole("button", { name: "Accept repair", exact: true }));
    await page.getByRole("button", { name: "Listen to source in context", exact: true }).click();
    await visible(page.getByRole("button", { name: "Pause playback", exact: true }));
    const clock = await until(() => page.evaluate(() => {
      const context = window.__testAudioContexts.find(item => item.state === "running");
      return context && { state: context.state, time: context.currentTime, sample_rate: context.sampleRate };
    }), "Actual audio output never started");
    await until(() => page.evaluate(before => window.__testAudioContexts.some(item => item.state === "running" && item.currentTime > before + 0.15), clock.time), "AudioContext clock did not advance");
    await page.getByRole("button", { name: "Original", exact: true }).click();
    await visible(page.getByRole("button", { name: "Pause playback", exact: true }));
    await page.getByRole("button", { name: "Pause playback", exact: true }).click();
    passed("sample_and_real_audio_clock", clock);
    await page.getByRole("button", { name: "Accept repair", exact: true }).click();
    await until(async () => (await api(route)).repairs[0].status === "accepted", "Repair was not saved");
    await page.getByRole("button", { name: "Undo last edit", exact: true }).click();
    await until(async () => (await api(route)).repairs[0].status === "proposed", "Undo was not saved");
    await page.getByRole("button", { name: "Redo last edit", exact: true }).click();
    await until(async () => (await api(route)).repairs[0].status === "accepted", "Redo was not saved");
    passed("repair_undo_redo");
    await menuHistory("undo");
    await until(async () => (await api(route)).repairs[0].status === "proposed", "Native Edit → Undo did not reverse the repair", 5000);
    await menuHistory("redo");
    await until(async () => (await api(route)).repairs[0].status === "accepted", "Native Edit → Redo did not restore the repair", 5000);
    await page.getByRole("button", { name: "Transcript", exact: true }).click();
    const text = page.getByRole("textbox", { name: "Transcript text", exact: true });
    await text.fill("Keep this line.");
    await text.selectText();
    await page.keyboard.insertText("A replacement line.");
    await menuHistory("undo");
    await until(async () => (await text.inputValue()) === "Keep this line.", "Native Undo did not preserve text editing", 5000);
    await menuHistory("redo");
    await until(async () => (await text.inputValue()) === "A replacement line.", "Native Redo did not preserve text editing", 5000);
    assert.equal((await api(route)).repairs[0].status, "accepted");
    await page.getByRole("button", { name: "Close panel", exact: true }).click();
    passed("native_history_and_text_editing");
    await page.screenshot({ path: path.join(directory, "editing.png"), fullPage: true });
    await page.getByRole("button", { name: "Export", exact: true }).click();
    await page.getByRole("button", { name: "Prepare export", exact: true }).click();
    await visible(page.getByRole("heading", { name: /Ready · revision/ }));
    const wav = await download(page.getByRole("button").filter({ hasText: /^dialogue\.wav/ }), "dialogue.wav");
    assert.equal(wav.subarray(0, 4).toString(), "RIFF");
    assert(wav.length > 960000);
    await page.getByRole("button", { name: "Prepare archive", exact: true }).click();
    const archiveButton = page.getByRole("button").filter({ hasText: /\.zip/ });
    await visible(archiveButton);
    const archive = await download(archiveButton, "project.cleantake.zip");
    assert.equal(archive.subarray(0, 2).toString(), "PK");
    passed("native_export_downloads", { wav_bytes: wav.length, archive_bytes: archive.length });
    await page.getByRole("button", { name: "Close panel", exact: true }).click();
    const beforeOrigin = new URL(page.url()).origin;
    await page.evaluate(() => { window.location.href = "https://example.invalid/blocked"; });
    await delay(250);
    assert.equal(new URL(page.url()).origin, beforeOrigin);
    assert.equal((await application.windows()).length, 1);
    passed("external_navigation_denied");

    const duplicate = spawn(executable, args, { env, stdio: "ignore", windowsHide: true });
    let duplicateTimer;
    const [duplicateCode] = await Promise.race([once(duplicate, "exit"), new Promise((_, reject) => { duplicateTimer = setTimeout(() => { duplicate.kill(); reject(new Error("Second instance did not focus the existing studio")); }, 15000); })]).finally(() => clearTimeout(duplicateTimer));
    assert.equal(duplicateCode, 0);
    assert.equal((await application.windows()).length, 1);
    passed("single_instance_focus");

    project = await api(route);
    const job = await api(`${route}/analyze`, { expected_revision: project.revision });
    await until(() => observed().processes.some(item => item.worker && item.alive), "No live analysis worker observed before close", 15000);
    const stopped = await close();
    const jobRecord = JSON.parse(fs.readFileSync(path.join(workspace, "jobs", `${job.id}.json`), "utf8"));
    assert.equal(jobRecord.status, "cancelled");
    assert.deepEqual(fs.readdirSync(path.join(workspace, "pending")), []);
    passed("quit_cancels_worker_without_orphans", stopped);

    await launch();
    assert.equal((await api("/api/projects")).projects.length, 1);
    project = await api(route);
    assert.equal(project.repairs[0].status, "accepted");
    passed("restart_preserves_saved_work");
    await close();
    assert.deepEqual(errors, [], "No renderer or process-monitor errors");
    report.status = "passed";
  } catch (error) {
    report.status = "failed";
    report.error = redact(error.stack || error.message).slice(0, 5000);
    if (page && !page.isClosed()) await page.screenshot({ path: path.join(directory, "failure.png"), fullPage: true }).catch(() => {});
    process.exitCode = 1;
  } finally {
    if (application) await application.close().catch(() => {});
    if (observer) { const done = once(observer, "exit"); observer.stdin.end("cleanup\n"); await done.catch(() => {}); }
    report.finished_at = new Date().toISOString();
    fs.writeFileSync(path.join(directory, "desktop-smoke.json"), JSON.stringify(report, null, 2) + "\n");
    process.stdout.write(JSON.stringify(report, null, 2) + "\n");
  }
})();
