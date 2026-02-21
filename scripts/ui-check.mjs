// UI gate: axe, overflow, CSP console errors, and screenshots for the local web UI.
//
// Not part of `pytest` or CI: it needs a Chromium binary and two npm packages,
// which the $0 local-only constraint keeps out of the repository. Install them
// once, next to the checkout:
//
//   mkdir -p ../.ui-tools && cd ../.ui-tools
//   npm install playwright-core axe-core
//
// Then, from the repository root:
//
//   node scripts/ui-check.mjs
//
// Environment:
//   UI_TOOLS   directory holding node_modules/playwright-core and axe-core
//              (default: ../.ui-tools)
//   CHROME     Chromium-family executable (default: the system Chrome path)
//   SHOTS      screenshot directory (default: .ui-tmp/shots)
//
// Exit code is 1 if axe reports a violation at serious or critical impact, if
// any page scrolls horizontally, or if the page logs a CSP violation.

import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const tools = resolve(process.env.UI_TOOLS ?? join(root, "..", ".ui-tools"));
const require = createRequire(join(tools, "package.json"));
const { chromium } = require("playwright-core");
const axePath = require.resolve("axe-core/axe.min.js");

const CHROME =
  process.env.CHROME ??
  (process.platform === "win32"
    ? "C:/Program Files/Google/Chrome/Application/chrome.exe"
    : "/usr/bin/google-chrome");
const shots = resolve(process.env.SHOTS ?? join(root, ".ui-tmp", "shots"));
const widths = [320, 390, 768, 1024, 1440];
const failures = [];
const checked = [];

const dataDir = mkdtempSync(join(tmpdir(), "homefile-ui-"));
const PYTHON = process.env.PYTHON ?? "python";
const port = Number(process.env.PORT ?? 8795);

function run(args, options = {}) {
  return new Promise((done, fail) => {
    const child = spawn(PYTHON, args, {
      cwd: root,
      stdio: ["ignore", "pipe", "pipe"],
      ...options,
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (chunk) => (out += chunk));
    child.stderr.on("data", (chunk) => (err += chunk));
    child.on("error", fail);
    child.on("exit", (code) => done({ code, out, err }));
  });
}

async function waitForServer(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // not listening yet
    }
    await new Promise((done) => setTimeout(done, 200));
  }
  throw new Error(`server did not answer on ${url} within ${timeoutMs} ms`);
}

const homefile = (...args) => run(["-m", "homefile", "--data-dir", dataDir, ...args]);

// `samples` only writes the synthetic PDFs; the library is filled through the
// same validated import path a user takes.
const sampleDir = join(dataDir, "samples");
const written = await homefile("samples", sampleDir);
if (written.code !== 0) {
  console.error(written.err || written.out);
  process.exit(1);
}
for (const [name] of Object.entries(JSON.parse(written.out))) {
  const imported = await homefile("import", join(sampleDir, name), "--date-order", "dmy");
  if (imported.code !== 0) {
    console.error(imported.err || imported.out);
    process.exit(1);
  }
}
// A one-page fixture cannot exercise page tabs, so the gate writes the
// two-page fixture and imports it through the same validated path.
const multiPath = join(dataDir, "multi-page.pdf");
const writtenMulti = await run([
  "-c",
  "import pathlib,sys; from homefile.fixtures import multi_page_pdf; "
    + "pathlib.Path(sys.argv[1]).write_bytes(multi_page_pdf())",
  multiPath,
]);
if (writtenMulti.code !== 0) {
  console.error(writtenMulti.err || writtenMulti.out);
  process.exit(1);
}
const importedMulti = await homefile("import", multiPath, "--date-order", "dmy");
if (importedMulti.code !== 0) {
  console.error(importedMulti.err || importedMulti.out);
  process.exit(1);
}

const listed = JSON.parse((await homefile("list")).out);
const firstDoc = listed[0]?.id;
const multiDoc = listed.find((item) => item.filename === "multi-page.pdf")?.id;
if (!firstDoc || !multiDoc) {
  console.error("fixtures were not imported; cannot exercise the detail page");
  process.exit(1);
}

mkdirSync(shots, { recursive: true });
const server = spawn(
  PYTHON,
  ["-m", "homefile", "--data-dir", dataDir, "serve", "--port", String(port)],
  { cwd: root, stdio: ["ignore", "pipe", "pipe"] },
);
server.stderr.on("data", (chunk) => process.stderr.write(chunk));

