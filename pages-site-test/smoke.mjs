// Drives headless Chromium against the assembled site: drops a folder holding a SWF plus a sibling file
// (with different letter case), runs it, and checks a relative LoadVars.load reached the sibling. Usage: node smoke.mjs <base-url> <dir>
import { chromium } from "playwright";

const [, , base, dir] = process.argv;
const browser = await chromium.launch({
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl"],
});
let failed = false;
for (const engine of ["rajit", "stock"]) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  try {
    await page.goto(`${base}/?engine=${engine}`);
    await page.waitForFunction(() => window.__vfsReady === true, null, { timeout: 30000 });
    await page.setInputFiles("#folderInput", `${dir}/gamefolder`);
    await page.waitForFunction(() => document.querySelectorAll("#files div").length >= 2, null, { timeout: 15000 });
    await page.waitForFunction(() => window.RufflePlayer && window.RufflePlayer.newest, null, { timeout: 60000 });
    await page.click("#run");
    await page.waitForFunction(
      () => /200\s+GET\s+gamefolder\/data\.txt\s*$/im.test(document.getElementById("log").textContent),
      null,
      { timeout: 60000 },
    );
    const log = await page.textContent("#log");
    console.log(`[${engine}] OK\n${log.trim().split("\n").map((l) => "    " + l).join("\n")}`);
  } catch (e) {
    failed = true;
    console.log(`[${engine}] FAILED: ${e.message}`);
    console.log("    page errors:", errors.join(" | ") || "none");
    console.log("    log panel:", (await page.textContent("#log").catch(() => "?")).trim());
    console.log("    hint:", (await page.textContent("#hint").catch(() => "")) || "");
  }
  await page.close();
}
await browser.close();
process.exit(failed ? 1 : 0);
