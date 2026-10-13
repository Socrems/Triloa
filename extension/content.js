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

  if (!document.documentElement || globalThis.__triloaViewportTranslationLoaded) return;
  globalThis.__triloaViewportTranslationLoaded = true;
  const ENABLED_KEY = `triloa:enabled:${location.origin}`;
  let controller = null;
  let settingsRevision = 0;

  function setEnabled(enabled) {
    if (enabled && !controller) controller = createInlineTranslation();
    if (!enabled && controller) {
      controller.stop();
      controller = null;
    }
  }

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local" || !Object.hasOwn(changes, ENABLED_KEY)) return;
    settingsRevision++;
    setEnabled(changes[ENABLED_KEY].newValue === true);
  });
  const initialRevision = settingsRevision;
  void chrome.storage.local.get(ENABLED_KEY).then((settings) => {
    if (settingsRevision === initialRevision) setEnabled(settings[ENABLED_KEY] === true);
  }).catch((error) => console.warn("Triloa 无法读取网站开关：", error));

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
    style.textContent = "div{background:#fff;color:#722f25;border:1px solid #ead0c8;border-radius:10px;padding:12px;font:14px/1.5 system-ui;box-shadow:0 4px 20px #0002}button{margin-top:8px;cursor:pointer} [hidden]{display:none}";
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
