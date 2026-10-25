"use strict";
// Runs web/app.js against the REAL server using a tiny DOM stub.
// usage: node frontend_smoke.js http://127.0.0.1:PORT
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const BASE = process.argv[2];
const webDir = path.join(__dirname, "..", "web");

class Node {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attrs = {}; this.style = {};
    this.listeners = {}; this.textContent = ""; this.className = ""; this.dataset = {}; this.parent = null;
  }
  append(...kids) { for (const k of kids) { k.parent = this; this.children.push(k); } }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "data-lang") this.dataset.lang = v; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; }
  insertBefore(node, ref) {
    node.remove();
    const i = ref ? this.children.indexOf(ref) : this.children.length;
    this.children.splice(i < 0 ? this.children.length : i, 0, node);
    node.parent = this;
  }
  click() { (this.listeners.click || []).forEach((f) => f()); }
}

const walk = (n, fn) => { fn(n); n.children.forEach((c) => walk(c, fn)); };
const find = (root, pred) => { let hit = null; walk(root, (n) => { if (!hit && pred(n)) hit = n; }); return hit; };
const allText = (root) => { const out = []; walk(root, (n) => n.textContent && out.push(n.textContent)); return out.join(" | "); };

// Build the stub document from the real index.html ids.
const html = fs.readFileSync(path.join(webDir, "index.html"), "utf8");
const byId = {};
for (const m of html.matchAll(/id="([^"]+)"/g)) byId[m[1]] = new Node("el");
const langButtons = ["en", "ar"].map((l) => { const b = new Node("button"); b.dataset.lang = l; return b; });
const document = {
  documentElement: new Node("html"), title: "",
  getElementById: (id) => { if (!byId[id]) throw new Error("missing #" + id); return byId[id]; },
  createElement: (tag) => new Node(tag),
  querySelectorAll: (sel) => (sel === ".lang button" ? langButtons : []),
};
const store = {};
const sandbox = {
  document, console, Object, Set, Map, Array, String, JSON, Error, Promise, setTimeout,
  localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; } },
  navigator: { language: "en-US" },
  requestAnimationFrame: (f) => f(),
  fetch: (u, o) => fetch(BASE + u, o),
};
process.on("unhandledRejection", (e) => { console.error("UNHANDLED", e); process.exit(2); });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(pred, what) {
  for (let i = 0; i < 200; i++) { if (pred()) return; await sleep(15); }
  throw new Error("timed out waiting for: " + what);
}
const dialogue = () => byId["dialogue"];
const questionText = () => { const q = find(dialogue(), (n) => n.className === "question"); return q && q.textContent; };
const button = (label) => find(dialogue(), (n) => n.tag === "button" && n.textContent === label);

(async () => {
  vm.runInNewContext(fs.readFileSync(path.join(webDir, "app.js"), "utf8"), sandbox);

  // 1. first render: domains + first question + chrome texts
  await until(() => questionText(), "first question");
  assert.strictEqual(questionText(), "Is the car failing to start?");
  assert.strictEqual(byId["domain-list"].children.length, 3);
  assert.strictEqual(document.documentElement.dir, "ltr");
  assert.ok(byId["disclaimer"].textContent.length > 0);

  // 2. answer until the diagnosis appears
  const yes = ["failing to start", "crank slowly", "dim or go out"];
  let guard = 0;
  while (!find(dialogue(), (n) => n.textContent === "Diagnosis")) {
    assert.ok(guard++ < 30, "too many questions");
    const q = questionText();
    const before = q;
    button(yes.some((k) => q.includes(k)) ? "Yes" : "No").click();
    await until(() => questionText() !== before || find(dialogue(), (n) => n.textContent === "Diagnosis"), "next view");
  }
  assert.ok(allText(dialogue()).includes("Weak or dead battery"));
  assert.ok(allText(dialogue()).includes("Jump-start"));
  const gauge = byId["gauge-list"];
  assert.ok(gauge.children.length >= 1);
  const fill = find(gauge.children[0], (n) => n.style.width);
  assert.match(fill.style.width, /^9\d%$/);          // the meter moved to ~96%

  // 3. switching language re-renders in Arabic with RTL
  langButtons[1].click();
  await until(() => document.documentElement.dir === "rtl" && /[؀-ۿ]/.test(allText(dialogue())), "arabic");
  assert.ok(allText(dialogue()).includes("بطارية ضعيفة أو فاضية"));
  assert.strictEqual(store.lang, "ar");

  // 4. Back, then Start over (Arabic labels)
  button("رجوع").click();
  await until(() => questionText(), "question after back");
  button("ابدأ من الأول").click();
  await until(() => questionText() === "هل العربية مش بتشتغل؟", "restarted");
  assert.strictEqual(gauge.children.length, 0);

  // 5. another domain
  byId["domain-list"].children[2].click();
  await until(() => questionText() && questionText().includes("الإنترنت"), "network domain");

  console.log("frontend smoke test OK");
  process.exit(0);
})().catch((e) => { console.error("FAILED:", e.message); process.exit(1); });
