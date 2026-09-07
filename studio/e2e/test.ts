import { test as base } from "@playwright/test";
import { randomUUID } from "node:crypto";

export const test = base.extend<{
  projectName: (label: string) => string;
}>({
  projectName: async ({}, use, testInfo) => {
    const suffix = `${testInfo.project.name}-${randomUUID().slice(0, 8)}`;
    await use((label) => `${label} · ${suffix}`);
  },
});
