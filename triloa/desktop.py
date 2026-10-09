"""Desktop interface for screen region OCR and offline translation."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

from .diagnostics import trace
from .monitor_overlay import MonitorTranslationOverlay, set_capture_excluded

trace("desktop before Qt imports")
from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
    QTabWidget, QSplitter, QDialogButtonBox, QFormLayout, QKeySequenceEdit,
)

from .paths import CACHE
from .server import make_server
from .translator import translate_preserving_paragraphs, TranslationCancelled, check_cancel
from . import preferences
from .window_state import WindowState
from .ui_style import apply_app_style

trace("desktop imports complete")


class SelectionOverlay(QDialog):
    selected = Signal(object)

    def __init__(self, screen, screenshot):
        super().__init__()
        self.screen = screen
        self.screenshot = screenshot
        self.selection_rect: QRect | None = None
        self.origin: QPoint | None = None
        self.end: QPoint | None = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._selection_completed = False

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if self.origin and self.end:
            rect = QRect(self.origin, self.end).normalized()
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(QPen(Qt.GlobalColor.cyan, 2))
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.origin = event.position().toPoint()
            self.end = self.origin

    def mouseMoveEvent(self, event):
        if self.origin:
            self.end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self.origin is None:
            return
        self.end = event.position().toPoint()
        rect = QRect(self.origin, self.end).normalized().intersected(self.rect())
        self._selection_completed = True
        self.close()
        if rect.width() < 12 or rect.height() < 12:
            self.selected.emit(None)
            return
        self.selection_rect = QRect(rect)
        ratio = self.screenshot.devicePixelRatio()
        pixel_rect = QRect(
            round(rect.x() * ratio), round(rect.y() * ratio),
            round(rect.width() * ratio), round(rect.height() * ratio),
        )
        self.selected.emit(self.screenshot.copy(pixel_rect))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
            event.accept()
        else:
            super().keyPressEvent(event)

    def reject(self):
        if not self._selection_completed:
            self._selection_completed = True
            self.selected.emit(None)
        super().reject()

    def closeEvent(self, event):
        self.releaseKeyboard()
        if not self._selection_completed:
            self._selection_completed = True
            self.selected.emit(None)
        super().closeEvent(event)


class TranslateWorker(QThread):
    completed = Signal(str, str, bool, int)
    failed = Signal(str, bool, int)
    progress = Signal(str)

    def __init__(
        self, *, text: str | None = None, image: Path | None = None,
        source: str = "auto", monitor: bool = False, monitor_generation: int = 0,
    ):
        super().__init__()
        self.cancel_event = Event()
        self.text = text
        self.image = image
        self.source = source
        self.monitor = monitor
        self.monitor_generation = monitor_generation

    def run(self):
        try:
            check_cancel(self.cancel_event)
            text = self.text
            if self.image:
                self.progress.emit("正在识别文字…")
                from .ocr import recognize
                text = recognize(self.image)
            if not text or not text.strip():
                raise RuntimeError("没有识别到文字。请重新框选清晰的文字区域。")
            check_cancel(self.cancel_event)
            translated = translate_preserving_paragraphs(
                text, self.source, cancel=self.cancel_event,
                on_progress=lambda done, total: self.progress.emit(f"正在翻译 {done}/{total} 段…"),
            )
            check_cancel(self.cancel_event)
            self.completed.emit(text, translated, self.monitor, self.monitor_generation)
        except TranslationCancelled:
            pass
        except Exception as exc:
            self.failed.emit(str(exc), self.monitor, self.monitor_generation)
        finally:
            if self.image:
                self.image.unlink(missing_ok=True)


class MainWindow(QMainWindow):
    @staticmethod
    def _make_card(title: str, hint: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        content = QVBoxLayout(card)
        content.setContentsMargins(17, 15, 17, 17)
        content.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        content.addWidget(heading)
        description = QLabel(hint)
        description.setObjectName("cardHint")
        description.setWordWrap(True)
        content.addWidget(description)
        return card, content

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Triloa · 离线翻译")
        self.setMinimumSize(720, 580)
        self.resize(870, 740)
        self._worker = None
        self._task_in_flight = False
        self._overlay = None
        self._selection_pending = False
        self._subtitle_control = None
        self._monitor_overlay: MonitorTranslationOverlay | None = None
        self._select_for_monitor = False
        self._monitoring = False
        self._monitor_screen = None
        self._monitor_rect: QRect | None = None
        self._monitor_last_hash: str | None = None
        self._monitor_generation = 0
        self._monitor_pending_image: Path | None = None
        self._monitor_was_paused_for_selection = False
        self._monitor_timer = QTimer(self)
        self._monitor_timer.setInterval(1000)
        self._monitor_timer.timeout.connect(self._capture_monitor_region)

        self._closing = False
        self._monitor_force_retry = False
        self._monitor_retry_at = 0.0
        self._monitor_failures = 0
        self._monitor_candidate_hash = None
        self._exit_timer = QTimer(self)
        self._exit_timer.setInterval(100)
        self._exit_timer.timeout.connect(self._finish_close)
        self.hotkeys = None
        self.tray = None

        root = QWidget()
        root.setObjectName("windowRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        header = QHBoxLayout()
        brand = QLabel("Triloa")
        brand.setObjectName("brand")
        header.addWidget(brand)
        header.addStretch()
        badge = QLabel("离线 · 本机处理")
        badge.setObjectName("muted")
        badge.hide()
        from .translation_picker import TranslationModelPicker
        self.translation_picker = TranslationModelPicker()
        header.addWidget(self.translation_picker)
        settings_button = QPushButton("设置")
        settings_button.clicked.connect(self.open_settings)
        header.addWidget(settings_button)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        text_page = QWidget()
        text_layout = QVBoxLayout(text_page)
        text_layout.setContentsMargins(0, 12, 0, 0)
        tools = QHBoxLayout()
        for text, action in (("框选翻译", self.select_region), ("翻译剪贴板", self.translate_clipboard)):
            button = QPushButton(text)
            button.clicked.connect(action)
            tools.addWidget(button)
        tools.addStretch()
        self.source_choice = QComboBox()
        for text, code in (("自动检测", "auto"), ("英语", "en"), ("日语", "ja")):
            self.source_choice.addItem(text, code)
        self.source_choice.setCurrentIndex(max(0, self.source_choice.findData(preferences.get('text.language', 'auto'))))
        self.source_choice.currentIndexChanged.connect(lambda: preferences.put('text.language', self.source_choice.currentData()))
        tools.addWidget(self.source_choice)
        text_layout.addLayout(tools)
        editors = QSplitter(Qt.Horizontal)
        self.original, self.translation = QTextEdit(), QTextEdit()
        self.original.setPlaceholderText("输入英文或日文，按 Ctrl+Enter 翻译")
        self.translation.setPlaceholderText("中文译文")
        self.translation.setReadOnly(True)
        for name, editor in (("原文", self.original), ("中文译文", self.translation)):
            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.addWidget(QLabel(name))
            column_layout.addWidget(editor, 1)
            editors.addWidget(column)
        editors.setChildrenCollapsible(False)
        text_layout.addWidget(editors, 1)
        actions = QHBoxLayout()
        self.translate_button = QPushButton("翻译")
        self.translate_button.setObjectName("primaryButton")
        self.translate_button.clicked.connect(self.translate_input)
        actions.addWidget(self.translate_button)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_translation)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        clear = QPushButton("清空")
        clear.clicked.connect(self.clear_text)
        actions.addWidget(clear)
        copy = QPushButton("复制译文")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.translation.toPlainText()))
        actions.addWidget(copy)
        text_layout.addLayout(actions)
        self.tabs.addTab(text_page, "文字翻译")
        self.translate_shortcut = QShortcut(QKeySequence('Ctrl+Return'), self)
        self.translate_shortcut.activated.connect(self.translate_input)

        screen_page = QWidget()
        screen_layout = QVBoxLayout(screen_page)
        screen_layout.setContentsMargins(0, 12, 0, 0)
        card, content = self._make_card("持续翻译屏幕区域", "框选文献、图片或视频中的文字。画面变化时自动更新译文。")
        row = QHBoxLayout()
        self.monitor_button = QPushButton("选择监视区域")
        self.monitor_button.setObjectName("primaryButton")
        self.monitor_button.clicked.connect(self.start_monitoring)
        row.addWidget(self.monitor_button)
        self.retry_monitor_button = QPushButton("重新识别")
        self.retry_monitor_button.setEnabled(False)
        self.retry_monitor_button.clicked.connect(self.retry_monitor)
        row.addWidget(self.retry_monitor_button)
        self.stop_monitor_button = QPushButton("停止监视")
        self.stop_monitor_button.setEnabled(False)
        self.stop_monitor_button.clicked.connect(self.stop_monitoring)
        row.addWidget(self.stop_monitor_button)
        content.addLayout(row)
        content.addWidget(QLabel("按 Esc 取消框选；悬浮窗解锁后可移动和缩放。"))
        screen_layout.addWidget(card)
        screen_layout.addStretch()
        self.tabs.addTab(screen_page, "屏幕翻译")
        self.subtitle_page = QWidget()
        self.subtitle_page.setObjectName("windowRoot")
        self.subtitle_layout = QVBoxLayout(self.subtitle_page)
        self.subtitle_layout.setContentsMargins(0, 0, 0, 0)
        subtitle_scroll = QScrollArea()
        subtitle_scroll.setWidgetResizable(True)
        subtitle_scroll.setFrameShape(QFrame.NoFrame)
        subtitle_scroll.setWidget(self.subtitle_page)
        self.tabs.addTab(subtitle_scroll, "实时字幕")
        self.tabs.currentChanged.connect(self._tab_changed)

        self.status = QLabel("就绪 · 全部在本机处理")
        self.status.setObjectName("statusText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.setCentralWidget(root)
        self.window_state = WindowState(self, 'main')
        self.tabs.setCurrentIndex(int(preferences.number('main.tab', 0, 0, 2)))

    def _tab_changed(self, index):
        preferences.put('main.tab', index)
        if index == 2 and self._subtitle_control is None:
            from .subtitles import SubtitleControl
            self._subtitle_control = SubtitleControl(embedded=True)
            self.subtitle_layout.addWidget(self._subtitle_control)

    def show_subtitles(self):
        self.tabs.setCurrentIndex(2)
        self._tab_changed(2)
        self._restore_main_window()

    def toggle_subtitles(self):
        if self._subtitle_control is None:
            self.show_subtitles()
        else:
            self._subtitle_control.toggle_overlay()

    def clear_text(self):
        self.cancel_translation()
        self.original.clear()
        self.translation.clear()

    def cancel_translation(self):
        if self._worker is not None:
            self._worker.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.status.setText("已取消 · 正在结束当前处理")
        if self._monitoring:
            self.stop_monitoring()

    def retry_monitor(self):
        self._monitor_last_hash = None
        self._monitor_retry_at = 0
        if self._task_in_flight:
            self._monitor_force_retry = True
            self._set_monitor_status("当前处理结束后重新识别")
        else:
            self._capture_monitor_region()

    def reset_positions(self):
        screen = QApplication.primaryScreen()
        if screen:
            self.resize(870, 680)
            self.move(screen.availableGeometry().center() - self.rect().center())
        if self._subtitle_control:
            self._subtitle_control.reset_positions()
        if self._monitor_overlay and screen:
            self._monitor_overlay._has_initial_placement = False
            self._monitor_overlay.place_on_screen(screen)
        for key in ('main', 'subtitles', 'history', 'monitor'):
            preferences.put('window.' + key, None)
        self.status.setText("窗口位置已恢复")

    def open_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("设置")
        form = QFormLayout(dialog)
        fields = {}
        defaults = {'select': 'Ctrl+Alt+T', 'clipboard': 'Ctrl+Alt+C', 'subtitles': 'Ctrl+Alt+S'}
        labels = {'select': '框选翻译', 'clipboard': '翻译剪贴板', 'subtitles': '显示 / 隐藏字幕'}
        for key, default in defaults.items():
            edit = QKeySequenceEdit(QKeySequence(preferences.get('hotkey.' + key, default)))
            fields[key] = edit
            form.addRow(labels[key], edit)
        hint = QLabel("使用一个组合键；留空可禁用。占用冲突时会提示。")
        form.addRow(hint)
        reset = QPushButton("恢复所有窗口位置")
        reset.clicked.connect(self.reset_positions)
        form.addRow(reset)
        from .paths import DATA
        location = QLabel(f"设置与日志：{DATA}")
        location.setWordWrap(True)
        form.addRow(location)
        log = QPushButton("查看最近错误")
        def show_log():
            path = DATA / 'errors.log'
            text = path.read_text(encoding='utf-8')[-12000:] if path.exists() else '暂无错误记录'
            viewer = QDialog(dialog)
            viewer.setWindowTitle('最近错误')
            view_layout = QVBoxLayout(viewer)
            editor = QTextEdit()
            editor.setReadOnly(True)
            editor.setPlainText(text)
            view_layout.addWidget(editor)
            viewer.resize(650, 380)
            viewer.exec()
        log.clicked.connect(show_log)
        form.addRow(log)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.rejected.connect(dialog.reject)
        def save():
            for key, field in fields.items():
                preferences.put('hotkey.' + key, field.keySequence().toString(QKeySequence.PortableText))
            if self.hotkeys:
                failures = self.hotkeys.register()
                self.status.setText('；'.join(failures) if failures else '快捷键已保存')
            dialog.accept()
        buttons.accepted.connect(save)
        form.addRow(buttons)
        dialog.exec()

    def _start_worker(self, *, monitor: bool = False, monitor_generation: int = 0, **kwargs):
        if self._closing:
            if image := kwargs.get("image"):
                image.unlink(missing_ok=True)
            return
        if self._task_in_flight:
            self.status.setText("正在翻译，请稍候…")
            if image := kwargs.get("image"):
                if monitor and self._monitoring and monitor_generation == self._monitor_generation:
                    if self._monitor_pending_image:
                        self._monitor_pending_image.unlink(missing_ok=True)
                    self._monitor_pending_image = image
                    return
                image.unlink(missing_ok=True)
            if not monitor:
                self.show()
            return
        self.status.setText("正在本机处理…")
        self._task_in_flight = True
        self.translate_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._worker = TranslateWorker(
            source=self.source_choice.currentData(), monitor=monitor,
            monitor_generation=monitor_generation, **kwargs,
        )
        self._worker.progress.connect(self._progress)
        self._worker.completed.connect(self._complete)
        self._worker.failed.connect(self._failure)
        self._worker.finished.connect(self._worker_finished)
        self._worker.start()

    def _progress(self, message):
        if not self._closing and self._worker and not self._worker.cancel_event.is_set():
            self.status.setText(message)

    def _complete(self, source, translated, monitor=False, monitor_generation=0):
        if self._closing or (self._worker and self._worker.cancel_event.is_set()):
            return
        if monitor and monitor_generation != self._monitor_generation:
            return
        if monitor:
            if self._monitoring and self._monitor_overlay is not None:
                self._monitor_last_hash = self._monitor_candidate_hash
                self._monitor_failures = 0
                self._monitor_retry_at = 0
                self._monitor_overlay.set_translation(translated)
                self.status.setText("持续监视中 · 画面有变化时自动更新")
            return
        self.tabs.setCurrentIndex(0)
        self.original.setPlainText(source)
        self.translation.setPlainText(translated)
        self.status.setText("翻译完成 · 全部在本机处理")
        self.show()
        self.raise_()

    def _failure(self, message, monitor=False, monitor_generation=0):
        if self._closing or (self._worker and self._worker.cancel_event.is_set()):
            return
        from .diagnostics import report_error
        report_error("屏幕/文字翻译", message)
        if monitor and monitor_generation != self._monitor_generation:
            return
        if monitor and self._monitoring:
            self._monitor_failures += 1
            delay = min(30, 2 ** min(self._monitor_failures, 5))
            self._monitor_retry_at = monotonic() + delay
            self._set_monitor_status(f"处理失败，{delay} 秒后重试：{message}")
            return
        self.status.setText(message)
        self.show()
        self.raise_()

    def _worker_finished(self):
        self._task_in_flight = False
        if self._worker:
            if self._worker.cancel_event.is_set():
                self.status.setText("已取消")
            self._worker.deleteLater()
        self._worker = None
        if self._monitor_force_retry:
            self._monitor_last_hash = None
            self._monitor_retry_at = 0
            self._monitor_force_retry = False
        self.translate_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self._monitor_pending_image:
            image = self._monitor_pending_image
            self._monitor_pending_image = None
            if self._monitoring:
                self._start_worker(
                    image=image, monitor=True,
                    monitor_generation=self._monitor_generation,
                )
            else:
                image.unlink(missing_ok=True)

    def translate_input(self):
        self._start_worker(text=self.original.toPlainText())

    def translate_clipboard(self):
        content = QApplication.clipboard().text()
        self.original.setPlainText(content)
        self._start_worker(text=content)

    def select_region(self):
        if self._closing or self._overlay is not None or self._selection_pending:
            return
        if self._task_in_flight:
            self.status.setText("请先取消或等待当前翻译完成")
            return
        self._monitor_was_paused_for_selection = self._monitor_timer.isActive()
        if self._monitor_was_paused_for_selection:
            self._monitor_timer.stop()
        self._selection_pending = True
        self.hide()
        QTimer.singleShot(250, self._show_selection)

    def start_monitoring(self):
        if self._monitoring:
            self._set_monitor_status("已在持续监视所选区域")
            return
        if self._task_in_flight:
            self.status.setText("请等待当前翻译完成后再开始监视")
            return
        self._select_for_monitor = True
        self.select_region()

    def _restore_main_window(self):
        if self._closing:
            return
        self.showNormal()
        if self._monitoring:
            set_capture_excluded(self, True)
        self.raise_()
        self.activateWindow()

    def _set_monitor_status(self, message: str):
        self.status.setText(message)
        if self._monitor_overlay is not None:
            self._monitor_overlay.set_status(message)

    def stop_monitoring(self):
        self._stop_monitoring(restore_window=True)

    def _stop_monitoring(self, restore_window: bool):
        was_monitoring = self._monitoring
        self._monitor_generation += 1
        self._monitoring = False
        self._monitor_timer.stop()
        if self._worker and self._worker.monitor:
            self._worker.cancel_event.set()
        set_capture_excluded(self, False)
        self._monitor_screen = None
        self._monitor_rect = None
        self._monitor_last_hash = None
        if self._monitor_pending_image:
            self._monitor_pending_image.unlink(missing_ok=True)
            self._monitor_pending_image = None
        if self._monitor_overlay is not None:
            self._monitor_overlay.close()
            self._monitor_overlay.deleteLater()
            self._monitor_overlay = None
        self.monitor_button.setEnabled(True)
        self.stop_monitor_button.setEnabled(False)
        self.retry_monitor_button.setEnabled(False)
        self.status.setText("持续监视已停止")
        if was_monitoring and restore_window:
            self._restore_main_window()

    @staticmethod
    def _encode_image(image) -> bytes:
        buffer = QBuffer()
        if not buffer.open(QIODevice.WriteOnly):
            raise RuntimeError("无法创建截图缓存")
        try:
            if not image.save(buffer, "PNG"):
                raise RuntimeError("编码屏幕截图失败")
            return bytes(buffer.data())
        finally:
            buffer.close()

    @staticmethod
    def _save_image_bytes(payload: bytes, prefix: str) -> Path:
        destination = CACHE / "tmp" / f"{prefix}-{uuid4().hex}.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return destination

    @staticmethod
    def _crop_region(screenshot, rect: QRect):
        ratio = screenshot.devicePixelRatio()
        pixel_rect = QRect(
            round(rect.x() * ratio), round(rect.y() * ratio),
            round(rect.width() * ratio), round(rect.height() * ratio),
        ).intersected(screenshot.rect())
        if pixel_rect.width() < 1 or pixel_rect.height() < 1:
            return None
        return screenshot.copy(pixel_rect)

    def _resume_monitoring_after_selection(self):
        if self._monitor_was_paused_for_selection and self._monitoring:
            self._monitor_timer.start()
        self._monitor_was_paused_for_selection = False

    def _show_selection(self):
        self._selection_pending = False
        if self._closing:
            return
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if not screen:
            self.show()
            self._resume_monitoring_after_selection()
            return
        screenshot = screen.grabWindow(0)
        self._overlay = SelectionOverlay(screen, screenshot)
        self._overlay.selected.connect(self._selected)
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()
        self._overlay.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self._overlay.grabKeyboard()

    def _selected(self, image):
        overlay = self._overlay
        self._overlay = None
        if overlay:
            overlay.deleteLater()
        if self._closing:
            return
        monitor_selection = self._select_for_monitor
        self._select_for_monitor = False
        if image is None:
            self.show()
            self._resume_monitoring_after_selection()
            return
        try:
            payload = self._encode_image(image)
            destination = self._save_image_bytes(payload, "selection")
        except Exception as exc:
            self._failure(str(exc))
            self._resume_monitoring_after_selection()
            return
        if monitor_selection:
            if not overlay or overlay.selection_rect is None:
                destination.unlink(missing_ok=True)
                self._failure("无法读取所选区域")
                return
            self._begin_monitoring(overlay.screen, overlay.selection_rect, payload)
            self.showMinimized()
            self._start_worker(
                image=destination, monitor=True,
                monitor_generation=self._monitor_generation,
            )
        else:
            self.show()
            self._start_worker(image=destination)
            self._resume_monitoring_after_selection()

    def _begin_monitoring(self, screen, rect: QRect, initial_payload: bytes):
        self._monitor_generation += 1
        self._monitoring = True
        self._monitor_screen = screen
        self._monitor_rect = QRect(rect)
        self._monitor_last_hash = None
        self._monitor_candidate_hash = sha256(initial_payload).hexdigest()
        self._monitor_retry_at = 0
        self._monitor_failures = 0
        self._monitor_pending_image = None
        self.monitor_button.setEnabled(False)
        self.stop_monitor_button.setEnabled(True)
        self.retry_monitor_button.setEnabled(True)
        self.status.setText("持续监视已启动 · 每秒检查画面变化")
        self._monitor_overlay = MonitorTranslationOverlay(
            on_restore=self._restore_main_window,
            on_stop=self.stop_monitoring, on_retry=self.retry_monitor,
        )
        self._monitor_overlay.place_on_screen(screen)
        self._monitor_overlay.show()
        set_capture_excluded(self, True)
        self._monitor_timer.start()

    def _capture_monitor_region(self):
        if not self._monitoring or not self._monitor_screen or not self._monitor_rect:
            return
        if self._task_in_flight or self._monitor_pending_image or monotonic() < self._monitor_retry_at:
            return
        try:
            screenshot = self._monitor_screen.grabWindow(0)
            image = self._crop_region(screenshot, self._monitor_rect)
            if image is None or image.isNull():
                raise RuntimeError("无法读取监视区域截图")
            payload = self._encode_image(image)
            digest = sha256(payload).hexdigest()
            if digest == self._monitor_last_hash:
                return
            self._monitor_candidate_hash = digest
            destination = self._save_image_bytes(payload, "monitor")
            self._start_worker(
                image=destination, monitor=True,
                monitor_generation=self._monitor_generation,
            )
        except Exception as exc:
            self._set_monitor_status(f"持续监视中 · 截图失败：{exc}")

    def closeEvent(self, event):
        self._closing = True
        self.window_state.save()
        self._stop_monitoring(restore_window=False)
        if self._overlay:
            self._overlay.reject()
        if self._worker:
            self._worker.cancel_event.set()
        if self._subtitle_control:
            self._subtitle_control.close()
        if self._task_in_flight or (self._subtitle_control and self._subtitle_control.runner is not None):
            event.ignore()
            self.hide()
            self._exit_timer.start()
            return
        self._exit_timer.stop()
        if self.tray:
            self.tray.hide()
        if self.hotkeys:
            self.hotkeys.unregister()
        event.accept()
        QApplication.instance().quit()

    def _finish_close(self):
        if not self._task_in_flight and not (self._subtitle_control and self._subtitle_control.runner is not None):
            self.close()


def run_desktop() -> int:
    trace("creating QApplication")
    app = QApplication([])
    trace("created QApplication")
    app.setApplicationName("Triloa")
    apply_app_style(app)
    trace("creating MainWindow")
    from .desktop_integration import InstanceGuard, Hotkeys, install_tray
    guard = InstanceGuard()
    if not guard.acquire():
        return 0
    app.setQuitOnLastWindowClosed(False)
    app.aboutToQuit.connect(guard.close)
    window = MainWindow()
    guard.callback = window._restore_main_window
    window.hotkeys = Hotkeys(window)
    failures = window.hotkeys.register()
    if failures:
        window.status.setText('；'.join(failures))
    install_tray(window)
    trace("created MainWindow")
    try:
        trace("binding local API")
        server = make_server()
        trace("bound local API")
        Thread(target=server.serve_forever, daemon=True, name="TriloaLocalAPI").start()
    except OSError:
        QMessageBox.warning(window, "本地服务", "端口 8765 已占用，Edge 扩展可能无法连接本程序。")
    trace("showing MainWindow")
    window.show()
    trace("shown MainWindow")
    result = app.exec()
    if "server" in locals():
        server.shutdown()
        server.server_close()
    return result
