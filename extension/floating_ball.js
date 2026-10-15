(() => {
  "use strict";
  // View and pointer handling only. content.js owns preferences and translation.
  globalThis.TriloaFloatingBall = function createFloatingBall(actions) {
    const SIZE = 44;
    let state = {};
    let active = true;
    let expanded = false;
    let settingsOpen = false;
    let leaveTimer = 0;
    let drag = null;
    let deferredPosition = null;
    let suppressClickUntil = 0;
    const listeners = [];
    const host = document.createElement("div");
    host.setAttribute("data-triloa-owned", "ball");
    host.style.cssText = "all:initial!important;position:fixed!important;z-index:2147483647!important;width:44px!important;height:44px!important;display:block!important;";
    const root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = `
      *{box-sizing:border-box} [hidden]{display:none!important}
      .wrap{position:relative;width:44px;height:44px;color:#223047;font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
      button,input{font:inherit}button{cursor:pointer;color:#223047;border:1px solid #D9E0E9;background:#FFFFFF;border-radius:12px;padding:8px 12px}
      button:hover{background:#F5F7FA}button:focus-visible,input:focus-visible{outline:3px solid #356AC3;outline-offset:3px}button:disabled,input:disabled{cursor:wait;opacity:.6}
      .ball{width:44px;height:44px;padding:0;border-radius:50%;border:1px solid #356AC3;background:#FFFFFF;color:#356AC3;font-size:20px;font-weight:650;box-shadow:0 4px 16px #22304724;touch-action:none;user-select:none;transition:background .15s,box-shadow .15s}
      .ball[aria-pressed=true]{background:#356AC3;color:#FFFFFF}.ball:hover{box-shadow:0 5px 20px #22304735}.ball[aria-pressed=true]:hover{background:#2D5DAE}
      .tools{position:absolute;top:0;height:44px;display:flex;align-items:center;gap:6px;padding:4px;background:#FFFFFF;border:1px solid #D9E0E9;border-radius:14px;box-shadow:0 4px 18px #22304718}
      .tools button{height:34px;padding:4px 10px;white-space:nowrap;border:0;border-radius:9px;font-size:12px}
      .panel{position:absolute;width:260px;max-width:calc(100vw - 80px);padding:16px;background:#FFFFFF;border:1px solid #D9E0E9;border-radius:16px;box-shadow:0 6px 28px #22304724;max-height:calc(100vh - 24px);overflow:auto}
      .right .tools,.right .panel{right:54px}.left .tools,.left .panel{left:54px}
      h2{font-size:15px;margin:0 0 14px}p{margin:10px 0 0;color:#637187;font-size:12px}.row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}.row input{accent-color:#356AC3;width:18px;height:18px}.reset{width:100%;background:#F5F7FA}.close{float:right;padding:0 5px;border:0;font-size:18px;line-height:24px}.hint{position:absolute;top:52px;white-space:nowrap;background:#FFFFFF;border:1px solid #D9E0E9;border-radius:8px;padding:5px 8px;font-size:12px;color:#637187}.right .hint{right:0}.left .hint{left:0}
      @media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
    `;
    function element(tag, text, className) {
      const node = document.createElement(tag);
      if (text) node.textContent = text;
      if (className) node.className = className;
      return node;
    }
    function button(text, label, className) {
      const node = element("button", text, className);
      node.type = "button";
      node.setAttribute("aria-label", label);
      return node;
    }
    const wrap = element("div", "", "wrap right");
    const ball = button("译", "在此网站启用翻译", "ball");
    const tools = element("div", "", "tools");
    tools.setAttribute("role", "group");
    tools.setAttribute("aria-label", "Triloa 悬浮球操作");
    const settings = button("设置", "悬浮球设置");
    settings.setAttribute("aria-expanded", "false");
    settings.setAttribute("aria-controls", "triloa-ball-settings");
    const hide = button("隐藏", "在此网站隐藏悬浮球");
    tools.append(settings, hide);
    const panel = element("section", "", "panel");
    panel.id = "triloa-ball-settings";
    panel.setAttribute("aria-label", "悬浮球设置");
    const close = button("×", "关闭悬浮球设置", "close");
    const heading = element("h2", "悬浮球设置");
    const row = element("label", "", "row");
    row.append(element("span", "在所有网站显示悬浮球"));
    const globalSwitch = element("input");
    globalSwitch.type = "checkbox";
    globalSwitch.setAttribute("role", "switch");
    row.append(globalSwitch);
    const reset = button("恢复默认位置", "恢复默认位置", "reset");
    panel.append(close, heading, row, reset, element("p", "点击悬浮球切换本站翻译；拖动可调整位置。隐藏后可从扩展弹窗恢复。"));
    const hint = element("div", "", "hint");
    hint.setAttribute("role", "status");
    wrap.append(ball, tools, panel, hint);
    root.append(style, wrap);
    document.documentElement.append(host);

    function listen(target, type, handler, options) {
      target.addEventListener(type, handler, options);
      listeners.push(() => target.removeEventListener(type, handler, options));
    }
    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
    function bounds() {
      const width = window.innerWidth;
      const height = window.innerHeight;
      const xMargin = Math.min(16, Math.max(0, (width - SIZE) / 2));
      const yMargin = Math.min(16, Math.max(0, (height - SIZE) / 2));
      return { minX: xMargin, maxX: Math.max(xMargin, width - SIZE - xMargin),
        minY: yMargin, maxY: Math.max(yMargin, height - SIZE - yMargin) };
    }
    function coords(position) {
      const b = bounds();
      return { x: position.side === "left" ? b.minX : b.maxX, y: b.minY + (b.maxY - b.minY) * position.yRatio };
    }
    function place(x, y) {
      host.style.setProperty("left", `${x}px`, "important");
      host.style.setProperty("top", `${y}px`, "important");
      if (settingsOpen) {
        const height = panel.getBoundingClientRect().height || 220;
        const min = 12 - y;
        const max = window.innerHeight - 12 - y - height;
        panel.style.top = `${clamp((SIZE - height) / 2, Math.min(min, max), Math.max(min, max))}px`;
      }
    }
    function render() {
      if (!active) return;
      const position = state.position || { side: "right", yRatio: .5 };
      wrap.className = `wrap ${drag?.moved ? (drag.x < (window.innerWidth - SIZE) / 2 ? "left" : "right") : position.side}`;
      ball.setAttribute("aria-pressed", String(state.enabled === true));
      ball.setAttribute("aria-label", state.enabled ? "显示原文，关闭本站翻译" : "在此网站启用翻译");
      ball.title = state.upgrade ? "请刷新网页完成扩展升级" : (state.enabled ? "显示原文 · 可拖动" : "翻译此网站 · 可拖动");
      ball.disabled = Boolean(state.pending?.enabled || state.pending?.position);
      hide.disabled = Boolean(state.pending?.hidden);
      globalSwitch.checked = state.ballEnabled === true;
      globalSwitch.disabled = Boolean(state.pending?.ball);
      reset.disabled = Boolean(state.pending?.position);
      settings.setAttribute("aria-expanded", String(settingsOpen));
      tools.hidden = !expanded || settingsOpen || Boolean(drag?.moved);
      panel.hidden = !settingsOpen || Boolean(drag?.moved);
      hint.textContent = state.upgrade ? "请刷新网页完成升级" : "";
      hint.hidden = !state.upgrade || !expanded || settingsOpen;
      const p = drag?.moved ? { x: drag.x, y: drag.y } : coords(position);
      place(p.x, p.y);
    }
    function cancelLeave() { window.clearTimeout(leaveTimer); }
    function deferClose() {
      cancelLeave();
      leaveTimer = window.setTimeout(() => {
        if (!root.activeElement && !settingsOpen && !drag) { expanded = false; render(); }
      }, 220);
    }
    function closeSettings() {
      settingsOpen = false;
      render();
      settings.focus();
    }
    listen(wrap, "pointerenter", () => { cancelLeave(); expanded = true; render(); });
    listen(wrap, "pointerleave", deferClose);
    listen(root, "focusin", () => { cancelLeave(); expanded = true; render(); });
    listen(root, "focusout", deferClose);
    listen(root, "keydown", event => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      cancelLeave();
      settingsOpen = false;
      ball.focus();
      expanded = false;
      render();
    });
    listen(ball, "click", event => {
      if (Date.now() < suppressClickUntil && (event.detail !== 0 || event.pointerType)) {
        event.preventDefault();
        suppressClickUntil = 0;
        return;
      }
      void actions.onToggle();
    });
    listen(settings, "click", () => { settingsOpen = true; render(); globalSwitch.focus(); });
    listen(close, "click", closeSettings);
    listen(hide, "click", () => { void actions.onHide(); });
    listen(globalSwitch, "change", () => { void actions.onGlobalChange(globalSwitch.checked); });
    listen(reset, "click", () => { void actions.onReset(); });
    listen(ball, "pointerdown", event => {
      if (event.isPrimary === false || event.button !== 0 || drag || state.pending?.position) return;
      const p = coords(state.position);
      drag = { id: event.pointerId, startX: event.clientX, startY: event.clientY, x: p.x, y: p.y,
        originX: p.x, originY: p.y, moved: false };
      deferredPosition = null;
      try { ball.setPointerCapture(event.pointerId); } catch { /* Page may be detaching. */ }
    });
    listen(ball, "pointermove", event => {
      if (!drag || event.pointerId !== drag.id) return;
      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;
      if (!drag.moved && Math.hypot(dx, dy) < 6) return;
      event.preventDefault();
      drag.moved = true;
      cancelLeave();
      const b = bounds();
      drag.x = clamp(drag.originX + dx, b.minX, b.maxX);
      drag.y = clamp(drag.originY + dy, b.minY, b.maxY);
      render();
    });
    function finishDrag(event, cancelled = false) {
      if (!drag || event.pointerId !== drag.id) return;
      const finished = drag;
      drag = null;
      try { ball.releasePointerCapture(finished.id); } catch { /* Already released. */ }
      if (cancelled || !finished.moved) {
        if (deferredPosition) state = { ...state, position: deferredPosition };
      } else {
        suppressClickUntil = Date.now() + 600;
        const b = bounds();
        const position = { side: finished.x + SIZE / 2 < window.innerWidth / 2 ? "left" : "right",
          yRatio: b.maxY === b.minY ? .5 : clamp((finished.y - b.minY) / (b.maxY - b.minY), 0, 1) };
        state = { ...state, position };
        void actions.onPosition(position);
      }
      deferredPosition = null;
      render();
    }
    listen(ball, "pointerup", event => finishDrag(event));
    listen(ball, "pointercancel", event => finishDrag(event, true));
    listen(ball, "lostpointercapture", event => finishDrag(event, true));
    listen(window, "resize", () => {
      if (drag) {
        const b = bounds();
        drag.x = clamp(drag.x, b.minX, b.maxX);
        drag.y = clamp(drag.y, b.minY, b.maxY);
      }
      render();
    });
    return {
      update(next) {
        if (drag && next.position) {
          deferredPosition = next.position;
          next = { ...next, position: state.position };
        }
        state = { ...next };
        render();
      },
      dispose() {
        active = false;
        cancelLeave();
        for (const remove of listeners) remove();
        drag = null;
        host.remove();
      }
    };
  };
})();

