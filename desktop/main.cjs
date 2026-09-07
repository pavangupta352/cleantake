"use strict";

const { app, BrowserWindow, Menu, dialog, shell, screen, session } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { Backend } = require("./lib/backend.cjs");
const { allowsNavigation, allowsExternal, safeBounds, redact } = require("./lib/security.cjs");

const repository = "https://github.com/pavangupta352/cleantake";
app.setName("CleanTake");
app.enableSandbox();
let window = null;
let backend = null;
let origin = null;
let quitting = false;
let quitReady = false;
let opening = false;
let failureDialog = false;
let logPath;
let statePath;

function log(message) {
  if (!logPath) return;
  try {
    if (fs.existsSync(logPath) && fs.statSync(logPath).size > 256 * 1024) {
      fs.renameSync(logPath, `${logPath}.previous`);
    }
    fs.appendFileSync(logPath, `${new Date().toISOString()} ${redact(message)}\n`, { mode: 0o600 });
  } catch { /* Logging must not prevent the editor opening or closing. */ }
}

function workspaceArgument() {
  const index = process.argv.indexOf("--workspace");
  if (index === -1) return [];
  if (!process.argv[index + 1] || process.argv[index + 1].startsWith("--")) {
    throw new Error("Choose a workspace folder after --workspace.");
  }
  return ["--workspace", path.resolve(process.argv[index + 1])];
}

function executable() {
  const name = process.platform === "win32" ? "cleantake-runtime.exe" : "cleantake-runtime";
  return app.isPackaged
    ? path.join(process.resourcesPath, "backend", name)
    : path.resolve(__dirname, "../build/native/runtime/cleantake-runtime", name);
}

async function openExternal(url) {
  if (allowsExternal(url)) await shell.openExternal(url);
}

