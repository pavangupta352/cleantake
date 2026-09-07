"use strict";

const { EventEmitter } = require("node:events");
const { spawn, execFile } = require("node:child_process");
const { promisify } = require("node:util");
const path = require("node:path");
const fs = require("node:fs");
const { readyMessage, redact } = require("./security.cjs");
const run = promisify(execFile);

async function terminateTree(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  if (process.platform === "win32") {
    const binary = path.join(process.env.SystemRoot || "C:\\Windows", "System32", "taskkill.exe");
    try { await run(binary, ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, timeout: 5000 }); }
    catch { if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL"); }
    return;
  }
  // Workers start their own process groups; enumerate only this child's tree.
  let descendants = [];
  try {
    const binary = ["/bin/ps", "/usr/bin/ps"].find(candidate => fs.existsSync(candidate));
    const { stdout } = await run(binary, ["-axo", "pid=,ppid="], { timeout: 2000, maxBuffer: 4 * 1024 * 1024 });
    const entries = stdout.trim().split("\n").map(line => line.trim().split(/\s+/).map(Number));
    const owned = new Set([child.pid]);
    for (let changed = true; changed;) {
      changed = false;
      for (const [pid, parent] of entries) {
        if (owned.has(parent) && !owned.has(pid)) { owned.add(pid); descendants.push(pid); changed = true; }
      }
    }
  } catch { /* The tracked child can still be terminated if process inspection failed. */ }
  if (child.exitCode !== null || child.signalCode !== null) return;
  for (const pid of descendants.reverse()) {
    try { process.kill(pid, "SIGKILL"); } catch (error) { if (error.code !== "ESRCH") throw error; }
  }
  child.kill("SIGKILL");
}

class Backend extends EventEmitter {
  constructor(options) {
    super();
    this.options = options;
    this.child = null;
    this.stopping = false;
    this.startPromise = null;
    this.stopPromise = null;
  }

  get pid() { return this.child?.pid; }

  start() {
    if (this.startPromise) return this.startPromise;
    this.startPromise = new Promise((resolve, reject) => {
      let settled = false;
      let buffered = "";
      let timer;
      const fail = error => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this.stop().then(() => reject(error), () => reject(error));
      };
      try {
        this.child = spawn(this.options.executable, this.options.args || ["--desktop"], {
          cwd: this.options.cwd,
          env: this.options.env || process.env,
          stdio: ["pipe", "pipe", "pipe"],
          windowsHide: true,
          shell: false,
        });
      } catch (error) { reject(error); return; }
      this.exitPromise = new Promise(done => this.child.once("exit", (code, signal) => {
        done({ code, signal });
        if (!settled) fail(new Error("The local studio stopped before it was ready. Open the log for details."));
        else if (!this.stopping) this.emit("unexpected-exit", { code, signal });
      }));
      this.child.once("error", error => { this.spawnError = error; fail(new Error("CleanTake could not start its bundled audio service. Reinstall the application and try again.")); });
      this.child.stdin.on("error", () => { /* A closing child can close its control pipe first. */ });
      this.child.stderr.setEncoding("utf8");
      let diagnostic = "";
      let oversized = false;
      this.child.stderr.on("data", data => {
        diagnostic += data;
        let newline;
        while ((newline = diagnostic.indexOf("\n")) !== -1) {
          const line = diagnostic.slice(0, newline + 1);
          diagnostic = diagnostic.slice(newline + 1);
          if (!oversized && line.length <= 65536) this.options.onLog?.(redact(line));
          oversized = false;
        }
        if (diagnostic.length > 65536) { diagnostic = ""; oversized = true; }
      });
      this.child.stderr.on("end", () => {
        if (diagnostic && !oversized) this.options.onLog?.(redact(diagnostic));
      });
      this.child.stdout.setEncoding("utf8");
      this.child.stdout.on("data", data => {
        if (settled) return;
        buffered += data;
        if (buffered.length > 65536) { fail(new Error("The local studio startup response was too large.")); return; }
        let newline;
        while (!settled && (newline = buffered.indexOf("\n")) !== -1) {
          const line = buffered.slice(0, newline);
          buffered = buffered.slice(newline + 1);
          try {
            const record = JSON.parse(line);
            if (record.event === "error") {
              const message = typeof record.message === "string" ? redact(record.message).slice(0, 500) : "The local studio could not start.";
              const error = new Error(message);
              error.code = record.code;
              fail(error);
            } else {
              const ready = readyMessage(record);
              settled = true;
              clearTimeout(timer);
              resolve(ready);
            }
          } catch { fail(new Error("The local studio sent an invalid startup response.")); }
        }
      });
      timer = setTimeout(() => fail(new Error("The local studio did not become ready. Try again or open the log for details.")), this.options.startupTimeout || 90000);
    });
    return this.startPromise;
  }

  stop() {
    if (this.stopPromise) return this.stopPromise;
    this.stopping = true;
    this.stopPromise = (async () => {
      if (!this.child || this.spawnError || this.child.exitCode !== null || this.child.signalCode !== null) return;
      if (!this.child.stdin.destroyed) this.child.stdin.end("shutdown\n");
      let timeout;
      const exited = await Promise.race([
        this.exitPromise.then(() => true),
        new Promise(resolve => { timeout = setTimeout(() => resolve(false), this.options.stopTimeout || 15000); }),
      ]);
      clearTimeout(timeout);
      if (!exited) {
        await terminateTree(this.child);
        await this.exitPromise;
      }
    })();
    return this.stopPromise;
  }
}

module.exports = { Backend, terminateTree };
