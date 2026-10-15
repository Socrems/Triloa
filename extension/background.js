const TRANSLATE_URL = "http://127.0.0.1:8765/translate";
const HEALTH_URL = "http://127.0.0.1:8765/health";
const MAX_BATCH_SIZE = 32;
const MAX_TEXT_LENGTH = 8000;
const REQUEST_TIMEOUT_MS = 90000;

// Existing top-level web tabs do not receive newly installed content scripts.
// Each tab is independent: a store, PDF or restricted page must not abort others.
async function injectOpenPages() {
  let tabs;
  try {
    tabs = await chrome.tabs.query({ url: ["http://*/*", "https://*/*"] });
  } catch (error) {
    console.warn("Triloa 无法读取已打开的网页：", error);
    return;
  }
  for (const tab of tabs) {
    try {
      if (!Number.isInteger(tab.id) || !["http:", "https:"].includes(new URL(tab.url).protocol)) continue;
      for (const file of ["model_cache.js", "floating_ball.js", "content.js"]) {
        await chrome.scripting.executeScript({ target: { tabId: tab.id, frameIds: [0] }, files: [file] });
      }
    } catch (error) {
      console.warn("Triloa 无法在此标签页加载；可刷新普通网页重试：", tab.id, error);
    }
  }
}
chrome.runtime.onInstalled.addListener(() => { void injectOpenPages(); });
chrome.storage.onChanged.addListener((changes, area) => {
  const change = changes["triloa:ball:enabled"];
  if (area === "local" && change?.newValue === true && change.oldValue !== true) void injectOpenPages();
});

function serviceError(payload, rawText, status) {
  const detail = payload && typeof payload === "object"
    ? (payload.detail ?? payload.error ?? payload.message)
    : null;
  let message = "";
  if (typeof detail === "string") {
    message = detail;
  } else if (detail != null) {
    try {
      message = JSON.stringify(detail);
    } catch {
      message = String(detail);
    }
  }
  if (!message && rawText) message = rawText.slice(0, 400);
  return `本地翻译服务返回 HTTP ${status}${message ? `：${message}` : ""}`;
}

async function translateBatch(texts) {
  if (!Array.isArray(texts) || texts.length < 1 || texts.length > MAX_BATCH_SIZE) {
    throw new Error("翻译请求包含无效的段落数量。");
  }
  if (texts.some((text) => typeof text !== "string" || !text.trim() || text.length > MAX_TEXT_LENGTH)) {
    throw new Error("翻译请求包含空段落或过长段落。");
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(TRANSLATE_URL, {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ texts, source: "auto", target: "zh" }),
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      signal: controller.signal
    });

    const rawText = await response.text();
    let payload = null;
    try {
      payload = rawText ? JSON.parse(rawText) : null;
    } catch {
      // A non-JSON error body is shown as plain text below.
    }

    if (!response.ok) {
      throw new Error(serviceError(payload, rawText, response.status));
    }
    if (!payload || !Array.isArray(payload.translations) || payload.translations.length !== texts.length) {
      throw new Error("本地服务响应格式无效：需要与请求段落数量相同的 translations 数组。");
    }
    if (payload.translations.some((item) => typeof item !== "string" || !item.trim())) {
      throw new Error("本地服务未能翻译所有段落。请检查服务状态和模型安装情况。");
    }
    if (typeof payload.model_id !== "string" || !payload.model_id) {
      throw new Error("本地服务缺少模型标识，请更新 Triloa。");
    }
    return { translations: payload.translations, modelId: payload.model_id };
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("本地翻译服务响应超时。请检查服务状态和模型运行情况。");
    }
    if (error instanceof TypeError) {
      throw new Error("无法连接本地翻译服务（127.0.0.1:8765）。请先启动本地服务；若已启动，请检查服务端口和 Origin 配置。");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

async function getModelIdentity() {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(HEALTH_URL, {
      cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer",
      signal: controller.signal
    });
    const payload = await response.json();
    if (!response.ok || typeof payload?.model_id !== "string" || !payload.model_id) {
      throw new Error("无法读取翻译模型标识，请启动或更新本地 Triloa 服务。");
    }
    return { modelId: payload.model_id };
  } catch (error) {
    if (error?.name === "AbortError" || error instanceof TypeError) {
      throw new Error("无法检查翻译模型，请确认本地 Triloa 服务正在运行。");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!["triloa:translate", "triloa:model"].includes(message?.type)) return false;
  if (sender.id !== chrome.runtime.id || !sender.tab) {
    sendResponse({ ok: false, error: "翻译请求来源无效。" });
    return false;
  }

  let siteKey;
  try {
    const url = new URL(sender.url || sender.tab.url);
    if (!["http:", "https:"].includes(url.protocol)) throw new Error();
    siteKey = `triloa:enabled:${url.origin}`;
  } catch {
    sendResponse({ ok: false, error: "当前页面不支持网页翻译。" });
    return false;
  }

  chrome.storage.local.get(siteKey)
    .then((settings) => {
      if (settings[siteKey] !== true) throw new Error("此网站尚未开启网页翻译。");
      return message.type === "triloa:model" ? getModelIdentity() : translateBatch(message.texts);
    })
    .then((result) => sendResponse({ ok: true, ...result }))
    .catch((error) => sendResponse({
      ok: false,
      error: error instanceof Error ? error.message : "本地翻译服务发生未知错误。"
    }));
  return true;
});
