"use strict";
const siteLabel = document.getElementById("site");
const enabledSwitch = document.getElementById("enabled");
const ballSwitch = document.getElementById("ball-enabled");
const restoreButton = document.getElementById("restore-ball");
const ballStatus = document.getElementById("ball-status");
const statusLabel = document.getElementById("status");
const BALL_KEY = "triloa:ball:enabled";
let siteKey = null;
let hiddenKey = null;
let ready = false;
let disposed = false;
let errorMessage = "";
const values = { [BALL_KEY]: false };
const revisions = new Map([[BALL_KEY, 0]]);
const pending = new Set();

function render() {
  if (disposed) return;
  enabledSwitch.checked = values[siteKey] === true;
  enabledSwitch.disabled = !ready || !siteKey || pending.has(siteKey);
  ballSwitch.checked = values[BALL_KEY] === true;
  ballSwitch.disabled = !ready || pending.has(BALL_KEY);
  restoreButton.disabled = !ready || !hiddenKey || !values[hiddenKey] || pending.has(hiddenKey);
  ballStatus.textContent = !hiddenKey ? "打开普通网页后可恢复本站悬浮球。" : values[hiddenKey]
    ? "悬浮球已在此网站隐藏。" : values[BALL_KEY] ? "悬浮球会显示在此网站。" : "本站允许显示；全局开关目前关闭。";
  statusLabel.textContent = errorMessage || (!siteKey
    ? "Edge 内置页面、扩展商店和浏览器 PDF 等页面可能不支持注入；普通网页可刷新后使用。"
    : values[siteKey] ? "本站翻译已开启。中文译文显示在原文下方；请保持 Triloa 本地服务运行。"
      : "本站翻译已关闭。悬浮球的显示设置不会改变翻译开关。");
  statusLabel.classList.toggle("error", Boolean(errorMessage));
}

async function save(key, value) {
  if (!key || pending.has(key)) return;
  const previous = values[key];
  const revision = (revisions.get(key) || 0) + 1;
  revisions.set(key, revision);
  pending.add(key);
  values[key] = value;
  errorMessage = "";
  render();
  try {
    await chrome.storage.local.set({ [key]: value });
  } catch (error) {
    if (disposed) return;
    if (revisions.get(key) === revision) values[key] = previous;
    errorMessage = `保存设置失败，请重试：${error instanceof Error ? error.message : String(error)}`;
  } finally {
    pending.delete(key);
    render();
  }
}
function onStorageChanged(changes, area) {
  if (disposed || area !== "local") return;
  for (const key of [BALL_KEY, siteKey, hiddenKey]) {
    if (!key || !Object.hasOwn(changes, key)) continue;
    revisions.set(key, (revisions.get(key) || 0) + 1);
    values[key] = changes[key].newValue === true;
  }
  render();
}
chrome.storage.onChanged.addListener(onStorageChanged);
enabledSwitch.addEventListener("change", () => { void save(siteKey, enabledSwitch.checked); });
ballSwitch.addEventListener("change", () => { void save(BALL_KEY, ballSwitch.checked); });
restoreButton.addEventListener("click", () => { void save(hiddenKey, false); });
window.addEventListener("pagehide", () => {
  disposed = true;
  chrome.storage.onChanged.removeListener(onStorageChanged);
}, { once: true });

async function initialize() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const url = tab?.url ? new URL(tab.url) : null;
    if (url && ["http:", "https:"].includes(url.protocol)) {
      siteKey = `triloa:enabled:${url.origin}`;
      hiddenKey = `triloa:ball:hidden:${url.origin}`;
      values[siteKey] = false;
      values[hiddenKey] = false;
      revisions.set(siteKey, 0);
      revisions.set(hiddenKey, 0);
      siteLabel.textContent = url.host;
    } else siteLabel.textContent = "当前页面不支持网页翻译";
    const keys = [BALL_KEY, siteKey, hiddenKey].filter(Boolean);
    const initial = new Map(revisions);
    const settings = await chrome.storage.local.get(keys);
    if (disposed) return;
    for (const key of keys) {
      if (initial.get(key) === revisions.get(key)) values[key] = settings[key] === true;
    }
    ready = true;
  } catch (error) {
    errorMessage = `无法读取设置：${error instanceof Error ? error.message : String(error)}`;
  }
  render();
}
void initialize();
