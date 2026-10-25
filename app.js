"use strict";

// All server text is inserted with textContent, never innerHTML.
const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "style") Object.assign(node.style, v); // CSSOM is allowed by the CSP, style="" is not
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  node.append(...children);
  return node;
};

const state = { meta: null, lang: "en", domain: null, answers: [], view: null };
const ui = () => state.meta.ui[state.lang];
const idx = () => (state.lang === "ar" ? 1 : 0);

function loadLang() {
  try {
    const saved = localStorage.getItem("lang");
    if (saved === "en" || saved === "ar") return saved;
  } catch (_) { /* storage may be unavailable */ }
  return (navigator.language || "").startsWith("ar") ? "ar" : "en";
}

async function post(body) {
  const res = await fetch("/api/step", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json()).error || res.statusText);
  return res.json();
}

async function refresh() {
  state.view = await post({ domain: state.domain, answers: state.answers, lang: state.lang });
  render();
}

function setLang(lang) {
  state.lang = lang;
  try { localStorage.setItem("lang", lang); } catch (_) { /* ignore */ }
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll(".lang button").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
  if (state.domain) refresh(); else renderChrome();
}

function selectDomain(key) {
  state.domain = key;
  state.answers = [];
  gaugeNodes.clear();
  $("gauge-list").replaceChildren();
  refresh();
}

function answer(choice) {
  state.answers.push([state.view.question.fact, choice]);
  refresh();
}

function renderChrome() {
  const t = ui();
  document.title = t.app_title;
  $("app-title").textContent = t.app_title;
  $("pick-title").textContent = t.pick_domain;
  $("gauge-title").textContent = t.thinking;
  $("disclaimer").textContent = t.disclaimer;

  const list = $("domain-list");
  list.replaceChildren(...state.meta.domains.map((d) =>
    el("button", {
      type: "button", role: "radio", text: d.title[idx()],
      "aria-checked": String(d.key === state.domain),
      onclick: () => selectDomain(d.key),
    })));
  const current = state.meta.domains.find((d) => d.key === state.domain);
  $("domain-intro").textContent = current ? current.intro[idx()] : t.pick_domain;
  if (!current) {
    $("dialogue").replaceChildren();
    $("gauge-list").replaceChildren();
    $("gauge-empty").textContent = "";
  }
}

const gaugeNodes = new Map(); // fact -> {li, name, pct, fill}; reused so the bars animate

function renderGauge(live) {
  const wanted = new Set(live.map((d) => d.fact));
  for (const [fact, node] of gaugeNodes) {
    if (!wanted.has(fact)) { node.li.remove(); gaugeNodes.delete(fact); }
  }
  const list = $("gauge-list");
  live.forEach((d, i) => {
    let node = gaugeNodes.get(d.fact);
    if (!node) {
      const name = el("span");
      const pct = el("b");
      const fill = el("span", { style: { width: "0%" } });
      const li = el("li", {},
        el("div", { class: "gauge-row" }, name, pct),
        el("div", { class: "bar", role: "presentation" }, fill));
      node = { li, name, pct, fill };
      gaugeNodes.set(d.fact, node);
    }
    node.name.textContent = d.title;
    node.pct.textContent = d.cf + "%";
    if (list.children[i] !== node.li) list.insertBefore(node.li, list.children[i] || null);
    requestAnimationFrame(() => { node.fill.style.width = d.cf + "%"; });
  });
  $("gauge-empty").textContent = live.length ? "" : "-";
}

function renderQuestion(view) {
  const t = ui();
  const btn = (choice, cls) => el("button", { type: "button", class: cls, text: t[choice], onclick: () => answer(choice) });
  return [
    el("p", { class: "meta", text: t.question.replace("{n}", view.answered + 1) }),
    el("p", { class: "question", text: view.question.text }),
    el("div", { class: "answers" }, btn("yes", "primary"), btn("probably", ""), btn("no", ""), btn("unknown", "quiet")),
    tools(),
  ];
}

function tools() {
  const t = ui();
  return el("div", { class: "tools" },
    el("button", {
      type: "button", class: "link", text: t.back, ...(state.answers.length ? {} : { disabled: "" }),
      onclick: () => { state.answers.pop(); refresh(); },
    }),
    el("button", { type: "button", class: "link", text: t.restart, onclick: () => { state.answers = []; refresh(); } }));
}

function renderResults(view) {
  const t = ui();
  const cards = view.results.map((r) =>
    el("article", { class: "result" + (r.urgent ? " urgent" : "") },
      el("h3", { text: (r.urgent ? t.important + ": " : "") + r.title }),
      el("p", { class: "conf", text: `${t.confidence}: ${r.cf}%` }),
      el("strong", { text: t.what_to_do }),
      el("ul", { class: "steps" }, ...r.steps.map((s) => el("li", { text: s }))),
      el("details", {},
        el("summary", { text: t.why }),
        el("ul", { class: "why" }, ...r.why.map((w) =>
          el("li", { style: { paddingInlineStart: w.depth * 16 + "px" }, text: w.text }))))));
  return [
    el("h2", { text: t.results }),
    cards.length ? el("div", { class: "results" }, ...cards) : el("p", { text: t.no_result }),
    tools(),
  ];
}

function render() {
  renderChrome();
  const view = state.view;
  $("dialogue").replaceChildren(...(view.done ? renderResults(view) : renderQuestion(view)));
  renderGauge(view.live);
}

async function init() {
  state.meta = await (await fetch("/api/meta")).json();
  document.querySelectorAll(".lang button").forEach((b) =>
    b.addEventListener("click", () => setLang(b.dataset.lang)));
  state.domain = state.meta.domains[0].key;
  setLang(loadLang());
}

init();
