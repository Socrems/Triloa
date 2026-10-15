"use strict";
// Browser DOM fixtures with in-memory extension APIs, not a real MV3 session.
const { parseHTML } = require(process.env.TRILOA_DOM_MODULE || "../cache/extension-dom-test/node_modules/linkedom");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const read = name => fs.readFileSync(path.join(__dirname, "../extension", name), "utf8");
const BALL = "triloa:ball:enabled", POS = "triloa:ball:position";
const enabled = origin => `triloa:enabled:${origin}`;
const hidden = origin => `triloa:ball:hidden:${origin}`;
const A = "https://example.com", B = "https://other.test";
const copy = value => value == null ? value : JSON.parse(JSON.stringify(value));

function storage(initial = {}) {
  const data = copy(initial), listeners = new Set(), writes = [];
  const hub = {
    data, listeners, writes, fail: false, delaySet: null,
    change(next) {
      const changes = {};
      for (const [key, value] of Object.entries(next)) {
        changes[key] = { oldValue: data[key], newValue: copy(value) };
        data[key] = copy(value);
      }
      for (const listener of [...listeners]) listener(changes, "local");
    },
    async set(next) {
      writes.push(copy(next));
      if (hub.fail) { hub.fail = false; throw new Error("fixture write failure"); }
      if (hub.delaySet) return hub.delaySet(next);
      hub.change(next);
    }
  };
  return hub;
}
function page(hub, origin = A, options = {}) {
  const { window, document } = parseHTML('<html lang="en"><body><h1>Introduction</h1><p>This is an English paragraph for reading.</p></body></html>');
  const timers = new Map(), intervals = new Map();
  let serial = 0, observers = 0, scans = 0;
  const requests = [], captures = [];
  const state = { pending: null };
  window.innerWidth = 1000; window.innerHeight = 800;
  window.HTMLElement.prototype.getBoundingClientRect = function () {
    return this.className === "panel" ? { height: 220, width: 260 } : { width: 700, height: 30, top: 50, bottom: 80, left: 20, right: 720 };
  };
  window.HTMLElement.prototype.setPointerCapture = id => captures.push(["set", id]);
  window.HTMLElement.prototype.releasePointerCapture = id => captures.push(["release", id]);
  window.getComputedStyle = () => ({ display: "block", visibility: "visible", opacity: "1", fontFamily: "Arial", fontSize: "16px", fontWeight: "400", color: "black", textAlign: "left" });
  window.setTimeout = callback => { timers.set(++serial, callback); return serial; };
  window.clearTimeout = id => timers.delete(id);
  window.setInterval = callback => { intervals.set(++serial, callback); return serial; };
  window.clearInterval = id => intervals.delete(id);
  const NativeObserver = window.MutationObserver;
  class Observer {
    constructor(callback) { this.inner = new NativeObserver(callback); this.running = false; }
    observe(...args) { if (!this.running) observers++; this.running = true; this.inner.observe(...args); }
    disconnect() { if (this.running) observers--; this.running = false; this.inner.disconnect(); }
  }
  const queryAll = document.querySelectorAll.bind(document);
  document.querySelectorAll = selector => { if (selector === "p, h1, h2, h3, h4, h5, h6, li") scans++; return queryAll(selector); };
  const chrome = {
    storage: {
      local: { get: async keys => {
        const snapshot = Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(key => [key, copy(hub.data[key])]));
        return options.get ? options.get(snapshot) : snapshot;
      }, set: next => hub.set(next) },
      onChanged: { addListener: cb => hub.listeners.add(cb), removeListener: cb => hub.listeners.delete(cb) }
    },
    runtime: { sendMessage: async message => {
      requests.push(copy(message));
      if (message.type === "triloa:model") return { ok: true, modelId: "fixture" };
      if (state.pending) return state.pending(message);
      return { ok: true, modelId: "fixture", translations: message.texts.map(text => `中文：${text}`) };
    } }
  };
  const context = vm.createContext({ window, document, MutationObserver: Observer, chrome, location: { origin }, console });
  if (options.legacy) {
    const node = document.createElement("span"); node.setAttribute("data-triloa-owned", "translation"); document.body.append(node);
  }
  function inject() { for (const file of ["model_cache.js", "floating_ball.js", "content.js"]) vm.runInContext(read(file), context); }
  inject();
  const result = {
    window, document, context, requests, state, captures, inject,
    get observers() { return observers; }, get scans() { return scans; }, get intervals() { return intervals.size; },
    host() { return document.querySelector('[data-triloa-owned="ball"]'); },
    ball() { return result.host()?.shadowRoot.querySelector(".ball"); },
    root() { return result.host()?.shadowRoot; },
    emit(target, type, props = {}) { const event = new window.Event(type, { bubbles: true, cancelable: true }); Object.assign(event, props); target.dispatchEvent(event); },
    click(target) { result.emit(target, "click", { detail: 1 }); },
    async settle() {
      for (let count = 0; count < 35; count++) {
        await Promise.resolve(); await Promise.resolve();
        if (!timers.size) { await Promise.resolve(); if (!timers.size) return; }
        const callbacks = [...timers.values()]; timers.clear(); for (const callback of callbacks) callback();
      }
      throw Error("Fixture did not settle");
    },
    dispose() { vm.runInContext("globalThis.__triloaController?.dispose()", context); }
  };
  return result;
}
let passed = 0;
async function check(name, fn) { await fn(); console.log(`ok ${++passed} - ${name}`); }

