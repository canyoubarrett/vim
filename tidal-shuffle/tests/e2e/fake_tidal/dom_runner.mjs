// Runs the CDP page scripts against a static page in jsdom (for tests/test_cdp_dom.py).
// stdin: {html, path, setup, steps: [{js, wait}]}; stdout: {results, clicks}
import { JSDOM } from "jsdom";

const input = JSON.parse(await new Promise((resolve) => {
  let d = "";
  process.stdin.on("data", (c) => (d += c));
  process.stdin.on("end", () => resolve(d));
}));

const dom = new JSDOM(input.html, { url: "https://desktop.tidal.com" + (input.path || "/"), runScripts: "outside-only" });
const { window } = dom;
const clicks = [];
for (const type of ["click", "dblclick"]) {
  window.document.addEventListener(type, (e) => {
    const el = e.target.closest ? e.target.closest("[data-mark]") : null;
    clicks.push(type + ":" + (el ? el.getAttribute("data-mark") : e.target.tagName));
  }, true);
}
window.__dispatched = [];
if (input.setup) window.eval(input.setup);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
for (const step of input.steps) {
  if (step.wait) await sleep(step.wait);
  try {
    results.push(await window.eval(step.js));
  } catch (e) {
    results.push({ error: String(e) });
  }
}
process.stdout.write(JSON.stringify({ results, clicks, dispatched: window.__dispatched, path: window.location.pathname }));
