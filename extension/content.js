(() => {
  const SELECTOR = "p, h1, h2, h3, h4, h5, h6, li";
  const OWN = "[data-triloa-owned]";
  const SKIP = `nav, footer, aside, [role='navigation'], [role='menu'], pre, code, button, textarea, select, [hidden], [aria-hidden='true'], [contenteditable]:not([contenteditable='false']), ${OWN}`;
  const MAX_BLOCKS = 32;
  const MAX_TEXT_LENGTH = 8000;
  const CACHE_LIMIT = 500;
  const RETRY_DELAY_MS = 8000;
  const ENGLISH_STOP_WORDS = new Set([
    "a", "about", "after", "all", "also", "am", "an", "and", "are", "as", "at",
    "be", "because", "been", "before", "but", "by", "can", "could", "did", "do",
    "does", "for", "from", "had", "has", "have", "he", "her", "here", "him", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "may", "more", "most", "not",
    "of", "on", "or", "our", "out", "she", "should", "so", "some", "than", "that",
    "the", "their", "them", "then", "there", "these", "they", "this", "those", "to",
    "up", "us", "was", "we", "were", "what", "when", "where", "which", "who", "will",
    "with", "would", "you", "your"
  ]);

  if (!document.documentElement || (window.top && window.top !== window)) return;
  // The DOM event also reaches controllers from a previous extension world.
  // v0.1.3 did not expose disposal, so its observers require a page refresh.
  const DISPOSE_EVENT = "triloa:dispose:v014";
  const hadLegacyFlag = globalThis.__triloaViewportTranslationLoaded && !globalThis.__triloaController;
  globalThis.__triloaController?.dispose();
  document.dispatchEvent(new window.Event(DISPOSE_EVENT));
  const upgradeRequired = Boolean(hadLegacyFlag || document.querySelector('[data-triloa-owned="translation"], [data-triloa-owned="status"]'));
  globalThis.__triloaViewportTranslationLoaded = true;
  const ENABLED_KEY = `triloa:enabled:${location.origin}`;
  const BALL_KEY = "triloa:ball:enabled";
  const HIDDEN_KEY = `triloa:ball:hidden:${location.origin}`;
  const POSITION_KEY = "triloa:ball:position";
  const keys = [ENABLED_KEY, BALL_KEY, HIDDEN_KEY, POSITION_KEY];
  const values = { [ENABLED_KEY]: false, [BALL_KEY]: false, [HIDDEN_KEY]: false,
    [POSITION_KEY]: { side: "right", yRatio: .5 } };
  const revisions = new Map(keys.map(key => [key, 0]));
  const pending = new Set();
  let active = true;
  let controller = null;
  let ball = null;
  let preferenceNotice = null;
  let preferenceError = "";

  function normalizePreference(key, value) {
    if (key !== POSITION_KEY) return value === true;
    return { side: value?.side === "left" ? "left" : "right",
      yRatio: typeof value?.yRatio === "number" && Number.isFinite(value.yRatio) ? Math.max(0, Math.min(1, value.yRatio)) : .5 };
  }

  function setEnabled(enabled) {
    if (enabled && !controller && !upgradeRequired) controller = createInlineTranslation();
    if (!enabled && controller) {
      controller.stop();
      controller = null;
    }
  }

  function renderPreferences() {
    if (!active) return;
    setEnabled(values[ENABLED_KEY]);
    const visible = values[BALL_KEY] && !values[HIDDEN_KEY];
    if (visible && !ball) {
      ball = globalThis.TriloaFloatingBall({
        onToggle: () => savePreference(ENABLED_KEY, !values[ENABLED_KEY]),
        onHide: () => savePreference(HIDDEN_KEY, true),
        onGlobalChange: value => savePreference(BALL_KEY, value),
        onReset: () => savePreference(POSITION_KEY, { side: "right", yRatio: .5 }),
        onPosition: value => savePreference(POSITION_KEY, value)
      });
    }
    if (!visible && ball) { ball.dispose(); ball = null; }
    ball?.update({ enabled: values[ENABLED_KEY], ballEnabled: values[BALL_KEY], position: values[POSITION_KEY],
      pending: { enabled: pending.has(ENABLED_KEY), ball: pending.has(BALL_KEY), hidden: pending.has(HIDDEN_KEY), position: pending.has(POSITION_KEY) },
      upgrade: upgradeRequired });
    const message = preferenceError || (upgradeRequired ? "Triloa 扩展已更新。此页仍有旧版脚本，请刷新网页完成升级。" : "");
    if (message && !preferenceNotice) {
      preferenceNotice = document.createElement("div");
      preferenceNotice.setAttribute("data-triloa-owned", "preference-notice");
      preferenceNotice.style.cssText = "position:fixed;bottom:16px;right:16px;z-index:2147483647;max-width:min(360px,90vw);";
      const root = preferenceNotice.attachShadow({ mode: "open" });
      const css = document.createElement("style");
      css.textContent = "div{box-sizing:border-box;padding:12px 16px;background:#FFFFFF;color:#223047;border:1px solid #D9E0E9;border-radius:12px;font:14px/1.5 system-ui;box-shadow:0 4px 20px #22304720}";
      const text = document.createElement("div");
      text.setAttribute("role", "status");
      root.append(css, text);
      document.documentElement.append(preferenceNotice);
    }
    if (message) preferenceNotice.shadowRoot.querySelector("div").textContent = message;
    else { preferenceNotice?.remove(); preferenceNotice = null; }
  }

  async function savePreference(key, value) {
    if (!active || pending.has(key)) return;
    const before = values[key];
    const revision = revisions.get(key) + 1;
    revisions.set(key, revision);
    pending.add(key);
    values[key] = normalizePreference(key, value);
    preferenceError = "";
    renderPreferences();
    try {
      await chrome.storage.local.set({ [key]: values[key] });
    } catch (error) {
      if (!active) return;
      if (revisions.get(key) === revision) values[key] = before;
      preferenceError = `保存设置失败，请重试：${error instanceof Error ? error.message : String(error)}`;
    } finally {
      if (active) { pending.delete(key); renderPreferences(); }
    }
  }
  function onStorageChanged(changes, area) {
    if (!active || area !== "local") return;
    for (const key of keys) {
      if (!Object.hasOwn(changes, key)) continue;
      revisions.set(key, revisions.get(key) + 1);
      values[key] = normalizePreference(key, changes[key].newValue);
    }
    renderPreferences();
  }
  function dispose() {
    if (!active) return;
    active = false;
    chrome.storage.onChanged.removeListener(onStorageChanged);
    document.removeEventListener(DISPOSE_EVENT, dispose);
    controller?.stop();
    controller = null;
    ball?.dispose();
    ball = null;
    preferenceNotice?.remove();
    preferenceNotice = null;
    if (globalThis.__triloaController?.dispose === dispose) delete globalThis.__triloaController;
  }
  globalThis.__triloaController = { dispose };
  document.addEventListener(DISPOSE_EVENT, dispose);
  chrome.storage.onChanged.addListener(onStorageChanged);
  const initialRevisions = new Map(revisions);
  void chrome.storage.local.get(keys).then(settings => {
    if (!active) return;
    for (const key of keys) {
      if (initialRevisions.get(key) === revisions.get(key)) values[key] = normalizePreference(key, settings[key]);
    }
    renderPreferences();
  }).catch(error => {
    if (!active) return;
    preferenceError = `无法读取设置，请刷新网页重试：${error instanceof Error ? error.message : String(error)}`;
    renderPreferences();
  });

  function createInlineTranslation() {
    const modelCache = new globalThis.TriloaModelCache(CACHE_LIMIT);
    const cache = modelCache.translations;
    const inFlight = modelCache.inFlight;
    const retryAt = modelCache.retryAt;
    const entries = new Map();
    let visibleEntries = [];
    let lastError = "";
    let modelError = "";
    let checkingModel = false;
    let timer = 0;
    let requesting = false;
    let active = true;

    const notice = document.createElement("div");
    notice.setAttribute("data-triloa-owned", "status");
    notice.style.cssText = "position:fixed;bottom:16px;right:16px;z-index:2147483647;max-width:min(360px,90vw);";
    const shadow = notice.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = "div{background:#FFFFFF;color:#223047;border:1px solid #D9E0E9;border-radius:12px;padding:12px 16px;font:14px/1.5 system-ui;box-shadow:0 4px 20px #22304720}button{margin-top:8px;padding:6px 12px;border:1px solid #D9E0E9;border-radius:8px;background:#F5F7FA;color:#356AC3;cursor:pointer}button:focus-visible{outline:2px solid #356AC3;outline-offset:2px}[hidden]{display:none}";
    const box = document.createElement("div");
    box.setAttribute("role", "status");
    const message = document.createElement("span");
    const retry = document.createElement("button");
    retry.textContent = "重试";
    retry.addEventListener("click", () => {
      retryAt.clear();
      lastError = "";
      void syncModel();
      scheduleRefresh(0);
    });
    box.append(message, document.createElement("br"), retry);
    shadow.append(style, box);
    notice.hidden = true;
    document.documentElement.appendChild(notice);

    function normalize(text) {
      return text.normalize("NFKC").replace(/\s+/g, " ").trim();
    }

    function sourceText(element) {
      const copy = element.cloneNode(true);
      let excluded = `${OWN}, script, style, noscript, code, pre, textarea, button, select, input`;
      // A list item can contain its own paragraph or nested list. Read only its
      // direct prose; the child paragraphs/list items are translated separately.
      if (element.tagName === "LI") excluded += `, ul, ol, ${SELECTOR}`;
      for (const node of copy.querySelectorAll(excluded)) node.remove();
      return normalize(copy.textContent || "");
    }

    function isEnglishOrJapanese(element, text) {
      const lang = (element.closest("[lang]")?.getAttribute("lang") || document.documentElement.lang || "").toLowerCase();
      const shortBlock = element.tagName !== "P";
      if (text.length < (shortBlock ? 2 : 8)) return false;
      if (/[\u3040-\u30ff\u31f0-\u31ff]/u.test(text) || /^ja(?:-|$)/.test(lang)) return true;
      if (/^(zh|ko)(?:-|$)/.test(lang)) return false;
      const words = text.toLowerCase().match(/[a-z]+(?:'[a-z]+)?/g) || [];
      const allLetters = (text.match(/\p{L}/gu) || []).length;
      if (!allLetters || words.join("").length / allLetters < 0.68) return false;
      if (/^en(?:-|$)/.test(lang) || (shortBlock && words.length)) return true;
      if (words.length < 5) return false;
      return words.filter(word => ENGLISH_STOP_WORDS.has(word)).length >= (words.length >= 12 ? 2 : 1);
    }

    function isVisible(element) {
      if (element.closest(SKIP)) return false;
      const rect = element.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2 || rect.bottom < -160 || rect.top > window.innerHeight + 160 || rect.right <= 0 || rect.left >= window.innerWidth) return false;
      const computed = window.getComputedStyle(element);
      return computed.display !== "none" && computed.visibility !== "hidden" && Number(computed.opacity || 1) > 0;
    }

    function removeEntry(entry) {
      entry.node?.remove();
      entries.delete(entry.source);
    }

    function collectVisible() {
      for (const entry of entries.values()) {
        if (!entry.source.isConnected || entry.source.closest(SKIP) || sourceText(entry.source) !== entry.text) removeEntry(entry);
      }
      const visible = [];
      for (const source of document.querySelectorAll(SELECTOR)) {
        if (!isVisible(source)) continue;
        const text = sourceText(source);
        if (text.length > MAX_TEXT_LENGTH || !isEnglishOrJapanese(source, text)) continue;
        let entry = entries.get(source);
        if (!entry) {
          entry = { source, text, node: null, output: null, translation: null };
          entries.set(source, entry);
        }
        visible.push(entry);
        if (visible.length >= MAX_BLOCKS) break;
      }
      // Bound DOM and bookkeeping on infinite-scroll pages as well as the cache.
      const current = new Set(visible);
      for (const entry of entries.values()) {
        if (entries.size <= CACHE_LIMIT) break;
        if (!current.has(entry)) removeEntry(entry);
      }
      return visible;
    }

    function insertTranslation(entry, translation) {
      if (!entry.node?.isConnected) {
        entry.node = document.createElement("span");
        entry.node.setAttribute("data-triloa-owned", "translation");
        entry.node.setAttribute("lang", "zh-Hans");
        entry.node.setAttribute("aria-label", "中文译文");
        entry.node.style.cssText = "display:block;box-sizing:border-box;margin:.35em 0 .8em;max-width:100%;";
        const root = entry.node.attachShadow({ mode: "open" });
        const css = document.createElement("style");
        css.textContent = ":host{display:block}span{display:block;white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;color:inherit;line-height:1.65}";
        entry.output = document.createElement("span");
        root.append(css, entry.output);
      }
      const computed = window.getComputedStyle(entry.source);
      for (const name of ["fontFamily", "fontSize", "fontWeight", "textAlign", "color"]) entry.node.style[name] = computed[name];
      if (entry.output.textContent !== translation) entry.output.textContent = translation;
      entry.translation = translation;
      if (entry.source.tagName === "LI") {
        const nested = Array.from(entry.source.children).find(child => ["UL", "OL", "P", "H1", "H2", "H3", "H4", "H5", "H6"].includes(child.tagName));
        if (entry.node.parentNode !== entry.source || (nested && entry.node.nextSibling !== nested)) entry.source.insertBefore(entry.node, nested || null);
      } else if (entry.source.nextSibling !== entry.node) {
        entry.source.insertAdjacentElement("afterend", entry.node);
      }
    }

    function render() {
      if (!active) return;
      const error = modelError || lastError;
      notice.hidden = !error;
      if (message.textContent !== error) message.textContent = error;
      for (const entry of entries.values()) {
        if (!entry.source.isConnected) { removeEntry(entry); continue; }
        const result = cache.get(entry.text);
        if (typeof result === "string" && result.trim()) insertTranslation(entry, result);
        else { entry.node?.remove(); entry.node = null; entry.output = null; entry.translation = null; }
      }
    }

    async function requestTranslations(texts) {
      if (!active || requesting) return;
      requesting = true;
      let generation = modelCache.start(texts);
      try {
        const response = await chrome.runtime.sendMessage({ type: "triloa:translate", texts });
        if (!active || generation !== modelCache.generation) return;
        if (!response?.ok || !Array.isArray(response.translations) || response.translations.length !== texts.length || response.translations.some(value => typeof value !== "string")) {
          throw new Error(response?.error || "本地翻译服务返回了无效响应。");
        }
        if (modelCache.setModel(response.modelId)) generation = modelCache.generation;
        for (let index = 0; index < texts.length; index++) {
          modelCache.remember(texts[index], response.translations[index], generation);
          retryAt.delete(texts[index]);
        }
        lastError = "";
        modelError = "";
      } catch (error) {
        if (!active || generation !== modelCache.generation) return;
        lastError = error instanceof Error ? error.message : "本地翻译服务发生未知错误。";
        const nextRetry = Date.now() + RETRY_DELAY_MS;
        for (const text of texts) retryAt.set(text, nextRetry);
        while (retryAt.size > CACHE_LIMIT) retryAt.delete(retryAt.keys().next().value);
      } finally {
        requesting = false;
        modelCache.finish(texts, generation);
        if (active) { render(); scheduleRefresh(220); }
      }
    }

    async function syncModel() {
      if (!active || checkingModel) return;
      checkingModel = true;
      const generation = modelCache.generation;
      try {
        const response = await chrome.runtime.sendMessage({ type: "triloa:model" });
        if (!active || generation !== modelCache.generation) return;
        if (!response?.ok) throw new Error(response?.error || "无法读取当前翻译模型，请保持 Triloa 桌面程序运行。");
        const recovered = Boolean(modelError);
        const changed = modelCache.setModel(response.modelId);
        modelError = "";
        if (changed) lastError = "";
        if (changed || recovered) { render(); scheduleRefresh(0); }
        else if (lastError) scheduleRefresh(0);
      } catch (error) {
        if (!active || generation !== modelCache.generation) return;
        modelError = error instanceof Error ? error.message : "无法连接本地翻译服务。";
        render();
      } finally { checkingModel = false; }
    }

    function refresh() {
      if (!active) return;
      visibleEntries = collectVisible();
      render();
      const now = Date.now();
      const unseen = Array.from(new Set(visibleEntries.map(entry => entry.text)))
        .filter(text => !cache.has(text) && !inFlight.has(text) && (retryAt.get(text) || 0) <= now);
      if (modelCache.modelId === null) void syncModel();
      else if (unseen.length && !requesting && !modelError) void requestTranslations(unseen);
    }

    function scheduleRefresh(delay = 220) {
      if (!active) return;
      window.clearTimeout(timer);
      timer = window.setTimeout(refresh, delay);
    }
    function owned(node) {
      const element = node.nodeType === 1 ? node : node.parentElement;
      return Boolean(element?.closest(OWN));
    }
    const onScroll = () => scheduleRefresh();
    const onResize = () => scheduleRefresh();
    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    window.addEventListener("resize", onResize, { passive: true });
    const observer = new MutationObserver(mutations => {
      const changed = mutations.some(mutation => {
        if (owned(mutation.target)) return false;
        if (mutation.type !== "childList") return true;
        return [...mutation.addedNodes, ...mutation.removedNodes].some(node => !owned(node));
      });
      if (changed) scheduleRefresh(350);
    });
    observer.observe(document.documentElement, { subtree: true, childList: true, characterData: true,
      attributes: true, attributeFilter: ["class", "style", "hidden", "lang", "aria-hidden", "contenteditable"] });
    const modelTimer = window.setInterval(syncModel, 2000);
    scheduleRefresh(120);
    return {
      stop() {
        active = false;
        window.clearTimeout(timer);
        window.clearInterval(modelTimer);
        observer.disconnect();
        document.removeEventListener("scroll", onScroll, true);
        window.removeEventListener("resize", onResize);
        for (const entry of entries.values()) entry.node?.remove();
        entries.clear();
        notice.remove();
      }
    };
  }
})();