async function main() {
  await check("default ball is off; visible idle ball never scans or checks the model", async () => {
    const hub = storage(), p = page(hub); await p.settle(); assert.equal(p.host(), null);
    hub.change({ [BALL]: true }); await p.settle();
    assert.ok(p.ball()); assert.equal(p.ball().tagName, "BUTTON"); assert.equal(p.ball().getAttribute("aria-pressed"), "false");
    assert.equal(p.host().style.left, "940px"); assert.equal(p.host().style.top, "378px");
    assert.equal(p.requests.length, 0); assert.equal(p.observers, 0); assert.equal(p.scans, 0); assert.equal(p.intervals, 0);
    p.dispose(); assert.equal(hub.listeners.size, 0); assert.equal(p.host(), null);
  });
  await check("ball toggle, per-site hide and global visibility preserve independent translation state", async () => {
    const hub = storage({ [BALL]: true }), p = page(hub); await p.settle();
    p.click(p.ball()); await p.settle(); assert.equal(hub.data[enabled(A)], true); assert.equal(p.observers, 1);
    const count = p.requests.length;
    p.click(p.root().querySelector('[aria-label="在此网站隐藏悬浮球"]')); await p.settle();
    assert.equal(p.host(), null); assert.equal(hub.data[enabled(A)], true); assert.equal(p.observers, 1);
    hub.change({ [hidden(A)]: false, [BALL]: false }); await p.settle();
    assert.equal(p.host(), null); assert.equal(p.observers, 1); assert.equal(p.requests.length, count);
    hub.change({ [BALL]: true }); await p.settle(); assert.ok(p.ball());
    p.click(p.ball()); await p.settle(); assert.equal(hub.data[enabled(A)], false); assert.equal(p.observers, 0);
    assert.equal(p.document.querySelectorAll('[data-triloa-owned="translation"]').length, 0); assert.ok(p.ball()); p.dispose();
  });
  await check("same-origin tabs sync while other origins keep independent translation and hidden state", async () => {
    const hub = storage({ [BALL]: true }), p = page(hub), same = page(hub), other = page(hub, B);
    await Promise.all([p.settle(), same.settle(), other.settle()]); p.click(p.ball()); await Promise.all([p.settle(), same.settle(), other.settle()]);
    assert.equal(same.ball().getAttribute("aria-pressed"), "true"); assert.equal(other.ball().getAttribute("aria-pressed"), "false");
    hub.change({ [hidden(A)]: true }); assert.equal(p.host(), null); assert.equal(same.host(), null); assert.ok(other.host());
    hub.change({ [POS]: { side: "left", yRatio: 1 } }); assert.equal(other.host().style.left, "16px"); assert.equal(other.host().style.top, "740px");
    hub.change({ [BALL]: false }); assert.equal(other.host(), null); assert.equal(p.observers, 1);
    for (const value of [p, same, other]) value.dispose();
  });
  await check("initial storage read cannot overwrite newer per-key changes", async () => {
    let resolve; const hub = storage(); const p = page(hub, A, { get: snapshot => new Promise(done => { resolve = () => done(snapshot); }) });
    hub.change({ [BALL]: true, [hidden(A)]: true, [enabled(A)]: true, [POS]: { side: "left", yRatio: .25 } });
    resolve(); await p.settle(); assert.equal(p.host(), null); assert.equal(p.observers, 1);
    hub.change({ [hidden(A)]: false }); assert.equal(p.host().style.left, "16px"); assert.equal(p.host().style.top, "197px");
    assert.equal(p.ball().getAttribute("aria-pressed"), "true"); p.dispose();
  });
  await check("failed save rolls back and reports plain-text error; later external change wins", async () => {
    const hub = storage({ [BALL]: true }), p = page(hub); await p.settle(); hub.fail = true;
    p.click(p.ball()); await p.settle(); assert.equal(p.ball().getAttribute("aria-pressed"), "false"); assert.equal(p.observers, 0);
    assert.match(p.document.querySelector('[data-triloa-owned="preference-notice"]').shadowRoot.querySelector('[role="status"]').textContent, /保存设置失败/);
    let reject; hub.delaySet = () => new Promise((_, fail) => { reject = fail; });
    p.click(p.ball()); hub.change({ [enabled(A)]: false }); hub.change({ [enabled(A)]: true }); reject(Error("late failure")); await p.settle();
    assert.equal(p.ball().getAttribute("aria-pressed"), "true"); assert.equal(p.observers, 1); p.dispose();
  });
  await check("drag threshold, capture, one release write, snap and trailing click suppression", async () => {
    const hub = storage({ [BALL]: true }), p = page(hub); await p.settle(); const button = p.ball();
    p.emit(button, "pointerdown", { pointerId: 1, button: 0, isPrimary: true, clientX: 960, clientY: 400 });
    p.emit(button, "pointermove", { pointerId: 1, clientX: 957, clientY: 398 }); assert.equal(hub.writes.length, 0);
    p.emit(button, "pointermove", { pointerId: 1, clientX: 30, clientY: 780 }); assert.equal(hub.writes.length, 0);
    p.emit(button, "pointerup", { pointerId: 1 }); assert.equal(hub.writes.length, 1); assert.equal(hub.data[POS].side, "left"); assert.equal(hub.data[POS].yRatio, 1);
    p.click(button); await p.settle(); assert.equal(hub.data[enabled(A)], undefined); assert.deepEqual(p.captures, [["set", 1], ["release", 1]]);
    p.emit(button, "pointerdown", { pointerId: 2, button: 0, isPrimary: false, clientX: 30, clientY: 780 });
    p.emit(button, "pointermove", { pointerId: 2, clientX: 300, clientY: 500 }); p.emit(button, "pointerup", { pointerId: 2 }); assert.equal(hub.writes.length, 1);
    p.emit(button, "click", { detail: 0 }); await p.settle(); assert.equal(hub.data[enabled(A)], true); p.dispose();
  });
  await check("external position waits for dragging; release keeps local position and cancellation adopts external", async () => {
    const hub = storage({ [BALL]: true }), p = page(hub); await p.settle(); const button = p.ball();
    p.emit(button, "pointerdown", { pointerId: 3, button: 0, clientX: 960, clientY: 400 });
    p.emit(button, "pointermove", { pointerId: 3, clientX: 900, clientY: 500 }); const before = p.host().style.top;
    hub.change({ [POS]: { side: "left", yRatio: 0 } }); assert.equal(p.host().style.top, before);
    p.emit(button, "pointerup", { pointerId: 3 }); await p.settle(); assert.equal(hub.data[POS].side, "right"); assert.equal(p.host().style.left, "940px");
    p.emit(button, "pointerdown", { pointerId: 4, button: 0, clientX: 960, clientY: 500 });
    p.emit(button, "pointermove", { pointerId: 4, clientX: 600, clientY: 600 }); hub.change({ [POS]: { side: "left", yRatio: 0 } });
    p.emit(button, "pointercancel", { pointerId: 4 }); assert.equal(p.host().style.top, "16px"); assert.equal(p.host().style.left, "16px"); assert.equal(hub.writes.length, 1);
    p.window.innerWidth = 200; p.window.innerHeight = 120; p.emit(p.window, "resize"); assert.equal(p.host().style.left, "16px");
    assert.ok(Number.parseFloat(p.host().style.top) >= 0); p.dispose();
  });
  await check("settings stay inside vertical viewport; Escape closes; reset only writes position", async () => {
    const hub = storage({ [BALL]: true, [POS]: { side: "right", yRatio: 1 } }), p = page(hub); await p.settle();
    p.click(p.root().querySelector('[aria-label="悬浮球设置"]')); const panel = p.root().querySelector(".panel"); assert.equal(panel.hidden, false);
    const top = Number.parseFloat(p.host().style.top) + Number.parseFloat(panel.style.top); assert.ok(top >= 12 && top + 220 <= 788);
    p.click(p.root().querySelector(".reset")); await p.settle(); assert.deepEqual(hub.data[POS], { side: "right", yRatio: .5 }); assert.equal(hub.data[enabled(A)], undefined);
    p.emit(p.root(), "keydown", { key: "Escape" }); assert.equal(panel.hidden, true); assert.equal(p.root().querySelector(".tools").hidden, true); p.dispose();
  });
  await check("reinjection and DOM cleanup event dispose old observers/listeners and invalidate pending replies", async () => {
    const hub = storage({ [BALL]: true, [enabled(A)]: true }), p = page(hub); let resolve;
    p.state.pending = () => new Promise(done => { resolve = done; }); await p.settle();
    p.inject(); p.state.pending = null; await p.settle(); assert.equal(hub.listeners.size, 1); assert.equal(p.observers, 1); assert.equal(p.intervals, 1);
    assert.equal(p.document.querySelectorAll('[data-triloa-owned="ball"]').length, 1);
    resolve({ ok: true, modelId: "old", translations: ["OLD", "OLD"] }); await p.settle();
    assert.ok([...p.document.querySelectorAll('[data-triloa-owned="translation"]')].every(node => !node.shadowRoot.querySelector("span").textContent.includes("OLD")));
    p.emit(p.document, "triloa:dispose:v014"); assert.equal(hub.listeners.size, 0); assert.equal(p.observers, 0); assert.equal(p.intervals, 0); assert.equal(p.host(), null);
  });
  await check("legacy v0.1.3 DOM asks for refresh and starts no duplicate scanning", async () => {
    const hub = storage({ [BALL]: true, [enabled(A)]: true }), p = page(hub, A, { legacy: true }); await p.settle();
    assert.match(p.document.querySelector('[data-triloa-owned="preference-notice"]').shadowRoot.querySelector('[role="status"]').textContent, /旧版脚本.*刷新/);
    assert.equal(p.requests.length, 0); assert.equal(p.observers, 0); p.dispose();
  });
  await check("background injects only HTTP(S) top frames in file order and isolates restricted-tab failures", async () => {
    let install, change; const calls = [], warnings = [];
    const scope = { URL, console: { warn: (...args) => warnings.push(args) },
      chrome: { runtime: { onInstalled: { addListener: cb => { install = cb; } }, onMessage: { addListener() {} } },
        storage: { onChanged: { addListener: cb => { change = cb; } } },
        tabs: { query: async () => [{ id: 1, url: A }, { id: 2, url: "https://restricted.test/" }, { id: 3, url: B }, { id: 4, url: "edge://extensions" }, { id: 5, url: "file:///sample.html" }] },
        scripting: { executeScript: async args => { calls.push(copy(args)); if (args.target.tabId === 2) throw Error("Restricted page"); } } } };
    vm.createContext(scope); vm.runInContext(read("background.js"), scope); install();
    for (let i = 0; i < 25; i++) await Promise.resolve();
    assert.deepEqual(calls.map(call => [call.target.tabId, call.files[0]]), [[1,"model_cache.js"],[1,"floating_ball.js"],[1,"content.js"],[2,"model_cache.js"],[3,"model_cache.js"],[3,"floating_ball.js"],[3,"content.js"]]);
    assert.ok(calls.every(call => JSON.stringify(call.target.frameIds) === "[0]")); assert.equal(warnings.length, 1);
    const count = calls.length; change({ [BALL]: { oldValue: true, newValue: true } }, "local"); assert.equal(calls.length, count);
    change({ [BALL]: { oldValue: false, newValue: true } }, "local"); for (let i = 0; i < 25; i++) await Promise.resolve(); assert.equal(calls.length, count * 2);
    const manifest = JSON.parse(read("manifest.json")); assert.equal(manifest.version, "0.1.4"); assert.ok(manifest.permissions.includes("scripting"));
    assert.ok(!manifest.permissions.includes("tabs")); assert.ok(!manifest.content_scripts[0].all_frames); assert.deepEqual(manifest.host_permissions, ["http://*/*", "https://*/*"]);
  });
  console.log(`Passed ${passed} floating-ball fixtures.`);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
