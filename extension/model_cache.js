"use strict";

// A generation prevents replies from the previous model from restoring stale text.
globalThis.TriloaModelCache = class TriloaModelCache {
  constructor(limit = 500) {
    this.limit = limit;
    this.modelId = null;
    this.generation = 0;
    this.translations = new Map();
    this.inFlight = new Set();
    this.retryAt = new Map();
  }

  setModel(modelId) {
    if (typeof modelId !== "string" || !modelId) throw new Error("本地服务缺少模型标识，请更新 Triloa。");
    if (modelId === this.modelId) return false;
    this.modelId = modelId;
    this.generation++;
    this.translations.clear();
    this.inFlight.clear();
    this.retryAt.clear();
    return true;
  }

  start(texts) {
    for (const text of texts) this.inFlight.add(text);
    return this.generation;
  }

  finish(texts, generation) {
    if (generation !== this.generation) return false;
    for (const text of texts) this.inFlight.delete(text);
    return true;
  }

  remember(text, translation, generation = this.generation) {
    if (generation !== this.generation) return false;
    this.translations.delete(text);
    this.translations.set(text, translation);
    while (this.translations.size > this.limit) {
      this.translations.delete(this.translations.keys().next().value);
    }
    return true;
  }
};
