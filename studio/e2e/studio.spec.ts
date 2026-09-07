import {
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { test } from "./test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, join } from "node:path";

const token = "cleantake-browser-test-session";
const headers = { "X-CleanTake-Token": token };
let fixtures: string;
const lapel = resolve("../tests/engine/data/ES2004a_0324-0344_Lapel-0.wav");
test.beforeAll(() => {
  fixtures = mkdtempSync(join(tmpdir(), "cleantake-e2e-input-"));
  execFileSync("uv", ["run", "python", "e2e/fixtures.py", fixtures]);
});
test.afterAll(() => rmSync(fixtures, { recursive: true, force: true }));
async function create(page: Page, name: string) {
  await page.goto(`/#token=${token}`);
  await page
    .getByRole("textbox", { name: "Project name", exact: true })
    .fill(name);
  await page
    .getByRole("button", { name: "Create project", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Start with your main recording." }),
  ).toBeVisible();
}
async function importRecordings(page: Page, files: string[]) {
  await page
    .getByLabel("Import recordings", { exact: true })
    .setInputFiles(files);
  await expect(
    page.getByRole("button", { name: "Align & analyze", exact: true }),
  ).toBeEnabled({ timeout: 60_000 });
  await expect(
    page.getByText(new RegExp(`^${files.length} of 4 recordings`)),
  ).toBeVisible();
}
async function projectByName(request: APIRequestContext, name: string) {
  const shelf = await request.get("/api/projects", { headers });
  expect(shelf.ok()).toBeTruthy();
  const matches = (await shelf.json()).projects.filter(
    (item: { name: string }) => item.name === name,
  );
  expect(matches, `one test project named ${name}`).toHaveLength(1);
  const item = matches[0];
  return (await request.get(`/api/projects/${item.id}`, { headers })).json();
}
async function expectSharedTimelineCoordinates(page: Page) {
  const geometry = await page.evaluate(() => {
    const lanes = Array.from(document.querySelectorAll(".waveform")).map(
      (lane) => {
        const bounds = lane.getBoundingClientRect();
        return { left: bounds.left, width: bounds.width };
      },
    );
    const ticks = Array.from(
      document.querySelectorAll(".timeline-ruler > div > span"),
    ).flatMap((tick, index) => {
      if (getComputedStyle(tick).display === "none") return [];
      const anchor = tick.getBoundingClientRect();
      const label = (tick.querySelector("span") || tick).getBoundingClientRect();
      return [{
        fraction: index / 4,
        x: anchor.left + Number.parseFloat(getComputedStyle(tick, "::after").left),
        labelLeft: label.left,
        labelRight: label.right,
      }];
    });
    return { lanes, ticks, viewport: innerWidth };
  });
  expect(geometry.lanes).toHaveLength(3);
  expect(geometry.ticks.length).toBeGreaterThanOrEqual(3);
  for (const tick of geometry.ticks) {
    for (const lane of geometry.lanes) {
      expect.soft(
        Math.abs(tick.x - (lane.left + lane.width * tick.fraction)),
        `${geometry.viewport}px: ruler tick at ${tick.fraction * 100}% aligns with every waveform`,
      ).toBeLessThanOrEqual(0.5);
    }
    const lane = geometry.lanes[0];
    expect.soft(tick.labelLeft).toBeGreaterThanOrEqual(lane.left - 0.5);
    expect.soft(tick.labelRight).toBeLessThanOrEqual(lane.left + lane.width + 0.5);
    expect.soft(tick.labelLeft).toBeGreaterThanOrEqual(0);
    expect.soft(tick.labelRight).toBeLessThanOrEqual(geometry.viewport);
  }
}

test("a new editor can identify the local import path without sample data", async ({
  page,
  browserName,
}) => {
  await page.goto(`/#token=${token}`);
  await expect(
    page.getByRole("heading", {
      name: /Every take has another chance.|Your recording desk./,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create project", exact: true }),
  ).toBeEnabled();
  await expect(page).not.toHaveURL(/token=/);
  expect(
    await page.evaluate(() => sessionStorage.getItem("cleantake-session")),
  ).toBe(token);
  // macOS WebKit uses Option+Tab to include links and buttons in keyboard navigation.
  await page.keyboard.press(
    browserName === "webkit" && process.platform === "darwin" ? "Alt+Tab" : "Tab",
  );
  await expect(
    page.getByRole("link", { name: "Skip to editor" }),
  ).toBeFocused();
});

test("real recordings flow through analysis, shared-time audition, decisions, reopening, transcripts, and portable exports", async ({
  page,
  request,
  projectName,
}, testInfo) => {
  const errors: string[] = [];
  const audioWindows: URL[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("request", (request) => {
    if (request.url().includes("/audio?"))
      audioWindows.push(new URL(request.url()));
  });
  const name = projectName("AMI dialogue · controlled dropout");
  await create(page, name);
  await importRecordings(page, [
    join(fixtures, "Headset-injected-dropout.wav"),
    lapel,
  ]);
  await page
    .getByRole("button", { name: "Align & analyze", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: /Missing signal/ }),
  ).toBeVisible({ timeout: 60_000 });
  let saved = await projectByName(request, name);
  expect(saved.repairs).toHaveLength(1);
  expect(saved.repairs[0].status).toBe("proposed");
  expect(saved.sources[1].alignment.status).toBe("aligned");
  await expect(
    page.getByRole("img", { name: /actual audio waveform/ }),
  ).toHaveCount(3);
  await page.getByRole("button", { name: /Missing signal/ }).click();
  await page
    .getByRole("button", { name: "Listen to source in context", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Pause playback", exact: true }),
  ).toBeVisible();
  const before = await page.getByLabel("Playhead time").textContent();
  await page.getByRole("button", { name: "Original", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Pause playback", exact: true }),
  ).toBeVisible();
  const after = await page.getByLabel("Playhead time").textContent();
  expect(
    Number(after!.split(":").at(-1)) - Number(before!.split(":").at(-1)),
  ).toBeLessThan(1);
  expect(
    audioWindows.some((url) => url.searchParams.get("mode") === "source"),
  ).toBeTruthy();
  expect(
    audioWindows.some((url) => url.searchParams.get("mode") === "original"),
  ).toBeTruthy();
  for (const url of audioWindows) {
    expect(
      (Number(url.searchParams.get("end_frame")) -
        Number(url.searchParams.get("start_frame"))) /
        48000,
    ).toBeLessThanOrEqual(120);
    expect(url.searchParams.has("token")).toBeFalsy();
  }
  await page
    .getByRole("button", { name: "Pause playback", exact: true })
    .click();
  const beforeFocus = await page.getByLabel("Playhead time").textContent();
  await page.getByLabel("Go to (s)", { exact: true }).focus();
  await page
    .getByRole("heading", { name: "Review the performance", exact: true })
    .click();
  await expect(page.getByLabel("Playhead time")).toHaveText(beforeFocus!);
  await page
    .getByRole("button", { name: "Accept repair", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Undo last edit", exact: true }),
  ).toBeEnabled();
  saved = await projectByName(request, name);
  expect(saved.repairs[0].status).toBe("accepted");
  await page
    .getByRole("button", { name: "Undo last edit", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Redo last edit", exact: true }),
  ).toBeEnabled();
  expect((await projectByName(request, name)).repairs[0].status).toBe(
    "proposed",
  );
  await page
    .getByRole("button", { name: "Redo last edit", exact: true })
    .click();
  await expect
    .poll(async () => (await projectByName(request, name)).repairs[0].status)
    .toBe("accepted");
  await page
    .getByRole("button", { name: "Accepted", exact: false })
    .filter({ hasText: /^Accepted/ })
    .first()
    .click();
  await page.getByRole("button", { name: /Missing signal/ }).click();
  await page.getByLabel("Gain (dB)", { exact: true }).fill("1.5");
  await page
    .getByRole("button", { name: "Save passage changes", exact: true })
    .click();
  await expect
    .poll(async () => (await projectByName(request, name)).repairs[0].gain_db)
    .toBe(1.5);
  await page.getByRole("button", { name: "Transcript", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Transcript text", exact: true })
    .fill(
      "WEBVTT\n\n00:00:17.000 --> 00:00:17.500\nA passage for navigation. <script>window.bad = true</script>\n",
    );
  await page
    .getByRole("button", { name: "Import transcript", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: /A passage for navigation/ }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => (window as unknown as { bad?: boolean }).bad),
  ).toBeUndefined();
  await page.getByRole("button", { name: /A passage for navigation/ }).click();
  await expect(page.getByLabel("Playhead time")).toHaveText("00:17.000");
  await page.getByRole("button", { name: "Close panel", exact: true }).click();
  await page
    .getByRole("button", { name: "CleanTake project shelf", exact: true })
    .click();
  await page
    .getByRole("button", { name: new RegExp(name) })
    .click();
  saved = await projectByName(request, name);
  expect(saved.repairs[0].status).toBe("accepted");
  expect(saved.transcripts).toHaveLength(1);
  await page
    .getByRole("button", { name: "Accepted", exact: false })
    .filter({ hasText: /^Accepted/ })
    .first()
    .click();
  await page.getByRole("button", { name: /Missing signal/ }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(
    page.getByText("Loading waveform…", { exact: true }),
  ).toHaveCount(0);
  await expectSharedTimelineCoordinates(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath("studio-desktop.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expectSharedTimelineCoordinates(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath("studio-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  const overflowing = await page.evaluate(() =>
    Array.from(document.querySelectorAll("body *"))
      .filter(
        (element) => element.getBoundingClientRect().right > innerWidth + 1,
      )
      .map((element) => ({
        tag: element.tagName,
        class: element.className,
        right: element.getBoundingClientRect().right,
      }))
      .slice(0, 12),
  );
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
    JSON.stringify(overflowing),
  ).toBeLessThanOrEqual(390);
  await expect(
    page.getByRole("button", { name: "Play audio", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page
    .getByRole("button", { name: "Prepare export", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /Ready · revision/ }),
  ).toBeVisible({ timeout: 60_000 });
  const wavButton = page
    .getByRole("button")
    .filter({ hasText: /^dialogue\.wav/ });
  await expect(wavButton).toBeVisible();
  const downloadEvent = page.waitForEvent("download");
  await wavButton.click();
  const download = await downloadEvent;
  const audio = testInfo.outputPath("exported.wav");
  await download.saveAs(audio);
  const bytes = readFileSync(audio);
  expect(bytes.subarray(0, 4).toString()).toBe("RIFF");
  const check = execFileSync("uv", [
    "run",
    "python",
    "-c",
    "import soundfile as s, numpy as n, sys; a,r=s.read(sys.argv[1]); assert r==48000; assert len(a)==20*r; assert n.sqrt(n.mean(a[int(17.1*r):int(17.4*r)]**2))>.001",
    audio,
  ]);
  expect(check.toString()).toBe("");
  await page
    .getByRole("button", { name: "Prepare archive", exact: true })
    .click();
  const archiveButton = page.getByRole("button").filter({ hasText: /\.zip/ });
  await expect(archiveButton).toBeVisible({ timeout: 60_000 });
  const archiveDownload = page.waitForEvent("download");
  await archiveButton.click();
  const archive = await archiveDownload;
  const archivePath = testInfo.outputPath("project.zip");
  await archive.saveAs(archivePath);
  await page.getByRole("button", { name: "Close panel", exact: true }).click();
  await page
    .getByRole("button", { name: "CleanTake project shelf", exact: true })
    .click();
  await page
    .getByLabel("Import project archive", { exact: true })
    .setInputFiles(archivePath);
  await expect(
    page.getByRole("heading", { name: "Review the performance", exact: true }),
  ).toBeVisible({ timeout: 60_000 });
  expect(errors).toEqual([]);
});

test("uncertain source clocks require manual alignment, and primary changes explain their effect", async ({
  page,
  request,
  projectName,
}) => {
  const name = projectName("Uncertain clock test");
  await create(page, name);
  await importRecordings(page, [
    join(fixtures, "Headset-injected-dropout.wav"),
    join(fixtures, "Unrelated-noise.wav"),
  ]);
  await page
    .getByRole("button", { name: "Align & analyze", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Analyze again", exact: true }),
  ).toBeEnabled({ timeout: 60_000 });
  await expect(
    page.getByRole("button", { name: "Source", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("Own clock · alignment needed", { exact: true }),
  ).toBeVisible();
  const saved = await projectByName(request, name);
  await page
    .getByRole("button", {
      name: `Settings for ${saved.sources[1].name}`,
      exact: true,
    })
    .click();
  await page
    .getByRole("button", { name: "Set manual alignment", exact: true })
    .click();
  await page.getByLabel("Offset (seconds)", { exact: true }).fill("0.025");
  await page
    .getByRole("button", { name: "Apply manual alignment", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Source", exact: true }),
  ).toBeEnabled();
  expect((await projectByName(request, name)).sources[1].alignment.status).toBe(
    "manual",
  );
  await page
    .getByRole("button", { name: "Manual repair", exact: true })
    .click();
  await page.getByLabel("Start (seconds)", { exact: true }).fill("2");
  await page.getByLabel("End (seconds)", { exact: true }).fill("2.25");
  await page
    .getByRole("button", { name: "Create proposed repair", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: /Manual passage/ }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Keep original", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: `Settings for ${saved.sources[1].name}`,
      exact: true,
    })
    .click();
  await page
    .getByRole("button", { name: "Use as primary", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "clears repair decisions and resets every alignment",
  );
  await page
    .getByRole("button", { name: "Keep current project", exact: true })
    .click();
  expect((await projectByName(request, name)).primary_source_id).toBe(
    saved.primary_source_id,
  );
});

test("failed imports and revision conflicts preserve recoverable project state", async ({
  page,
  request,
  projectName,
}) => {
  const name = projectName("Recovery behavior");
  await create(page, name);
  await page
    .getByLabel("Import recordings", { exact: true })
    .setInputFiles(join(fixtures, "invalid.wav"));
  await expect(page.getByRole("alert")).toBeVisible({ timeout: 60_000 });
  await expect(
    page.getByRole("button", { name: "Choose recordings", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Dismiss error", exact: true })
    .click();
  await page
    .getByLabel("Import recordings", { exact: true })
    .setInputFiles(join(fixtures, "Headset-injected-dropout.wav"));
  await expect(
    page.getByRole("button", { name: "Add backup", exact: true }),
  ).toBeVisible({ timeout: 60_000 });
  const saved = await projectByName(request, name);
  await page
    .getByRole("button", {
      name: `Settings for ${saved.sources[0].name}`,
      exact: true,
    })
    .click();
  const response = await request.patch(`/api/projects/${saved.id}`, {
    headers,
    data: {
      name: `${name} changed elsewhere`,
      expected_revision: saved.revision,
    },
  });
  expect(response.ok()).toBeTruthy();
  await page
    .getByLabel("Recording name", { exact: true })
    .fill("Old revision edit");
  await page.getByRole("button", { name: "Save labels", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "latest saved project has been loaded",
  );
  const latest = await projectByName(request, `${name} changed elsewhere`);
  expect(latest.sources[0].name).not.toBe("Old revision edit");
});

test("manual repair exports real replacement samples with source maps and reopens its archive", async ({
  page,
  request,
  projectName,
}, testInfo) => {
  const name = projectName("Manual AMI repair · injected damage");
  await create(page, name);
  await importRecordings(page, [
    join(fixtures, "Headset-injected-dropout.wav"),
    lapel,
  ]);
  await page
    .getByRole("button", { name: "Align & analyze", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Analyze again", exact: true }),
  ).toBeEnabled({ timeout: 60_000 });
  await page
    .getByRole("button", { name: "Manual repair", exact: true })
    .click();
  await page.getByLabel("Start (seconds)", { exact: true }).fill("17");
  await page.getByLabel("End (seconds)", { exact: true }).fill("17.5");
  await page.getByLabel("Gain (dB)", { exact: true }).fill("12");
  await page
    .getByRole("button", { name: "Create proposed repair", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: /Manual passage/ }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Accept repair", exact: true })
    .click();
  await expect
    .poll(async () =>
      (await projectByName(request, name)).repairs.some(
        (item: { status: string }) => item.status === "accepted",
      ),
    )
    .toBeTruthy();
  await page.getByRole("button", { name: "Repair", exact: true }).click();
  await page
    .getByRole("heading", { name: "Review the performance", exact: true })
    .click();
  await page.keyboard.press("Space");
  await expect(
    page.getByRole("button", { name: "Pause playback", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Space");
  await expect(
    page.getByRole("button", { name: "Play audio", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page
    .getByRole("button", { name: "Prepare export", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /Ready · revision/ }),
  ).toBeVisible({ timeout: 60_000 });
  const wavButton = page
    .getByRole("button")
    .filter({ hasText: /^dialogue\.wav/ });
  await expect(wavButton).toBeVisible();
  const downloading = page.waitForEvent("download");
  await wavButton.click();
  const audioPath = testInfo.outputPath("manual-repaired.wav");
  await (await downloading).saveAs(audioPath);
  execFileSync("uv", [
    "run",
    "python",
    "-c",
    "import soundfile as s,numpy as n,sys; a,r=s.read(sys.argv[1]); assert r==48000; assert len(a)==20*r; assert n.sqrt(n.mean(a[int(17.1*r):int(17.4*r)]**2))>.001",
    audioPath,
  ]);
  await expect(
    page.getByRole("button").filter({ hasText: /^source-map\.json/ }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Prepare archive", exact: true })
    .click();
  const archiveButton = page.getByRole("button").filter({ hasText: /\.zip/ });
  await expect(archiveButton).toBeVisible({ timeout: 60_000 });
  const download = page.waitForEvent("download");
  await archiveButton.click();
  const archivePath = testInfo.outputPath("manual-project.zip");
  await (await download).saveAs(archivePath);
  const saved = await projectByName(request, name);
  await page.getByRole("button", { name: "Close panel", exact: true }).click();
  await page
    .getByRole("button", { name: "CleanTake project shelf", exact: true })
    .click();
  await page
    .getByLabel("Import project archive", { exact: true })
    .setInputFiles(archivePath);
  await expect(
    page.getByRole("heading", { name: "Review the performance", exact: true }),
  ).toBeVisible({ timeout: 60_000 });
  const shelf = await (await request.get("/api/projects", { headers })).json();
  expect(
    shelf.projects.filter(
      (item: { id: string; name: string }) =>
        item.id !== saved.id && item.name.includes(name),
    ),
  ).toHaveLength(1);
});

test("selecting another passage during source playback uses that passage’s donor", async ({
  page,
  request,
  projectName,
}) => {
  const name = projectName("Source identity comparison");
  await create(page, name);
  await importRecordings(page, [
    join(fixtures, "Headset-injected-dropout.wav"),
    lapel,
    join(fixtures, "Lapel-identity-probe.wav"),
  ]);
  let item = await projectByName(request, name);
  for (const source of item.sources.slice(1)) {
    const response = await request.patch(
      `/api/projects/${item.id}/sources/${source.id}`,
      {
        headers,
        data: {
          alignment: { offset_seconds: 0, drift_ppm: 0, polarity: 1 },
          expected_revision: item.revision,
        },
      },
    );
    expect(response.ok()).toBeTruthy();
    item = await response.json();
  }
  for (const [index, source] of item.sources.slice(1).entries()) {
    const response = await request.post(`/api/projects/${item.id}/repairs`, {
      headers,
      data: {
        source_id: source.id,
        start_frame: (2 + index * 3) * 48000,
        end_frame: (2.5 + index * 3) * 48000,
        kind: "manual",
        expected_revision: item.revision,
      },
    });
    expect(response.ok()).toBeTruthy();
    item = await response.json();
  }
  await page
    .getByRole("button", { name: "CleanTake project shelf", exact: true })
    .click();
  await page.getByRole("button", { name: new RegExp(name) }).click();
  const rows = page.getByRole("button", { name: /Manual passage/ });
  await rows.first().click();
  await page
    .getByRole("button", { name: "Listen to source in context", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Pause playback", exact: true }),
  ).toBeVisible();
  const nextAudio = page.waitForRequest(
    (request) =>
      request.url().includes("/audio?") &&
      request.url().includes("mode=source"),
  );
  await rows.last().click();
  const url = new URL((await nextAudio).url());
  expect(url.searchParams.get("source_id")).toBe(item.sources[2].id);
  await expect(page.getByLabel("Audition source", { exact: true })).toHaveValue(
    item.sources[2].id,
  );
});
