"""Desktop single-instance activation, tray and Windows global shortcuts."""
import ctypes
import sys
from hashlib import sha256
from PySide6.QtCore import QAbstractNativeEventFilter, QLockFile, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from . import preferences
from .paths import DATA

DEFAULTS = {'select': 'Ctrl+Alt+T', 'clipboard': 'Ctrl+Alt+C', 'subtitles': 'Ctrl+Alt+S'}

class InstanceGuard:
    def __init__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        self.name = 'Triloa-' + sha256(str(DATA.resolve()).casefold().encode()).hexdigest()[:16]
        self.lock = QLockFile(str(DATA / 'desktop.lock'))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer()
        self.callback = None
        self.server.newConnection.connect(self._activate)

    def acquire(self):
        if not self.lock.tryLock(0):
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            socket.waitForConnected(1500)
            socket.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise RuntimeError('无法创建本地窗口通信服务')
        return True

    def _activate(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.close()
            socket.deleteLater()
        if self.callback:
            self.callback()

    def close(self):
        self.server.close()
        self.lock.unlock()


def decode_shortcut(text):
    sequence = QKeySequence(text, QKeySequence.PortableText)
    if sequence.count() != 1:
        raise ValueError('请使用单个组合键')
    parts = sequence.toString(QKeySequence.PortableText).split('+')
    key = parts.pop().upper()
    modifiers = 0
    for part in parts:
        if part not in ('Ctrl', 'Alt', 'Shift', 'Meta'):
            raise ValueError('不支持此修饰键')
        modifiers |= {'Alt': 1, 'Ctrl': 2, 'Shift': 4, 'Meta': 8}[part]
    if not modifiers:
        raise ValueError('快捷键需包含 Ctrl、Alt、Shift 或 Win')
    if len(key) == 1 and key.isascii() and key.isalnum():
        code = ord(key)
    elif key.startswith('F') and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        code = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError('请使用字母、数字或功能键')
    return modifiers | 0x4000, code


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.registered = {}
        self.callbacks = {'select': window.select_region, 'clipboard': window.translate_clipboard, 'subtitles': window.toggle_subtitles}
        QApplication.instance().installNativeEventFilter(self)

    def unregister(self):
        if sys.platform == 'win32':
            for identifier in self.registered:
                ctypes.windll.user32.UnregisterHotKey(None, identifier)
        self.registered.clear()

    def register(self):
        self.unregister()
        failures = []
        if sys.platform != 'win32':
            return ['全局快捷键仅支持 Windows']
        for identifier, (key, default) in enumerate(DEFAULTS.items(), 0x4100):
            text = preferences.get('hotkey.' + key, default)
            if not text:
                continue
            try:
                modifiers, code = decode_shortcut(text)
                if not ctypes.windll.user32.RegisterHotKey(None, identifier, modifiers, code):
                    raise ValueError('已被其他程序或快捷键占用')
                self.registered[identifier] = self.callbacks[key]
            except (ValueError, TypeError) as exc:
                failures.append(f'{text}：{exc}')
        return failures

    def nativeEventFilter(self, event_type, message):
        if sys.platform == 'win32' and bytes(event_type) in (b'windows_generic_MSG', b'windows_dispatcher_MSG'):
            from ctypes.wintypes import MSG
            msg = MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self.registered:
                QTimer.singleShot(0, self.registered[msg.wParam])
                return True, 0
        return False, 0


def install_tray(window):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return
    tray = QSystemTrayIcon(QApplication.windowIcon(), window)
    tray.setToolTip('Triloa · 离线翻译')
    menu = QMenu(window)
    for text, callback in (('打开主窗口', window._restore_main_window), ('框选翻译', window.select_region), ('翻译剪贴板', window.translate_clipboard), ('显示 / 隐藏字幕', window.toggle_subtitles), ('隐藏主窗口', window.hide), ('退出 Triloa', window.close)):
        menu.addAction(text, callback)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: window._restore_main_window() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
    tray.show()
    window.tray = tray
    window.tray_menu = menu
