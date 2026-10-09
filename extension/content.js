(() => {
  const HOST_ID = "triloa-viewport-translation";
  const MAX_PARAGRAPHS = 32;
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
  const PANEL_KEY = `triloa:panel:${location.origin}`;
  let controller = null;
  let settingsRevision = 0;

  function setEnabled(enabled) {
    if (enabled && !controller) controller = createPanel();
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

  function createPanel() {
    document.getElementById(HOST_ID)?.remove();

    const modelCache = new globalThis.TriloaModelCache(CACHE_LIMIT);
    const cache = modelCache.translations;
    const inFlight = modelCache.inFlight;
    const retryAt = modelCache.retryAt;
    let visibleEntries = [];
    let lastError = "";
    let modelError = "";
    let checkingModel = false;
    let timer = 0;
    let active = true;
    let locked = false;
    let geometry = null;

    const host = document.createElement("div");
    host.id = HOST_ID;
    document.documentElement.appendChild(host);
    const shadow = host.attachShadow({ mode: "open" });

    const style = document.createElement("style");
    style.textContent = `
      :host { all: initial; }
      *, *::before, *::after { box-sizing: border-box; }
      .panel {
        position: fixed; z-index: 2147483647; display: flex; flex-direction: column;
        overflow: hidden; color: #172033;
        background: #fff; border: 1px solid #d8deea; border-radius: 14px;
        box-shadow: 0 10px 36px rgba(20, 32, 55, .24);
        font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
      }
      .panel[hidden], .reopen[hidden] { display: none !important; }
      .header { display: flex; align-items: center; gap: 7px; padding: 10px 12px; border-bottom: 1px solid #e8ebf1; cursor: move; user-select: none; touch-action: none; }
      .panel.locked .header { cursor: default; }
      .title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 700; font-size: 14px; }
      .count { flex: none; color: #69758b; font-size: 12px; font-weight: 500; }
      button { border: 0; cursor: pointer; font: inherit; }
      .control { flex: none; height: 28px; border-radius: 8px; color: #58647a; background: #f1f3f7; }
      .control:hover { background: #e6eaf1; }
      .lock { padding: 0 7px; font-size: 12px; }
      .close { width: 28px; font-size: 18px; line-height: 1; }
      .status { padding: 8px 14px; color: #526079; background: #f7f8fb; font-size: 12px; }
      .status.error { color: #8b1c22; background: #fff0ef; }
      .list { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; }
      .card { padding: 11px 14px; border-top: 1px solid #edf0f5; }
      .source { display: -webkit-box; overflow: hidden; color: #6c778c; font-size: 11px; line-height: 1.4; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow-wrap: anywhere; }
      .translation { margin-top: 5px; color: #172033; font-size: 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
      .pending { color: #78839a; }
      .empty { padding: 16px 14px; color: #66728a; font-size: 13px; }
      .resize-handle { position: absolute; right: 2px; bottom: 2px; width: 19px; height: 19px; background: transparent; cursor: nwse-resize; touch-action: none; }
      .resize-handle::after { content: ""; position: absolute; right: 3px; bottom: 3px; width: 10px; height: 10px; border-right: 2px solid #8190a7; border-bottom: 2px solid #8190a7; }
      .panel.locked .resize-handle { display: none; }
      .reopen { position: fixed; right: 20px; bottom: 20px; z-index: 2147483647; padding: 10px 14px; color: #fff; background: #2457c5; border-radius: 999px; box-shadow: 0 5px 20px rgba(20, 32, 55, .24); font-weight: 650; }
      @media (max-width: 520px) { .reopen { right: 10px; bottom: 10px; } }
    `;
    shadow.appendChild(style);

    const panel = document.createElement("section");
    panel.className = "panel";
    panel.setAttribute("aria-label", "网页视口中文翻译");
    panel.hidden = true;
    const header = document.createElement("div");
    header.className = "header";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = "当前视口 · 中文翻译";
    const count = document.createElement("span");
    count.className = "count";
    const lockButton = document.createElement("button");
    lockButton.className = "control lock";
    lockButton.type = "button";
    const closeButton = document.createElement("button");
    closeButton.className = "control close";
    closeButton.type = "button";
    closeButton.setAttribute("aria-label", "收起翻译面板");
    closeButton.title = "收起翻译面板";
    closeButton.textContent = "×";
    header.append(title, count, lockButton, closeButton);
    const status = document.createElement("div");
    status.className = "status";
    const list = document.createElement("div");
    list.className = "list";
    const resizeHandle = document.createElement("button");
    resizeHandle.className = "resize-handle";
    resizeHandle.type = "button";
    resizeHandle.setAttribute("aria-label", "拖动或用方向键调整翻译窗大小");
    resizeHandle.title = "拖动以调整大小";
    panel.append(header, status, list, resizeHandle);
    const reopenButton = document.createElement("button");
    reopenButton.className = "reopen";
    reopenButton.type = "button";
    reopenButton.textContent = "显示翻译";
    reopenButton.hidden = true;
    shadow.append(panel, reopenButton);

    const MARGIN = 8;
    const MIN_WIDTH = 260;
    const MIN_HEIGHT = 170;

    function clamp(value, minimum, maximum) {
      return Math.min(Math.max(value, minimum), maximum);
    }

    function normalizeGeometry(value) {
      const maxWidth = Math.max(1, window.innerWidth - MARGIN * 2);
      const maxHeight = Math.max(1, window.innerHeight - MARGIN * 2);
      const width = clamp(
        Number.isFinite(value?.width) ? Math.round(value.width) : 390,
        Math.min(MIN_WIDTH, maxWidth), maxWidth
      );
      const height = clamp(
        Number.isFinite(value?.height) ? Math.round(value.height) : Math.min(500, Math.round(window.innerHeight * 0.52)),
        Math.min(MIN_HEIGHT, maxHeight), maxHeight
      );
      const defaultX = window.innerWidth - width - 20;
      const defaultY = window.innerHeight - height - 20;
      return {
        x: clamp(Number.isFinite(value?.x) ? Math.round(value.x) : defaultX, MARGIN, Math.max(MARGIN, window.innerWidth - width - MARGIN)),
        y: clamp(Number.isFinite(value?.y) ? Math.round(value.y) : defaultY, MARGIN, Math.max(MARGIN, window.innerHeight - height - MARGIN)),
        width,
        height
      };
    }

    function applyGeometry(value) {
      geometry = normalizeGeometry(value);
      panel.style.left = `${geometry.x}px`;
      panel.style.top = `${geometry.y}px`;
      panel.style.width = `${geometry.width}px`;
      panel.style.height = `${geometry.height}px`;
    }

    function updateLock() {
      panel.classList.toggle("locked", locked);
      lockButton.textContent = locked ? "已固定" : "固定";
      lockButton.setAttribute("aria-pressed", String(locked));
      lockButton.setAttribute("aria-label", locked ? "解除固定，允许移动和缩放" : "固定位置和大小");
      lockButton.title = locked ? "点击解锁位置和大小" : "点击锁定位置和大小";
    }

    function savePanel() {
      if (!active || !geometry) return;
      void chrome.storage.local.set({ [PANEL_KEY]: { ...geometry, locked } })
        .catch((error) => console.warn("Triloa 无法保存翻译窗位置：", error));
    }

    applyGeometry(null);
    updateLock();
    void chrome.storage.local.get(PANEL_KEY)
      .then((settings) => {
        if (!active) return;
        const saved = settings[PANEL_KEY];
        locked = saved?.locked === true;
        applyGeometry(saved);
        updateLock();
      })
      .catch((error) => console.warn("Triloa 无法读取翻译窗位置：", error))
      .finally(() => { if (active) panel.hidden = false; });

    let dragStart = null;
    header.addEventListener("pointerdown", (event) => {
      if (locked || event.button !== 0 || event.target.closest("button")) return;
      event.preventDefault();
      dragStart = { id: event.pointerId, clientX: event.clientX, clientY: event.clientY, ...geometry };
      header.setPointerCapture(event.pointerId);
    });
    header.addEventListener("pointermove", (event) => {
      if (!dragStart || event.pointerId !== dragStart.id) return;
      applyGeometry({
        ...geometry,
        x: dragStart.x + event.clientX - dragStart.clientX,
        y: dragStart.y + event.clientY - dragStart.clientY
      });
    });
    function finishDrag(event) {
      if (!dragStart || event.pointerId !== dragStart.id) return;
      dragStart = null;
      savePanel();
    }
    header.addEventListener("pointerup", finishDrag);
    header.addEventListener("pointercancel", finishDrag);

    let resizeStart = null;
    resizeHandle.addEventListener("pointerdown", (event) => {
      if (locked || event.button !== 0) return;
      event.preventDefault();
      resizeStart = { id: event.pointerId, clientX: event.clientX, clientY: event.clientY, ...geometry };
      resizeHandle.setPointerCapture(event.pointerId);
    });
    resizeHandle.addEventListener("pointermove", (event) => {
      if (!resizeStart || event.pointerId !== resizeStart.id) return;
      const maxWidth = Math.max(1, window.innerWidth - MARGIN - resizeStart.x);
      const maxHeight = Math.max(1, window.innerHeight - MARGIN - resizeStart.y);
      applyGeometry({
        ...geometry,
        width: clamp(resizeStart.width + event.clientX - resizeStart.clientX, Math.min(MIN_WIDTH, maxWidth), maxWidth),
        height: clamp(resizeStart.height + event.clientY - resizeStart.clientY, Math.min(MIN_HEIGHT, maxHeight), maxHeight)
      });
    });
    function finishResize(event) {
      if (!resizeStart || event.pointerId !== resizeStart.id) return;
      resizeStart = null;
      savePanel();
    }
    resizeHandle.addEventListener("pointerup", finishResize);
    resizeHandle.addEventListener("pointercancel", finishResize);
    resizeHandle.addEventListener("keydown", (event) => {
      if (locked || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
      event.preventDefault();
      const widthChange = event.key === "ArrowRight" ? 10 : event.key === "ArrowLeft" ? -10 : 0;
      const heightChange = event.key === "ArrowDown" ? 10 : event.key === "ArrowUp" ? -10 : 0;
      const maxWidth = Math.max(1, window.innerWidth - MARGIN - geometry.x);
      const maxHeight = Math.max(1, window.innerHeight - MARGIN - geometry.y);
      applyGeometry({
        ...geometry,
        width: clamp(geometry.width + widthChange, Math.min(MIN_WIDTH, maxWidth), maxWidth),
        height: clamp(geometry.height + heightChange, Math.min(MIN_HEIGHT, maxHeight), maxHeight)
      });
      savePanel();
    });
    lockButton.addEventListener("click", () => {
      locked = !locked;
      updateLock();
      savePanel();
    });

    closeButton.addEventListener("click", () => {
      panel.hidden = true;
      reopenButton.hidden = false;
    });
    reopenButton.addEventListener("click", () => {
      panel.hidden = false;
      reopenButton.hidden = true;
      scheduleRefresh(0);
    });

    function normalize(text) {
      return text.normalize("NFKC").replace(/\s+/g, " ").trim();
    }

    function isEnglishOrJapanese(element, text) {
      const kana = (text.match(/[\u3040-\u30ff\u31f0-\u31ff]/gu) || []).length;
      const lang = (element.closest("[lang]")?.getAttribute("lang") || document.documentElement.lang || "").toLowerCase();
      if (text.length < 8) return false;
      if (kana >= 1 || /^ja(?:-|$)/.test(lang)) return true;
      if (/^(zh|ko)(?:-|$)/.test(lang)) return false;

      const words = text.toLowerCase().match(/[a-z]+(?:'[a-z]+)?/g) || [];
      const latinLetters = words.join("").length;
      const allLetters = (text.match(/\p{L}/gu) || []).length;
      if (words.length < 5 || !allLetters || latinLetters / allLetters < 0.68) return false;
      let stopWordCount = 0;
      for (const word of words) {
        if (ENGLISH_STOP_WORDS.has(word)) stopWordCount++;
      }
      return stopWordCount >= (words.length >= 12 ? 2 : 1);
    }

    function isVisible(element) {
      if (element.closest("nav, header, footer, aside, [role='navigation'], [aria-hidden='true'], [contenteditable='true']")) return false;
      const rect = element.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2 || rect.bottom <= 0 || rect.top >= window.innerHeight || rect.right <= 0 || rect.left >= window.innerWidth) return false;
      const computed = window.getComputedStyle(element);
      return computed.display !== "none" && computed.visibility !== "hidden" && Number(computed.opacity || 1) > 0;
    }

    function collectVisible() {
      const unique = new Map();
      for (const element of document.querySelectorAll("p")) {
        if (!isVisible(element)) continue;
        const text = normalize(element.innerText || element.textContent || "");
        if (text.length > MAX_TEXT_LENGTH || !isEnglishOrJapanese(element, text) || unique.has(text)) continue;
        unique.set(text, { text });
        if (unique.size >= MAX_PARAGRAPHS) break;
      }
      return Array.from(unique.values());
    }

    function remember(text, translation, generation) {
      modelCache.remember(text, translation, generation);
    }

    function updateStatus() {
      count.textContent = `${visibleEntries.length} 段`;
      const error = modelError || lastError;
      status.classList.toggle("error", Boolean(error));
      if (error) {
        status.textContent = error;
      } else if (inFlight.size) {
        status.textContent = `正在请求本地服务，${inFlight.size} 段翻译处理中…`;
      } else if (visibleEntries.length) {
        status.textContent = "滚动页面后自动更新 · 翻译由本地服务提供";
      } else {
        status.textContent = "当前视口没有识别到英文或日文段落";
      }
    }

    function render() {
      if (!active) return;
      updateStatus();
      list.replaceChildren();
      if (!visibleEntries.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "向下滚动到英文或日文内容，翻译会自动显示在这里。";
        list.appendChild(empty);
        return;
      }
      for (const entry of visibleEntries) {
        const card = document.createElement("article");
        card.className = "card";
        const source = document.createElement("div");
        source.className = "source";
        source.textContent = entry.text;
        const translated = document.createElement("div");
        translated.className = "translation";
        const result = cache.get(entry.text);
        if (result) {
          translated.textContent = result;
        } else if (inFlight.has(entry.text)) {
          translated.classList.add("pending");
          translated.textContent = "正在翻译…";
        } else if ((retryAt.get(entry.text) || 0) > Date.now()) {
          translated.classList.add("pending");
          translated.textContent = "本地服务暂不可用，稍后滚动页面可重试。";
        } else {
          translated.classList.add("pending");
          translated.textContent = "等待翻译…";
        }
        card.append(source, translated);
        list.appendChild(card);
      }
    }

    async function requestTranslations(texts) {
      if (!active) return;
      let generation = modelCache.start(texts);
      render();
      try {
        const response = await chrome.runtime.sendMessage({ type: "triloa:translate", texts });
        if (!active || generation !== modelCache.generation) return;
        if (!response?.ok || !Array.isArray(response.translations) || response.translations.length !== texts.length) {
          throw new Error(response?.error || "本地翻译服务返回了无效响应。");
        }
        if (modelCache.setModel(response.modelId)) {
          generation = modelCache.generation;
          scheduleRefresh(0);
        }
        for (let index = 0; index < texts.length; index++) {
          remember(texts[index], response.translations[index], generation);
          retryAt.delete(texts[index]);
        }
        lastError = "";
        modelError = "";
      } catch (error) {
        if (!active || generation !== modelCache.generation) return;
        lastError = error instanceof Error ? error.message : "本地翻译服务发生未知错误。";
        const nextRetry = Date.now() + RETRY_DELAY_MS;
        for (const text of texts) retryAt.set(text, nextRetry);
      } finally {
        if (modelCache.finish(texts, generation) && active) render();
      }
    }

    async function syncModel() {
      if (!active || checkingModel) return;
      checkingModel = true;
      const generation = modelCache.generation;
      try {
        const response = await chrome.runtime.sendMessage({ type: "triloa:model" });
        if (!active || generation !== modelCache.generation) return;
        if (!response?.ok) throw new Error(response?.error || "无法读取当前翻译模型。");
        const hadError = Boolean(modelError);
        const changed = modelCache.setModel(response.modelId);
        modelError = "";
        if (changed) {
          lastError = "";
          scheduleRefresh(0);
        } else if (hadError) {
          render();
        }
      } catch (error) {
        if (!active || generation !== modelCache.generation) return;
        modelError = error instanceof Error ? error.message : "无法读取当前翻译模型。";
        render();
      } finally {
        checkingModel = false;
      }
    }

    function refresh() {
      if (!active) return;
      visibleEntries = collectVisible();
      render();
      const now = Date.now();
      const unseen = visibleEntries
        .map((entry) => entry.text)
        .filter((text) => !cache.has(text) && !inFlight.has(text) && (retryAt.get(text) || 0) <= now);
      if (modelCache.modelId === null) void syncModel();
      else if (unseen.length) void requestTranslations(unseen);
    }

    function scheduleRefresh(delay = 220) {
      if (!active) return;
      window.clearTimeout(timer);
      timer = window.setTimeout(refresh, delay);
    }

    const onScroll = () => scheduleRefresh();
    const onWindowResize = () => {
      applyGeometry(geometry);
      scheduleRefresh();
    };
    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    window.addEventListener("resize", onWindowResize, { passive: true });
    const observer = new MutationObserver((mutations) => {
      if (mutations.some((mutation) => !host.contains(mutation.target))) scheduleRefresh(350);
    });
    observer.observe(document.documentElement, { subtree: true, childList: true, characterData: true });
    const modelTimer = window.setInterval(syncModel, 2000);
    scheduleRefresh(120);

    return {
      stop() {
        active = false;
        window.clearTimeout(timer);
        window.clearInterval(modelTimer);
        observer.disconnect();
        document.removeEventListener("scroll", onScroll, true);
        window.removeEventListener("resize", onWindowResize);
        host.remove();
      }
    };
  }
})();
