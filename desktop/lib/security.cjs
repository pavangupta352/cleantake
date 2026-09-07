"use strict";

function readyMessage(value) {
  if (!value || value.event !== "ready" || typeof value.version !== "string" ||
      typeof value.url !== "string" || value.url.length > 1024) {
    throw new Error("The local studio sent an invalid startup response.");
  }
  let url;
  try { url = new URL(value.url); } catch { throw new Error("The local studio address is invalid."); }
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" ||
      !url.port || url.username || url.password || url.pathname !== "/" || url.search ||
      !/^#token=[A-Za-z0-9_-]{32,128}$/.test(url.hash)) {
    throw new Error("The local studio did not provide a private loopback session.");
  }
  return { url: url.href, origin: url.origin, version: value.version };
}

function allowsNavigation(value, origin) {
  try {
    const url = new URL(value);
    return url.origin === origin && url.protocol === "http:" && !url.username && !url.password;
  } catch { return false; }
}

function allowsExternal(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "github.com" &&
      !url.username && !url.password && !url.port &&
      (url.pathname === "/pavangupta352/cleantake" ||
       url.pathname.startsWith("/pavangupta352/cleantake/"));
  } catch { return false; }
}

function safeBounds(saved, areas) {
  const primary = areas[0];
  const finite = saved && ["x", "y", "width", "height"].every(key => Number.isFinite(saved[key]));
  const containing = finite && areas.find(area =>
    saved.x >= area.x && saved.y >= area.y &&
    saved.width >= Math.min(760, area.width) && saved.height >= Math.min(560, area.height) &&
    saved.x + saved.width <= area.x + area.width && saved.y + saved.height <= area.y + area.height);
  if (containing) return Object.fromEntries(["x", "y", "width", "height"].map(key => [key, Math.round(saved[key])]));
  const width = Math.min(1440, Math.max(1, primary.width - 48));
  const height = Math.min(960, Math.max(1, primary.height - 48));
  return {
    x: Math.round(primary.x + (primary.width - width) / 2),
    y: Math.round(primary.y + (primary.height - height) / 2),
    width, height,
  };
}

function redact(value) {
  return String(value)
    .replace(/([#?&](?:token|ticket)=)[^\s&"'<>]+/gi, "$1[redacted]")
    .replace(/("(?:token|ticket)"\s*:\s*")[^"]+/gi, "$1[redacted]");
}

module.exports = { readyMessage, allowsNavigation, allowsExternal, safeBounds, redact };
