import { expect } from "@playwright/test";
import { test } from "./test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, join } from "node:path";

const token = "cleantake-browser-test-session";
const headers = { "X-CleanTake-Token": token };

test("an actual delayed next audio window stops at the last heard frame", async ({
  page,
  request,
  projectName,
}) => {
  const name = projectName("Playback window continuity probe");
  const directory = mkdtempSync(join(tmpdir(), "cleantake-window-test-"));
  const path = join(directory, "Repeated-AMI-playback-fixture.wav");
  execFileSync("uv", [
    "run",
    "python",
    "-c",
    "import soundfile as s, numpy as n, sys; a,r=s.read(sys.argv[1]); s.write(sys.argv[2],n.tile(a,3),r)",
    resolve("../tests/engine/data/ES2004a_0324-0344_Headset-0.wav"),
    path,
  ]);
  try {
    const created = await request.post("/api/projects", {
      headers,
      data: { name },
    });
    const project = await created.json();
    const upload = await request.post(`/api/projects/${project.id}/sources`, {
      headers,
      multipart: {
        file: {
          name: "Repeated-AMI-playback-fixture.wav",
          mimeType: "audio/wav",
          buffer: readFileSync(path),
        },
      },
    });
    let job = await upload.json();
    await expect
      .poll(
        async () => {
          job = await (
            await request.get(`/api/jobs/${job.id}`, { headers })
          ).json();
          return job.status;
        },
        { timeout: 60_000 },
      )
      .toBe("completed");
    await page.goto(`/#token=${token}`);
    await page
      .getByRole("button", { name: new RegExp(name) })
      .click();
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let secondRequested = false;
    await page.route("**/api/projects/*/audio?*", async (route) => {
      if (
        new URL(route.request().url()).searchParams.get("start_frame") ===
        "960000"
      ) {
        const response = await route.fetch();
        secondRequested = true;
        await gate;
        await route.fulfill({ response }).catch(() => {});
      } else await route.continue();
    });
    try {
      await page
        .getByRole("button", { name: "Play audio", exact: true })
        .click();
      await expect
        .poll(() => secondRequested, { timeout: 20_000 })
        .toBeTruthy();
      await expect(
        page.getByRole("button", { name: "Play audio", exact: true }),
      ).toBeVisible({ timeout: 15_000 });
      await expect(page.getByLabel("Playhead time")).toHaveText("00:20.000");
      await expect(page.getByRole("alert")).toContainText("buffer");
    } finally {
      release();
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("a pending real project edit cannot restart audio from its older revision", async ({
  page,
  request,
  projectName,
}) => {
  const name = projectName("Revision playback probe");
  const created = await request.post("/api/projects", {
    headers,
    data: { name },
  });
  const project = await created.json();
  const path = resolve("../tests/engine/data/ES2004a_0324-0344_Headset-0.wav");
  const upload = await request.post(`/api/projects/${project.id}/sources`, {
    headers,
    multipart: {
      file: {
        name: "AMI-headset.wav",
        mimeType: "audio/wav",
        buffer: readFileSync(path),
      },
    },
  });
  let job = await upload.json();
  await expect
    .poll(async () => {
      job = await (
        await request.get(`/api/jobs/${job.id}`, { headers })
      ).json();
      return job.status;
    })
    .toBe("completed");
  await page.goto(`/#token=${token}`);
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await page.getByRole("button", { name: "Play audio", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Pause playback", exact: true }),
  ).toBeVisible();
  await page.getByText("Project settings", { exact: true }).click();
  await page
    .getByRole("textbox", { name: "Project name", exact: true })
    .fill(`${name} updated`);
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let editing = false;
  await page.route(`**/api/projects/${project.id}`, async (route) => {
    if (route.request().method() === "PATCH") {
      const response = await route.fetch();
      editing = true;
      await gate;
      await route.fulfill({ response }).catch(() => {});
    } else await route.continue();
  });
  try {
    await page.getByRole("button", { name: "Save name", exact: true }).click();
    await expect.poll(() => editing).toBeTruthy();
    await expect(
      page.getByRole("button", { name: "Play audio", exact: true }),
    ).toBeDisabled();
  } finally {
    release();
  }
  await expect(
    page.getByRole("button", {
      name: `${name} updated`,
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Play audio", exact: true }),
  ).toBeEnabled();
});
