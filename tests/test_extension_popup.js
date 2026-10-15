"use strict";
const { parseHTML } = require(process.env.TRILOA_DOM_MODULE || "../cache/extension-dom-test/node_modules/linkedom");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const read = name => fs.readFileSync(path.join(__dirname, "../extension", name), "utf8");
const SITE = "triloa:enabled:https://example.com", BALL = "triloa:ball:enabled", HIDDEN = "triloa:ball:hidden:https://example.com";

function popup(initial = {}, options = {}) {
  const { document, window } = parseHTML(read("popup.html"));
  const values = { ...initial }, listeners = new Set(), writes = [];
  const result = {
    document, window, values, listeners, writes, fail: false, delaySet: null,
    control(id) { return document.getElementById(id); },
    change(next) {
      const changes = {};
      for (const [key, value] of Object.entries(next)) { changes[key] = { newValue: value, oldValue: values[key] }; values[key] = value; }
      for (const listener of listeners) listener(changes, "local");
    },
    event(id, type, checked) {
      const target = result.control(id);
      if (checked !== undefined) target.checked = checked;
      target.dispatchEvent(new window.Event(type, { bubbles: true }));
    },
    async settle() { for (let count = 0; count < 15; count++) await Promise.resolve(); }
  };
  const chrome = {
    tabs: { query: async () => [{ url: options.url || "https://example.com/article" }] },
    storage: {
      onChanged: { addListener: cb => listeners.add(cb), removeListener: cb => listeners.delete(cb) },
      local: {
        get: async () => options.get ? options.get({ ...values }) : { ...values },
        set: async next => {
          writes.push({ ...next });
          if (result.fail) { result.fail = false; throw Error("fixture write failure"); }
          if (result.delaySet) return result.delaySet(next);
          result.change(next);
        }
      }
    }
  };
  const context = vm.createContext({ window, document, chrome, URL, console });
  vm.runInContext(read("popup.js"), context);
  return result;
}
let passed = 0;
async function check(name, action) { await action(); console.log(`ok ${++passed} - ${name}`); }
async function main() {
  await check("popup restores only site visibility and keeps translation independent from global display", async () => {
    const p = popup({ [SITE]: true, [BALL]: true, [HIDDEN]: true }); await p.settle();
    assert.equal(p.control("enabled").checked, true); assert.equal(p.control("ball-enabled").checked, true); assert.equal(p.control("restore-ball").disabled, false);
    p.event("restore-ball", "click"); await p.settle(); assert.deepEqual(p.writes, [{ [HIDDEN]: false }]); assert.equal(p.values[SITE], true);
    p.event("ball-enabled", "change", false); await p.settle(); assert.equal(p.values[SITE], true); assert.equal(p.values[HIDDEN], false);
    p.change({ [SITE]: false, [HIDDEN]: true, [BALL]: true });
    assert.equal(p.control("enabled").checked, false); assert.equal(p.control("ball-enabled").checked, true); assert.equal(p.control("restore-ball").disabled, false);
    p.window.dispatchEvent(new p.window.Event("pagehide")); assert.equal(p.listeners.size, 0);
  });
  await check("popup late read preserves all newer key changes", async () => {
    let resolve; const p = popup({}, { get: snapshot => new Promise(done => { resolve = () => done(snapshot); }) }); await p.settle();
    p.change({ [SITE]: true, [BALL]: true, [HIDDEN]: true }); resolve(); await p.settle();
    assert.equal(p.control("enabled").checked, true); assert.equal(p.control("ball-enabled").checked, true); assert.equal(p.control("restore-ball").disabled, false);
  });
  await check("popup failed write rolls back while a newer external value survives late rejection", async () => {
    const p = popup(); await p.settle(); p.fail = true; p.event("enabled", "change", true); await p.settle();
    assert.equal(p.control("enabled").checked, false); assert.match(p.control("status").textContent, /保存设置失败/); assert.equal(p.control("enabled").disabled, false);
    let reject; p.delaySet = () => new Promise((_, fail) => { reject = fail; }); p.event("enabled", "change", true);
    p.change({ [SITE]: false }); p.change({ [SITE]: true }); reject(Error("late fixture failure")); await p.settle(); assert.equal(p.control("enabled").checked, true);
  });
  await check("restricted pages retain global ball control and disable unavailable site actions", async () => {
    const p = popup({}, { url: "edge://extensions" }); await p.settle();
    assert.equal(p.control("enabled").disabled, true); assert.equal(p.control("restore-ball").disabled, true); assert.equal(p.control("ball-enabled").disabled, false);
    p.event("ball-enabled", "change", true); await p.settle(); assert.deepEqual(p.writes, [{ [BALL]: true }]);
  });
  console.log(`Passed ${passed} popup fixtures.`);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
