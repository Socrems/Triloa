"use strict";
// Run the real cache and message handlers without an Edge session or local model.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const read = (name) => fs.readFileSync(path.join(root, "extension", name), "utf8");
let passed = 0;

function panel(sendMessage = async () => ({ ok: true, modelId: "hy" })) {
  const scope = {
    active: true, checkingModel: false, requesting: false, lastError: "", modelError: "",
    RETRY_DELAY_MS: 8000, CACHE_LIMIT: 500, Error, Date,
    renders: 0, refreshes: 0,
    chrome: { runtime: { sendMessage } }
  };
  scope.render = () => scope.renders++;
  scope.scheduleRefresh = () => scope.refreshes++;
  vm.createContext(scope);
  vm.runInContext(read("model_cache.js"), scope);
  scope.modelCache = vm.runInContext("new TriloaModelCache(2)", scope);
  scope.cache = scope.modelCache.translations;
  scope.inFlight = scope.modelCache.inFlight;
  scope.retryAt = scope.modelCache.retryAt;
  const source = read("content.js");
  // Isolate the actual handlers; DOM insertion is covered by test_extension_inline.
  vm.runInContext(source.slice(source.indexOf("    async function requestTranslations("),
                               source.indexOf("    function refresh()")), scope);
  return scope;
}

async function check(name, action) {
  await action();
  passed++;
  console.log(`ok ${passed} - ${name}`);
}

async function main() {
  await check("model switch clears translations, requests and retries", () => {
    const s = panel();
    s.modelCache.setModel("hy");
    s.modelCache.remember("paragraph", "HY translation");
    s.modelCache.start(["pending"]);
    s.retryAt.set("failed", 10);
    assert.equal(s.modelCache.setModel("hy"), false);
    assert.equal(s.cache.size, 1);
    assert.equal(s.modelCache.setModel("qwen"), true);
    assert.equal(s.cache.size + s.inFlight.size + s.retryAt.size, 0);
  });
  await check("old replies cannot overwrite or finish new model work; LRU stays bounded", () => {
    const s = panel();
    s.modelCache.setModel("hy");
    const old = s.modelCache.start(["paragraph"]);
    s.modelCache.setModel("qwen");
    const current = s.modelCache.start(["paragraph"]);
    assert.equal(s.modelCache.remember("paragraph", "old", old), false);
    assert.equal(s.modelCache.finish(["paragraph"], old), false);
    assert.equal(s.inFlight.has("paragraph"), true);
    s.modelCache.remember("a", "A");
    s.modelCache.remember("b", "B");
    s.modelCache.remember("a", "updated A");
    s.modelCache.remember("c", "C");
    assert.deepEqual([...s.cache.keys()], ["a", "c"]);
    assert.equal(s.modelCache.finish(["paragraph"], current), true);
  });
  await check("health check invalidates an already cached page and schedules translation", async () => {
    const s = panel(async (message) => {
      assert.equal(message.type, "triloa:model");
      return { ok: true, modelId: "qwen" };
    });
    s.modelCache.setModel("hy");
    s.modelCache.remember("paragraph", "HY translation");
    await s.syncModel();
    assert.equal(s.modelCache.modelId, "qwen");
    assert.equal(s.cache.size, 0);
    assert.equal(s.refreshes, 1);
  });
  await check("translation can discover the new model and keep its valid response", async () => {
    const s = panel(async () => ({ ok: true, modelId: "qwen", translations: ["Qwen translation"] }));
    s.modelCache.setModel("hy");
    s.modelCache.remember("cached", "old");
    await s.requestTranslations(["paragraph"]);
    assert.equal(s.modelCache.modelId, "qwen");
    assert.equal(s.cache.size, 1);
    assert.equal(s.cache.get("paragraph"), "Qwen translation");
    assert.equal(s.inFlight.size, 0);
    assert.equal(s.refreshes, 1);
  });
  await check("delayed old translation is ignored after a model switch", async () => {
    let reply;
    const s = panel(() => new Promise((resolve) => { reply = resolve; }));
    s.modelCache.setModel("hy");
    const pending = s.requestTranslations(["paragraph"]);
    s.modelCache.setModel("qwen");
    s.modelCache.start(["paragraph"]);
    reply({ ok: true, modelId: "hy", translations: ["old"] });
    await pending;
    assert.equal(s.modelCache.modelId, "qwen");
    assert.equal(s.cache.size, 0);
    assert.equal(s.inFlight.has("paragraph"), true);
  });
  await check("delayed health check cannot roll back a newly adopted model", async () => {
    let reply;
    const s = panel(() => new Promise((resolve) => { reply = resolve; }));
    s.modelCache.setModel("hy");
    const pending = s.syncModel();
    s.modelCache.setModel("qwen");
    s.modelCache.remember("paragraph", "new");
    reply({ ok: true, modelId: "hy" });
    await pending;
    assert.equal(s.modelCache.modelId, "qwen");
    assert.equal(s.cache.get("paragraph"), "new");
    assert.equal(s.checkingModel, false);
  });
  await check("missing model identity produces a visible error without caching text", async () => {
    const s = panel(async () => ({ ok: true, translations: ["unidentified"] }));
    s.modelCache.setModel("hy");
    await s.requestTranslations(["paragraph"]);
    assert.match(s.lastError, /模型标识/);
    assert.equal(s.cache.size, 0);
    assert.equal(s.inFlight.size, 0);
  });
  await check("background passes model identity through both message types", async () => {
    let listener;
    const requested = [];
    const scope = {
      URL, Error, TypeError, AbortController, setTimeout, clearTimeout,
      chrome: {
        runtime: { id: "extension-id", onMessage: { addListener: (fn) => { listener = fn; } } },
        storage: { local: { get: async (key) => ({ [key]: true }) } }
      },
      fetch: async (url) => {
        requested.push(url);
        return { ok: true, json: async () => ({ model_id: "qwen" }),
          text: async () => JSON.stringify({ translations: ["译文"], model_id: "qwen" }) };
      }
    };
    vm.createContext(scope);
    vm.runInContext(read("background.js"), scope);
    const sender = { id: "extension-id", tab: { url: "https://example.test/article" } };
    const send = (message) => new Promise((resolve) => listener(message, sender, resolve));
    const health = await send({ type: "triloa:model" });
    assert.equal(health.modelId, "qwen");
    const translated = await send({ type: "triloa:translate", texts: ["hello"] });
    assert.equal(translated.modelId, "qwen");
    assert.equal(translated.translations[0], "译文");
    assert.deepEqual(requested, ["http://127.0.0.1:8765/health", "http://127.0.0.1:8765/translate"]);
  });
  const manifest = JSON.parse(read("manifest.json"));
  for (const name of manifest.content_scripts[0].js) {
    new vm.Script(read(name), { filename: name });
  }
  console.log(`Passed ${passed} extension regressions; content scripts and manifest parsed.`);
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
