import { firefox } from "@playwright/test";

// Exercise a real user gesture and audio clock, including on headless runners.
const browser = await firefox.launch();
try {
  const page = await browser.newPage();
  await page.setContent('<button type="button">Start audio</button>');
  await page.evaluate(() => {
    window.audioProbe = { resumed: false, error: null };
    document.querySelector("button").onclick = () => {
      const context = new AudioContext();
      window.probeContext = context;
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      gain.gain.value = 0;
      oscillator.connect(gain).connect(context.destination);
      oscillator.start();
      context.resume().then(
        () => { window.audioProbe.resumed = true; },
        error => { window.audioProbe.error = String(error); },
      );
    };
  });
  await page.getByRole("button", { name: "Start audio" }).click();
  try {
    await page.waitForFunction(
      () => window.audioProbe.resumed && window.probeContext.currentTime > 0.1,
      undefined,
      { timeout: 5000 },
    );
  } catch {
    // The first CI probe records an unavailable backend without masking it.
  }
  const result = await page.evaluate(() => ({
    ...window.audioProbe,
    state: window.probeContext?.state,
    currentTime: window.probeContext?.currentTime,
  }));
  console.log(JSON.stringify(result));
  if (process.argv.includes("--require-running") &&
      !(result.resumed && result.state === "running" && result.currentTime > 0.1)) {
    process.exitCode = 1;
  }
} finally {
  await browser.close();
}
