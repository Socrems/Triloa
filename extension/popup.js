const siteLabel = document.getElementById("site");
const enabledSwitch = document.getElementById("enabled");
const statusLabel = document.getElementById("status");

function setStatus(message, error = false) {
  statusLabel.textContent = message;
  statusLabel.classList.toggle("error", error);
}

async function initialize() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const url = tab?.url ? new URL(tab.url) : null;
    if (!url || !["http:", "https:"].includes(url.protocol)) {
      siteLabel.textContent = "当前页面不支持网页翻译";
      setStatus("请打开普通网页；Edge 内置页面无法使用此扩展。");
      return;
    }

    const key = `triloa:enabled:${url.origin}`;
    siteLabel.textContent = url.host;
    const settings = await chrome.storage.local.get(key);
    enabledSwitch.checked = settings[key] === true;
    enabledSwitch.disabled = false;
    setStatus(enabledSwitch.checked
      ? "已在此网站开启。可拖动翻译窗标题栏，拖动右下角调整大小。"
      : "此网站已关闭；其他网站的设置互不影响。");

    enabledSwitch.addEventListener("change", async () => {
      enabledSwitch.disabled = true;
      try {
        await chrome.storage.local.set({ [key]: enabledSwitch.checked });
        setStatus(enabledSwitch.checked
          ? "已开启。若翻译窗未出现，请刷新网页并检查 Edge 的网站访问权限。"
          : "此网站已关闭；其他网站的设置互不影响。");
      } catch (error) {
        enabledSwitch.checked = !enabledSwitch.checked;
        setStatus(`保存设置失败：${error instanceof Error ? error.message : String(error)}`, true);
      } finally {
        enabledSwitch.disabled = false;
      }
    });
  } catch (error) {
    siteLabel.textContent = "无法读取当前网站";
    setStatus(error instanceof Error ? error.message : String(error), true);
  }
}

void initialize();