const pages = [
  ["home", "/"],
  ["documents", "/documents"],
  ["detail", `/documents/${firstDoc}`],
  ["reminders", "/reminders"],
  ["settings", "/settings"],
];

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
try {
  await waitForServer(`http://127.0.0.1:${port}/healthz`);
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  // The pages ship `script-src 'self'`, so an injected <script> tag is blocked.
  // An init script is installed through the protocol before any page script
  // runs, which is the only way to load axe without weakening the policy the
  // gate is meant to check.
  await context.addInitScript({ path: axePath });
  const page = await context.newPage();
  const consoleProblems = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleProblems.push(message.text());
  });

  for (const [name, path] of pages) {
    for (const width of widths) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`http://127.0.0.1:${port}${path}`, { waitUntil: "load" });
      // Web fonts settle after `load`; measuring before that reports overflow
      // from the fallback face, which the user never sees.
      await page.evaluate(() => document.fonts.ready);
      const result = await page.evaluate(async () =>
        await window.axe.run(document, { resultTypes: ["violations"] }),
      );
      const blocking = result.violations.filter((v) =>
        ["serious", "critical"].includes(v.impact ?? ""),
      );
      if (blocking.length) {
        for (const violation of blocking) {
          failures.push(
            `${name}@${width}: axe ${violation.impact} ${violation.id} (${violation.nodes.length} node(s))`,
          );
        }
      }
      const metrics = await page.evaluate(() => {
        const root = document.documentElement;
        return { overflow: root.scrollWidth - root.clientWidth, client: root.clientWidth, scroll: root.scrollWidth };
      });
      if (metrics.overflow > 0) {
        const widest = await page.evaluate(() => {
          const cw = document.documentElement.clientWidth;
          const rows = [];
          for (const el of document.querySelectorAll("body *")) {
            const box = el.getBoundingClientRect();
            if (box.right > cw + 0.5) {
              rows.push({
                tag: el.tagName.toLowerCase(),
                cls: String(el.className).slice(0, 40),
                right: Math.round(box.right),
                text: (el.textContent ?? "").trim().slice(0, 30),
              });
            }
          }
          return rows.slice(0, 6);
        });
        failures.push(
          `${name}@${width}: scrolls horizontally by ${metrics.overflow}px ` +
            `(client ${metrics.client}, scroll ${metrics.scroll}) ` +
            JSON.stringify(widest),
        );
      }
      if (width === 320 || width === 390 || width === 1440) {
        await page.screenshot({ path: join(shots, `${name}-${width}.png`), fullPage: true });
      }
    }
  }

  for (const problem of consoleProblems) {
    // CSP violations surface as console errors; an empty page is not proof.
    if (/content security policy|refused to/i.test(problem)) {
      failures.push(`console: ${problem}`);
    }
  }

  // ---------------------------------------------------------------- flows
  // Each flow asserts an observable end state, not that a request was sent.
  const check = (name, condition, detail) => {
    checked.push(name);
    if (!condition) failures.push(`flow ${name}: ${detail}`);
  };
  const base = `http://127.0.0.1:${port}`;
  await page.setViewportSize({ width: 1440, height: 900 });
  page.on("dialog", (dialog) => dialog.accept());

  // Search: a query that matches one fixture must narrow the result count.
  await page.goto(`${base}/documents`, { waitUntil: "load" });
  const allCount = await page.locator("tbody tr").count();
  await page.fill('input[name="q"]', "STREAMBOX");
  await page.press('input[name="q"]', "Enter");
  await page.waitForLoadState("load");
  const hitCount = await page.locator("tbody tr").count();
  check("search", hitCount > 0 && hitCount < allCount, `${hitCount} rows of ${allCount}`);
  // The snippet is escaped text rather than HTML highlighting, so the match is
  // asserted on the rendered text of the result table.
  const snippet = await page.locator("tbody tr td:last-child").first().innerText();
  check("search-snippet", /streambox/i.test(snippet), `snippet was "${snippet.slice(0, 60)}"`);

  // Field selection: activating a field row retargets the citation pane and
  // announces it, without a page load.
  await page.goto(`${base}/documents/${firstDoc}`, { waitUntil: "load" });
  const rows = page.locator("a.field-row");
  if ((await rows.count()) >= 2) {
    const target = rows.nth(1);
    const fieldName = (await target.getAttribute("data-name")) ?? "";
    await target.click();
    const citation = await page.locator("[data-citation-field]").innerText();
    check("field-selection", citation.length > 0, "citation pane lost its field name");
    const announced = await page.locator("#citation-live").innerText();
    check(
      "field-announcement",
      announced.includes("page"),
      `live region did not announce the citation (${announced})`,
    );
    check(
      "field-aria-current",
      (await target.getAttribute("aria-current")) === "true",
      `selected row is not aria-current (${fieldName})`,
    );
  } else {
    failures.push("flow field-selection: fixture document has fewer than two fields");
  }

  // Correction: the saved value must come back with the original retained.
  await page.fill('[data-citation-form] input[name="value"]', "NORTHWIND HARDWARE LIMITED");
  await page.fill('[data-citation-form] input[name="reason"]', "gate: certificate wording");
  await page.click('[data-citation-form] button[type="submit"]');
  await page.waitForLoadState("load");
  const flash = await page.locator('[role="status"]').first().innerText().catch(() => "");
  check("correction", /correction saved/i.test(flash), `flash was "${flash}"`);
  const timeline = await page.locator("ol.timeline").innerText();
  check(
    "correction-history",
    /corrected|original|→/i.test(timeline),
    `history did not record the correction (${timeline.slice(0, 80)})`,
  );

  // Reminder confirmation: the suggested row must leave the suggested list.
  await page.goto(`${base}/reminders?status=suggested`, { waitUntil: "load" });
  const before = await page.locator("tbody tr").count();
  if (before > 0) {
    await page.locator('button:has-text("Confirm reminder")').first().click();
    await page.waitForLoadState("load");
    await page.goto(`${base}/reminders?status=suggested`, { waitUntil: "load" });
    const after = await page.locator("tbody tr").count();
    check("reminder-confirm", after === before - 1, `${before} -> ${after} suggested rows`);
    await page.goto(`${base}/reminders?status=confirmed`, { waitUntil: "load" });
    check(
      "reminder-visible",
      (await page.locator("tbody tr").count()) > 0,
      "confirmed reminder is not listed under Confirmed",
    );
  } else {
    failures.push("flow reminder-confirm: no suggested reminder in the fixture library");
  }

  // -------------------------------------------------------------- keyboard
  await page.goto(`${base}/`, { waitUntil: "load" });
  await page.keyboard.press("Tab");
  const firstStop = await page.evaluate(() => {
    const el = document.activeElement;
    const style = getComputedStyle(el);
    return {
      text: (el?.textContent ?? "").trim().slice(0, 40),
      tag: el?.tagName.toLowerCase() ?? "",
      outline: `${style.outlineStyle} ${style.outlineWidth} ${style.boxShadow}`,
    };
  });
  check(
    "skip-link-first",
    /skip/i.test(firstStop.text),
    `first tab stop is ${firstStop.tag} "${firstStop.text}"`,
  );
  check(
    "focus-visible",
    !/none 0px/.test(firstStop.outline) || firstStop.outline.includes("rgb"),
    `first focus stop has no visible ring (${firstStop.outline})`,
  );

  // `/` is the documented shortcut to the search field.
  await page.goto(`${base}/documents`, { waitUntil: "load" });
  await page.keyboard.press("/");
  check(
    "slash-shortcut",
    (await page.evaluate(() => document.activeElement?.getAttribute("name"))) === "q",
    "pressing / did not focus the search field",
  );

  // Page tabs: arrow keys move selection, and exactly one panel stays visible.
  await page.goto(`${base}/documents/${multiDoc}`, { waitUntil: "load" });
  const tabs = page.locator('[role="tab"]');
  if ((await tabs.count()) >= 2) {
    await tabs.first().focus();
    await page.keyboard.press("ArrowRight");
    const state = await page.evaluate(() => {
      const list = [...document.querySelectorAll('[role="tab"]')];
      return {
        focused: list.findIndex((tab) => tab === document.activeElement),
        selected: list.filter((tab) => tab.getAttribute("aria-selected") === "true").length,
        visible: [...document.querySelectorAll('[role="tabpanel"]')].filter(
          (panel) => panel.offsetParent !== null,
        ).length,
      };
    });
    check("tab-arrow", state.focused === 1, `ArrowRight left focus on tab ${state.focused}`);
    check("tab-single-selection", state.selected === 1, `${state.selected} tabs selected`);
    check("tab-panel-visible", state.visible === 1, `${state.visible} panels visible`);
  } else {
    failures.push("keyboard tab-arrow: the two-page fixture rendered no page tabs");
  }

  await context.close();

} finally {
  await browser.close();
  server.kill();
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log(
  `ui gate clean: ${pages.length} pages x ${widths.length} widths, ` +
    `${checked.length} flow/keyboard checks, screenshots in ${shots}`,
);
console.log(`  checks: ${checked.join(", ")}`);
