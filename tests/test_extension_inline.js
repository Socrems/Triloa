"use strict";
// npm install --prefix cache/extension-dom-test --ignore-scripts linkedom@0.18.12
const { parseHTML } = require(process.env.TRILOA_DOM_MODULE || "../cache/extension-dom-test/node_modules/linkedom");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function page(html, enabled = true) {
  const { window, document } = parseHTML(`<html lang="en"><body>${html}</body></html>`);
  const callbacks = new Map();
  const intervals = new Map();
  let serial = 0;
  let change;
  const requests = [];
  const state = { model: "A", pending: null, fail: false };
  window.innerWidth = 1000;
  window.innerHeight = 800;
  window.HTMLElement.prototype.getBoundingClientRect = () => ({ width: 700, height: 30, top: 50, bottom: 80, left: 20, right: 720 });
  window.getComputedStyle = node => ({ display: node.style.display || "block", visibility: "visible", opacity: "1", fontFamily: "Arial", fontSize: "16px", fontWeight: "400", color: "black", textAlign: "left" });
  window.setTimeout = callback => { callbacks.set(++serial, callback); return serial; };
  window.clearTimeout = id => callbacks.delete(id);
  window.setInterval = callback => { intervals.set(++serial, callback); return serial; };
  window.clearInterval = id => intervals.delete(id);
  const key = "triloa:enabled:https://example.com";
  const chrome = {
    storage: {
      local: { get: async () => ({ [key]: enabled }) },
      onChanged: { addListener: callback => { change = callback; } }
    },
    runtime: {
      sendMessage: async message => {
        if (message.type === "triloa:model") return { ok: true, modelId: state.model };
        const texts = Array.from(message.texts);
        requests.push(texts);
        if (state.pending) return state.pending(texts);
        if (state.fail) return { ok: false, error: "fixture service failure" };
        return { ok: true, modelId: state.model, translations: texts.map(text => `中文${state.model}：${text}`) };
      }
    }
  };
  const context = vm.createContext({ window, document, MutationObserver: window.MutationObserver, chrome, location: { origin: "https://example.com" }, console });
  for (const name of ["model_cache.js", "content.js"]) vm.runInContext(fs.readFileSync(path.join(__dirname, "../extension", name), "utf8"), context);
  return {
    document, requests, state,
    switch(value) { change({ [key]: { newValue: value } }, "local"); },
    poll() { for (const callback of intervals.values()) callback(); },
    async settle() {
      for (let count = 0; count < 30; count++) {
        await Promise.resolve();
        await Promise.resolve();
        if (!callbacks.size) { await Promise.resolve(); if (!callbacks.size) return; }
        const current = [...callbacks.values()];
        callbacks.clear();
        for (const callback of current) callback();
      }
      throw new Error("Refresh did not settle; injected DOM may cause a feedback loop.");
    }
  };
}

function translations(document) {
  return [...document.querySelectorAll('[data-triloa-owned="translation"]')].map(node => node.shadowRoot.querySelector("span").textContent);
}

async function run() {
  const html = '<h2 id="title">Introduction</h2><p id="p">This is an <a href="/link">English paragraph</a> to translate.</p><ul><li id="li">Parent item<ul><li id="child">Child item</li></ul></li><li><p>Another paragraph in a list.</p></li></ul><nav><p>Do not translate this navigation text.</p></nav><pre><p>Do not translate this code example.</p></pre>';
  const first = page(html);
  await first.settle();
  assert.equal(translations(first.document).length, 5);
  assert.equal(first.document.querySelector("#p").nextSibling.getAttribute("data-triloa-owned"), "translation");
  assert.equal(first.document.querySelector("#title").nextSibling.getAttribute("data-triloa-owned"), "translation");
  assert.equal(first.document.querySelector("#li > [data-triloa-owned]").nextSibling.tagName, "UL");
  assert.equal(first.document.querySelector("#p a").getAttribute("href"), "/link");
  assert.deepEqual(first.requests.flat().sort(), ["Introduction", "This is an English paragraph to translate.", "Parent item", "Child item", "Another paragraph in a list."].sort());
  assert.equal(first.requests.length, 1, "own DOM changes must not trigger more translation requests");
  first.switch(false);
  await first.settle();
  assert.equal(first.document.body.innerHTML, html);
  assert.equal(first.document.querySelectorAll("[data-triloa-owned]").length, 0);

  const duplicates = page('<p>The same English paragraph is here.</p><p>The same English paragraph is here.</p>');
  await duplicates.settle();
  assert.equal(duplicates.requests[0].length, 1);
  assert.equal(translations(duplicates.document).length, 2);
  duplicates.document.querySelector("p").textContent = "This original paragraph has now changed.";
  await duplicates.settle();
  assert.ok(translations(duplicates.document).includes("中文A：This original paragraph has now changed."));
  const added = duplicates.document.createElement("h3");
  added.textContent = "Installation";
  duplicates.document.body.append(added);
  await duplicates.settle();
  assert.ok(translations(duplicates.document).includes("中文A：Installation"));
  duplicates.state.model = "B";
  duplicates.poll();
  await duplicates.settle();
  assert.ok(translations(duplicates.document).every(text => text.startsWith("中文B")));
  duplicates.switch(false);

  const late = page('<p>This English paragraph has a delayed response.</p>');
  let resolve;
  late.state.pending = () => new Promise(done => { resolve = done; });
  await late.settle();
  late.state.model = "B";
  late.poll();
  await late.settle();
  late.state.pending = null;
  resolve({ ok: true, modelId: "A", translations: ["OLD MODEL RESULT"] });
  await late.settle();
  assert.deepEqual(translations(late.document), ["中文B：This English paragraph has a delayed response."]);
  late.switch(false);

  const stopped = page('<p>This English paragraph will be disabled.</p>');
  stopped.state.pending = () => new Promise(done => { resolve = done; });
  await stopped.settle();
  stopped.switch(false);
  resolve({ ok: true, modelId: "A", translations: ["LATE RESULT"] });
  await stopped.settle();
  assert.equal(stopped.document.querySelectorAll("[data-triloa-owned]").length, 0);

  const safe = page('<h1>Security</h1>');
  safe.state.pending = async () => ({ ok: true, modelId: "A", translations: ['<img src=x onerror="alert(1)">'] });
  await safe.settle();
  assert.deepEqual(translations(safe.document), ['<img src=x onerror="alert(1)">']);
  assert.equal(safe.document.querySelector('[data-triloa-owned="translation"]').shadowRoot.querySelector("img"), null);
  safe.switch(false);

  const disabled = page('<h1>Introduction</h1>', false);
  await disabled.settle();
  assert.equal(disabled.requests.length, 0);
  assert.equal(disabled.document.querySelectorAll("[data-triloa-owned]").length, 0);
  console.log("Inline translation checks passed: placement, lists, duplicates, dynamic content, model switch, stale responses, cleanup, text safety and site opt-in.");
}
run().catch(error => { console.error(error); process.exitCode = 1; });
