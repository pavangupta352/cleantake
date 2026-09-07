const assert = require("node:assert/strict");
const { test } = require("node:test");
const { readyMessage, allowsNavigation, allowsExternal, safeBounds, redact } = require("../lib/security.cjs");

test("accepts only a bounded token-bearing loopback ready message", () => {
  const token = "a".repeat(43);
  const message = readyMessage({ event: "ready", version: "0.2.0", url: `http://127.0.0.1:43123/#token=${token}` });
  assert.equal(message.origin, "http://127.0.0.1:43123");
  for (const url of [
    `https://127.0.0.1:43123/#token=${token}`,
    `http://localhost:43123/#token=${token}`,
    `http://127.0.0.1.evil.test:43123/#token=${token}`,
    `http://user@127.0.0.1:43123/#token=${token}`,
    `http://127.0.0.1:43123/api/health#token=${token}`,
    `http://127.0.0.1:43123/?token=${token}`,
    "http://127.0.0.1:43123/#token=short",
  ]) assert.throws(() => readyMessage({ event: "ready", version: "0.2.0", url }));
  assert.throws(() => readyMessage({ event: "ready", version: "0.2.0", url: "x".repeat(5000) }));
});

test("renderer navigation cannot change origin or open arbitrary external schemes", () => {
  const origin = "http://127.0.0.1:43123";
  assert.equal(allowsNavigation(`${origin}/`, origin), true);
  assert.equal(allowsNavigation(`${origin}/api/projects`, origin), true);
  for (const url of ["file:///etc/passwd", "javascript:alert(1)", "https://example.com", "http://127.0.0.1:43124/"])
    assert.equal(allowsNavigation(url, origin), false);
  assert.equal(allowsExternal("https://github.com/pavangupta352/cleantake/releases/latest"), true);
  for (const url of ["https://github.com/pavangupta352/cleantake-other", "https://evil.test", "file:///tmp/x", "https://user@github.com/pavangupta352/cleantake"])
    assert.equal(allowsExternal(url), false);
});

test("window restoration fits an available display after a monitor disappears", () => {
  const area = { x: 0, y: 25, width: 1280, height: 775 };
  const normal = safeBounds({ x: 50, y: 60, width: 1000, height: 650 }, [area]);
  assert.deepEqual(normal, { x: 50, y: 60, width: 1000, height: 650 });
  const recovered = safeBounds({ x: 4000, y: -900, width: 2000, height: 1400 }, [area]);
  assert.ok(recovered.x >= area.x && recovered.y >= area.y);
  assert.ok(recovered.x + recovered.width <= area.width);
  assert.ok(recovered.y + recovered.height <= area.y + area.height);
  const invalid = safeBounds({ x: NaN, y: Infinity, width: -1, height: "large" }, [area]);
  assert.ok(Number.isFinite(invalid.width) && invalid.width > 0);
  const tiny = safeBounds({ x: 1200, y: 700, width: 1, height: 1 }, [area]);
  assert.ok(tiny.width >= 760 && tiny.x + tiny.width <= area.width);
});

test("diagnostics redact launch tokens and scoped download tickets", () => {
  const line = 'ready http://127.0.0.1:43123/#token=private-token\nGET /x?ticket=private-ticket&name=test';
  const cleaned = redact(line);
  assert.ok(!cleaned.includes("private-token"));
  assert.ok(!cleaned.includes("private-ticket"));
  assert.ok(cleaned.includes("name=test"));
});