function saveBounds() {
  if (!window || window.isDestroyed() || window.isMinimized()) return;
  try {
    const temporary = `${statePath}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify({ ...window.getNormalBounds(), maximized: window.isMaximized() }), { mode: 0o600 });
    fs.renameSync(temporary, statePath);
  } catch { /* Window preferences never hold up saved audio work. */ }
}

async function showFailure(message) {
  if (quitting || failureDialog) return;
  failureDialog = true;
  const result = await dialog.showMessageBox(window && !window.isDestroyed() ? window : undefined, {
    type: "error",
    title: "CleanTake could not open",
    message: "Your studio could not start.",
    detail: message,
    buttons: ["Try again", "Show log", "Quit"],
    defaultId: 0,
    cancelId: 2,
    noLink: true,
  });
  failureDialog = false;
  if (result.response === 0) void startStudio();
  else if (result.response === 1) {
    shell.showItemInFolder(logPath);
    void showFailure("The log folder is open. You can try again after resolving the problem.");
  } else app.quit();
}

async function startStudio() {
  if (opening || quitting) return;
  opening = true;
  try {
    origin = null;
    if (backend) await backend.stop();
    if (window && !window.isDestroyed()) await window.loadFile(path.join(__dirname, "launch.html"));
    backend = new Backend({ executable: executable(), args: ["--desktop", ...workspaceArgument()], onLog: log });
    backend.on("unexpected-exit", event => {
      log(`Local service stopped: ${JSON.stringify(event)}`);
      if (!quitting) void showFailure("The audio service stopped unexpectedly. Saved decisions remain available. Try opening the studio again.");
    });
    const ready = await backend.start();
    if (quitting) { await backend.stop(); return; }
    if (ready.version !== app.getVersion()) throw new Error("The application and audio service versions do not match. Reinstall CleanTake and try again.");
    origin = ready.origin;
    await window.loadURL(ready.url);
    log(`Studio ready; version ${ready.version}.`);
  } catch (error) {
    log(error.message);
    if (backend) await backend.stop().catch(failure => log(failure.message));
    void showFailure(error.message);
  } finally { opening = false; }
}

function installMenu() {
  const mac = process.platform === "darwin";
  const template = [
    ...(mac ? [{ label: "CleanTake", submenu: [{ role: "about" }, { type: "separator" }, { role: "services" }, { type: "separator" }, { role: "hide" }, { role: "hideOthers" }, { role: "unhide" }, { type: "separator" }, { role: "quit" }] }] : []),
    { label: "File", submenu: [{ role: "close" }, ...(!mac ? [{ role: "quit" }] : [])] },
    { label: "Edit", submenu: [{ role: "undo" }, { role: "redo" }, { type: "separator" }, { role: "cut" }, { role: "copy" }, { role: "paste" }, { role: "selectAll" }] },
    { label: "View", submenu: [{ label: "Reload studio", accelerator: "CmdOrCtrl+R", click: () => { if (window && origin) window.reload(); } }, { type: "separator" }, { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" }, { type: "separator" }, { role: "togglefullscreen" }] },
    { label: "Window", submenu: [{ role: "minimize" }, { role: "zoom" }, ...(mac ? [{ type: "separator" }, { role: "front" }] : [])] },
    { label: "Help", submenu: [
      { label: "Editing guide", click: () => void openExternal(`${repository}/blob/main/docs/GUIDE.md`) },
      { label: "Downloads and updates", click: () => void openExternal(`${repository}/releases/latest`) },
      { label: "Report a problem", click: () => void openExternal(`${repository}/issues/new/choose`) },
      { label: "Licenses", click: () => void shell.openPath(path.join(process.resourcesPath, "THIRD_PARTY_NOTICES.md")) },
      { type: "separator" },
      { label: "Show log", click: () => shell.showItemInFolder(logPath) },
      ...(!mac ? [{ role: "about" }] : []),
    ] },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function createWindow() {
  fs.mkdirSync(app.getPath("userData"), { recursive: true });
  fs.mkdirSync(app.getPath("logs"), { recursive: true });
  logPath = path.join(app.getPath("logs"), "desktop.log");
  statePath = path.join(app.getPath("userData"), "window.json");
  log(`Opening CleanTake ${app.getVersion()} on ${process.platform}/${process.arch}.`);
  let saved;
  try { saved = JSON.parse(fs.readFileSync(statePath, "utf8")); } catch { saved = null; }
  const displays = screen.getAllDisplays().map(display => display.workArea);
  const bounds = safeBounds(saved, displays);
  window = new BrowserWindow({
    ...bounds,
    minWidth: Math.min(760, bounds.width), minHeight: Math.min(560, bounds.height),
    title: "CleanTake", backgroundColor: "#f9fafc", show: false,
    icon: path.join(__dirname, "resources", "icon.png"),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, webviewTag: false, devTools: !app.isPackaged },
  });
  window.once("ready-to-show", () => { if (saved?.maximized) window.maximize(); window.show(); });
  window.on("close", saveBounds);
  window.webContents.on("will-navigate", (event, url) => {
    if (!origin || !allowsNavigation(url, origin)) { event.preventDefault(); void openExternal(url); }
  });
  window.webContents.on("will-redirect", (event, url) => { if (!origin || !allowsNavigation(url, origin)) event.preventDefault(); });
  window.webContents.setWindowOpenHandler(({ url }) => { void openExternal(url); return { action: "deny" }; });
  window.webContents.on("will-attach-webview", event => event.preventDefault());
  window.webContents.on("render-process-gone", (_, details) => { log(`Renderer stopped: ${details.reason}`); if (!quitting) void showFailure("The editing window stopped. Reopen it to continue from your saved project."); });
  session.defaultSession.setPermissionRequestHandler((_, __, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  session.defaultSession.on("will-download", (_, item, contents) => {
    if (contents !== window?.webContents || !origin || !allowsNavigation(item.getURL(), origin)) { item.cancel(); return; }
    item.setSaveDialogOptions({ title: "Save CleanTake export", defaultPath: path.join(app.getPath("downloads"), path.basename(item.getFilename())) });
  });
  installMenu();
  await startStudio();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { if (window) { if (window.isMinimized()) window.restore(); window.show(); window.focus(); } });
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", event => {
    if (quitReady) return;
    event.preventDefault();
    if (quitting) return;
    quitting = true;
    saveBounds();
    Promise.resolve(backend?.stop()).catch(error => log(error.message)).finally(() => { quitReady = true; app.quit(); });
  });
  app.whenReady().then(createWindow).catch(error => { log(error.message); dialog.showErrorBox("CleanTake could not open", "Reinstall the application and try again."); app.quit(); });
}
