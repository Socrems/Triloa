"""Always-on-top bilingual subtitle overlay driven by local system audio."""

from __future__ import annotations

from threading import Thread
from pathlib import Path

from .paths import MODELS, configure_paths, portable

configure_paths()

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QProgressBar, QLayout,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizeGrip,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .speech import SpeechSubtitle, SpeechSubtitleRunner, list_loopback_devices
from . import preferences
from .window_state import WindowState
from .subtitle_history import SubtitleHistoryOverlay
from .nemotron import NemotronSpeechSubtitleRunner, NEMOTRON_MODEL_PATH, nemotron_available
from .qwen_asr import (QwenASRSpeechSubtitleRunner, QWEN_ASR_MODEL_PATH,
                       model_path as qwen_model_path, model_ready as qwen_model_ready,
                       runtime_available as qwen_runtime_available, select_model_folder)
from .translator import release_translator, begin_subtitle_session, end_subtitle_session, selected_backend
from .ui_style import apply_app_style


class SubtitleBridge(QObject):
    subtitle = Signal(object)
    ready = Signal(str)
    error = Signal(str)
    stopped = Signal()
    level = Signal(int)
    phase = Signal(str)
    devices = Signal(object)


class VerticalResizeHandle(QWidget):
    """Resize from either horizontal edge, including upward from the screen bottom."""
    def __init__(self, overlay, top):
        super().__init__(overlay)
        self.overlay, self.top = overlay, top
        self.origin = None
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip('上下拖动以调整字幕高度')

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.overlay._locked:
            self.origin = event.globalPosition().toPoint()
            self.start_rect = self.overlay.geometry()
            self.overlay._hide_timer.stop()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.origin is None or self.overlay._locked:
            return
        delta = event.globalPosition().toPoint().y() - self.origin.y()
        rect = self.start_rect
        height = max(self.overlay.minimumHeight(), rect.height() + (-delta if self.top else delta))
        y = rect.bottom() - height + 1 if self.top else rect.y()
        self.overlay.setGeometry(rect.x(), y, rect.width(), height)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.origin = None
            self.overlay.window_state.save()
            event.accept()


class SubtitleOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Triloa · 实时双语字幕")
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(320, 150)
        self.resize(880, 250)
        self._locked = True
        self._has_initial_placement = False
        self._drag_origin: QPoint | None = None
        self._drag_window_origin: QPoint | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame(self)
        self.panel.setObjectName("bilingualSubtitlePanel")
        self.panel.setStyleSheet(
            "QFrame#bilingualSubtitlePanel { "
            "background: rgba(27, 30, 35, 225); "
            "border: 1px solid rgba(170, 185, 200, 70); border-radius: 12px; }"
        )
        outer.addWidget(self.panel)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(12, 7, 12, 10)
        layout.setSpacing(0)
        toolbar_host = QWidget(self.panel)
        toolbar = QHBoxLayout(toolbar_host)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addStretch()
        self._lock_host = QWidget(self)
        self._lock_host.setFixedSize(34, 30)
        lock_layout = QHBoxLayout(self._lock_host)
        lock_layout.setContentsMargins(0, 0, 0, 0)
        lock_layout.setSpacing(0)
        self.lock_button = QPushButton("🔒", self._lock_host)
        self.lock_button.setFixedSize(30, 26)
        self.lock_button.setFocusPolicy(Qt.NoFocus)
        self.lock_button.setToolTip("点击解锁位置和大小")
        self.lock_button.setStyleSheet(
            "QPushButton { color: white; background: rgba(27, 30, 35, 225); "
            "border: 1px solid rgba(170, 185, 200, 100); border-radius: 7px; "
            "font-size: 16px; padding: 0; } "
            "QPushButton:hover { background: rgba(65, 75, 86, 240); }"
        )
        self.lock_button.clicked.connect(self._toggle_locked)
        self.lock_button.hide()
        lock_layout.addWidget(self.lock_button)
        toolbar.addWidget(self._lock_host)
        layout.addWidget(toolbar_host)

        self.original = QTextEdit()
        self.chinese = QTextEdit()
        for label in (self.original, self.chinese):
            label.setReadOnly(True)
            label.setFrameStyle(QFrame.Shape.NoFrame)
            label.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.original.setMinimumHeight(40)
        self.original.setStyleSheet(
            "QTextEdit { color: #e0e7ee; background: transparent; "
            "border: none; padding: 9px 15px; font-size: 18px; }"
        )
        layout.addWidget(self.original, 1)
        divider = QFrame(self.panel)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: rgba(170, 185, 200, 70); border: none;")
        layout.addWidget(divider)
        self.chinese.setMinimumHeight(40)
        self.chinese.setStyleSheet(
            "QTextEdit { color: #ffffff; background: transparent; "
            "border: none; padding: 9px 15px; "
            "font-size: 22px; font-weight: 600; }"
        )
        layout.addWidget(self.chinese, 1)
        for target in (
            self.panel, toolbar_host, self._lock_host, divider,
            self.original.viewport(), self.chinese.viewport(),
        ):
            target.installEventFilter(self)

        self._resize_grip = QSizeGrip(self)
        self._resize_grip.setToolTip("拖动以调整大小")
        self._resize_grip.hide()
        self._hover_hide_timer = QTimer(self)
        self._hover_hide_timer.setSingleShot(True)
        self._hover_hide_timer.timeout.connect(self._hide_hover_controls_if_outside)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self.hide()
        self._height_handles = [VerticalResizeHandle(self, True), VerticalResizeHandle(self, False)]
        for handle in self._height_handles:
            handle.hide()
        self.window_state = WindowState(self, "subtitles")
        self._has_initial_placement = self.window_state.restored
        self.lock_button.clicked.connect(self.window_state.save)
        self.apply_appearance()

    def apply_appearance(self):
        for editor, key, default, color in ((self.original, 'original_size', 18, '#e0e7ee'), (self.chinese, 'translated_size', 22, '#ffffff')):
            size = preferences.number('captions.' + key, default, 12, 48)
            editor.setStyleSheet(f"QTextEdit {{color: {color}; background: transparent; border: none; padding: 9px 15px; font-size: {size}px;}}")
        opacity = preferences.number('captions.opacity', 88, 30, 100)
        self.panel.setStyleSheet(f"QFrame#bilingualSubtitlePanel {{background: rgba(27,30,35,{round(opacity * 2.55)}); border: 1px solid rgba(170,185,200,70); border-radius: 12px;}}")
        ratio = int(preferences.number('captions.ratio', 50, 25, 75))
        self.panel.layout().setStretch(1, ratio)
        self.panel.layout().setStretch(3, 100 - ratio)
        self._hide_timer.stop()

    def _toggle_locked(self):
        self._locked = not self._locked
        for handle in self._height_handles:
            handle.setVisible(not self._locked)
            handle.raise_()
        self.lock_button.setText("🔒" if self._locked else "🔓")
        self.lock_button.setToolTip(
            "点击解锁位置和大小" if self._locked else "点击锁定位置和大小"
        )
        self._resize_grip.setVisible(
            not self._locked and self.frameGeometry().contains(QCursor.pos())
        )

    def _show_hover_controls(self):
        self._hover_hide_timer.stop()
        self.lock_button.show()
        self._resize_grip.setVisible(not self._locked)

    def _hide_hover_controls_if_outside(self):
        if not self.isVisible() or not self.frameGeometry().contains(QCursor.pos()):
            self.lock_button.hide()
            self._resize_grip.hide()

    def enterEvent(self, event):
        self._show_hover_controls()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_hide_timer.start(120)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._hover_hide_timer.stop()
        self.lock_button.hide()
        self._resize_grip.hide()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if not self._locked and event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_window_origin = self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def eventFilter(self, watched, event):
        if not self._locked:
            event_type = event.type()
            if event_type == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
                self.mousePressEvent(event)
                return True
            if event_type == QEvent.Type.MouseMove and event.buttons() & Qt.LeftButton:
                self.mouseMoveEvent(event)
                return True
            if event_type == QEvent.Type.MouseButtonRelease and event.button() == Qt.LeftButton:
                self.mouseReleaseEvent(event)
                return True
        return super().eventFilter(watched, event)

    def mouseMoveEvent(self, event):
        if (
            not self._locked
            and self._drag_origin is not None
            and self._drag_window_origin is not None
            and event.buttons() & Qt.LeftButton
        ):
            delta = event.globalPosition().toPoint() - self._drag_origin
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self.move(self._drag_window_origin + delta)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_origin = None
            self._drag_window_origin = None
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        for handle in getattr(self, "_height_handles", []):
            handle.setGeometry(8, 0 if handle.top else self.height() - 7, self.width() - 32, 7)
            handle.raise_()
        size = self._resize_grip.sizeHint()
        self._resize_grip.setGeometry(
            self.width() - size.width(),
            self.height() - size.height(),
            size.width(),
            size.height(),
        )
        super().resizeEvent(event)

    def _place_initially(self):
        if self._has_initial_placement:
            return
        self._has_initial_placement = True
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            self.adjustSize()
            return
        area = screen.availableGeometry()
        margin_x = min(24, max(8, area.width() // 40))
        margin_y = min(24, max(8, area.height() // 40))
        min_width = max(160, min(360, area.width() - 2 * margin_x))
        min_height = 150
        self.setMinimumSize(min_width, min_height)
        width = max(min_width, min(880, area.width() - 2 * margin_x))
        max_height = max(min_height, area.height() - 2 * margin_y)
        height = max(min_height, min(self.height(), max_height))
        x = area.center().x() - width // 2
        y = area.y() + area.height() - height - margin_y
        self.setGeometry(x, y, width, height)

    def show_subtitle(self, subtitle: SpeechSubtitle):
        draft_mark = "" if subtitle.final else " …"
        self.original.setPlainText(subtitle.original + draft_mark)
        self.original.setAlignment(Qt.AlignCenter)
        self.original.verticalScrollBar().setValue(0)
        self.chinese.setPlainText(subtitle.chinese + draft_mark)
        self.chinese.setAlignment(Qt.AlignCenter)
        self.chinese.verticalScrollBar().setValue(0)
        self._place_initially()
        self.show()
        self.raise_()
        seconds = int(preferences.number("captions.hide_seconds", 10, 0, 120))
        if seconds:
            self._hide_timer.start(seconds * 1000)


class SubtitleControl(QWidget):
    def __init__(self, embedded=False):
        super().__init__()
        self.setWindowTitle("Triloa · 双语字幕")
        self.setMinimumSize(480, 390)
        self._overlay_hidden = False
        self._latest_subtitle = None
        self.resize(560, 610)
        self.setObjectName("subtitleRoot")
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(15)

        eyebrow = QLabel("TRILOA  /  LIVE CAPTIONS")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("双语字幕")
        title.setObjectName("brand")
        layout.addWidget(title)
        subtitle = QLabel("识别系统声音，显示英文或日文原文与中文译文")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        subtitle.setText('稳定短语生成临时字幕，句末使用所选翻译模型完整重译')
        layout.addWidget(subtitle)
        if not embedded:
            from .translation_picker import TranslationModelPicker
            layout.addWidget(TranslationModelPicker())

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(17, 15, 17, 17)
        card_layout.setSpacing(10)
        section = QLabel("识别设置")
        section.setObjectName("sectionTitle")
        card_layout.addWidget(section)
        card_layout.addWidget(QLabel("本地语音模型"))

        self.model_paths = {
            "base": MODELS / "faster-whisper" / "base",
            "small": MODELS / "faster-whisper" / "small",
            "nemotron": NEMOTRON_MODEL_PATH,
            "qwen-asr": qwen_model_path(),
        }
        self.model_available = {
            name: self._model_ready(name)
            for name, path in self.model_paths.items()
        }
        self.model_selector = QComboBox()
        self.model_selector.setObjectName("modelSelector")
        labels = {
            "base": "faster-whisper base · 较低延迟",
            "small": "faster-whisper small · 更高准确率，识别稍慢",
            "nemotron": "Nemotron 3.5 · 流式识别",
            "qwen-asr": "Qwen3-ASR-0.6B · 日语 / 英语识别",
        }
        for name, path in self.model_paths.items():
            label = labels[name]
            if not self.model_available[name]:
                label += "（未安装）"
            self.model_selector.addItem(label, name)
            index = self.model_selector.count() - 1
            self.model_selector.setItemData(
                index, str(path), Qt.ItemDataRole.ToolTipRole
            )
            item = self.model_selector.model().item(index)
            if item is not None:
                item.setEnabled(self.model_available[name] or name == "qwen-asr")
        preferred = preferences.get("speech.model")
        if not self.model_available.get(preferred):
            preferred = "nemotron" if self.model_available["nemotron"] else None
        if preferred is None:
            preferred = next(
                (name for name in self.model_paths if self.model_available[name]),
                "base",
            )
        self.model_selector.setCurrentIndex(list(self.model_paths).index(preferred))
        card_layout.addWidget(self.model_selector)
        self.resources_button = QPushButton("安装字幕资源")
        self.resources_button.clicked.connect(self.open_resources)
        card_layout.addWidget(self.resources_button)
        self.qwen_directory_row = QWidget()
        qwen_actions = QHBoxLayout(self.qwen_directory_row)
        qwen_actions.setContentsMargins(0, 0, 0, 0)
        qwen_actions.addWidget(QLabel("模型目录"))
        self.qwen_directory = QLineEdit(str(self.model_paths["qwen-asr"]))
        self.qwen_directory.setReadOnly(True)
        self.qwen_directory.setToolTip(self.qwen_directory.text())
        qwen_actions.addWidget(self.qwen_directory, 1)
        self.qwen_folder_button = QPushButton("选择文件夹")
        self.qwen_folder_button.clicked.connect(self.choose_qwen_folder)
        qwen_actions.addWidget(self.qwen_folder_button)
        card_layout.addWidget(self.qwen_directory_row)

        self.model_detail = QLabel()
        self.model_detail.setObjectName("cardHint")
        self.model_detail.setWordWrap(True)
        card_layout.addWidget(self.model_detail)
        card_layout.addWidget(QLabel("字幕模式"))
        self.mode_selector = QComboBox()
        self.mode_selector.addItem("整句模式 · 句末显示", "sentence")
        self.mode_selector.addItem("实时模式 · 持续更新，句末定稿", "live")
        self.mode_selector.setCurrentIndex(1)
        self.mode_selector.setToolTip(
            "实时模式会在说话过程中显示可修正的临时字幕，句末显示最终结果。"
        )
        card_layout.addWidget(self.mode_selector)
        card_layout.addWidget(QLabel("识别语言"))
        self.language_selector = QComboBox()
        self.language_selector.addItem("自动检测", "auto")
        self.language_selector.addItem("英语", "en")
        self.language_selector.addItem("日语", "ja")
        card_layout.addWidget(self.language_selector)
        device_row = QHBoxLayout()
        self.device_selector = QComboBox()
        self.device_selector.addItem("系统默认播放设备", None)
        saved_device = preferences.get('speech.device')
        if saved_device:
            self.device_selector.addItem(saved_device, saved_device)
            self.device_selector.setCurrentIndex(1)
        device_row.addWidget(self.device_selector, 1)
        self.refresh_button = QPushButton("刷新设备")
        self.refresh_button.clicked.connect(self.refresh_devices)
        device_row.addWidget(self.refresh_button)
        card_layout.addWidget(QLabel("声音来源"))
        card_layout.addLayout(device_row)
        self.audio_level = QProgressBar()
        self.audio_level.setRange(0, 100)
        self.audio_level.setValue(0)
        self.audio_level.setFixedHeight(8)
        self.audio_level.setTextVisible(False)
        self.audio_level.setToolTip("系统播放音量；无声音时检查所选播放设备")
        card_layout.addWidget(self.audio_level)
        layout.addWidget(card)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.start_button = QPushButton("开始字幕")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self._start)
        actions.addWidget(self.start_button, 1)
        self.stop_button = QPushButton("停止实时字幕")
        self.stop_button.setObjectName("quietButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop)
        actions.addWidget(self.stop_button, 1)
        layout.addLayout(actions)
        options = QHBoxLayout()
        for label, callback in (("字幕外观", self.appearance_dialog), ("显示 / 隐藏字幕", self.toggle_overlay), ("显示 / 隐藏历史", self.toggle_history)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            options.addWidget(button)
        layout.addLayout(options)

        status_strip = QFrame()
        status_strip.setObjectName("statusStrip")
        status_layout = QHBoxLayout(status_strip)
        status_layout.setContentsMargins(13, 10, 13, 10)
        dot = QLabel("●")
        dot.setObjectName("statusDot")
        status_layout.addWidget(dot)
        self.status = QLabel("选择本地语音模型，再点击「开始字幕」启动。")
        self.status.setObjectName("statusText")
        self.status.setWordWrap(True)
        status_layout.addWidget(self.status, 1)
        layout.addWidget(status_strip)
        layout.addStretch()

        self.overlay = SubtitleOverlay()
        self.history = SubtitleHistoryOverlay()
        self.bridge = SubtitleBridge()
        self.bridge.subtitle.connect(self._display_subtitle)
        self.bridge.ready.connect(self._on_ready)
        self.bridge.error.connect(self._show_error)
        self.bridge.stopped.connect(self._stopped)
        self.bridge.level.connect(lambda value: self.audio_level.setValue(value) if self._display_enabled else None)
        self.bridge.phase.connect(lambda text: self.status.setText(text) if self._display_enabled else None)
        self.bridge.devices.connect(self._devices_loaded)
        self.runner: SpeechSubtitleRunner | NemotronSpeechSubtitleRunner | None = None
        self.worker: Thread | None = None
        self._running_model = ""
        self._failed = False
        self._display_enabled = False
        self.model_selector.currentIndexChanged.connect(self._update_model_detail)
        for key, selector in (("model", self.model_selector), ("mode", self.mode_selector), ("language", self.language_selector)):
            saved = selector.findData(preferences.get('speech.' + key))
            if saved >= 0 and (key != 'model' or self.model_available.get(selector.itemData(saved))):
                selector.setCurrentIndex(saved)
            selector.currentIndexChanged.connect(lambda _i, k=key, box=selector: preferences.put('speech.' + k, box.currentData()))
        self.device_selector.currentIndexChanged.connect(lambda: preferences.put('speech.device', self.device_selector.currentData()))
        self._update_model_detail()
        if embedded:
            eyebrow.hide()
            title.hide()
            layout.setContentsMargins(0, 12, 0, 0)

    @staticmethod
    def _whisper_ready(name):
        from .resources import whisper_ready
        return whisper_ready(name)

    def _model_ready(self, name):
        if name == "nemotron":
            return nemotron_available()
        if name == "qwen-asr":
            return qwen_runtime_available() and qwen_model_ready(self.model_paths[name])
        return self._whisper_ready(name)

    def choose_qwen_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择完整的 Qwen3-ASR-0.6B 模型目录", str(self.model_paths["qwen-asr"].parent))
        if folder:
            self._select_qwen_folder(Path(folder))

    def _select_qwen_folder(self, folder):
        from .translator import model_busy
        if self.runner is not None or model_busy():
            self.status.setText("请先停止字幕并等待翻译结束，再更换模型目录。")
            return
        try:
            folder = select_model_folder(folder)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        self.model_paths["qwen-asr"] = folder
        self.refresh_models()
        if not qwen_runtime_available():
            self.status.setText("目录已保存；源码版请先运行 setup_qwen_asr.ps1 安装 Qwen3-ASR 推理依赖。")
            return
        self.status.setText("已选择 Qwen3-ASR 本地目录。模型直接从该位置读取，无需复制。")

    def refresh_models(self):
        self.model_paths["qwen-asr"] = qwen_model_path()
        self.qwen_directory.setText(str(self.model_paths["qwen-asr"]))
        self.qwen_directory.setToolTip(self.qwen_directory.text())
        self.model_selector.blockSignals(True)
        try:
            for index, (name, path) in enumerate(self.model_paths.items()):
                ready = self._model_ready(name)
                self.model_available[name] = ready
                label = self.model_selector.itemText(index).replace("（未安装）", "")
                self.model_selector.setItemText(index, label if ready else label + "（未安装）")
                self.model_selector.setItemData(index, str(path), Qt.ItemDataRole.ToolTipRole)
                item = self.model_selector.model().item(index)
                if item is not None:
                    item.setEnabled(ready or name == "qwen-asr")
            if self.model_selector.currentData() != "qwen-asr" and not self.model_available.get(self.model_selector.currentData()):
                for index, name in enumerate(self.model_paths):
                    if self.model_available[name]:
                        self.model_selector.setCurrentIndex(index)
                        break
        finally:
            self.model_selector.blockSignals(False)
        preferences.put('speech.model', self.model_selector.currentData())
        self._update_model_detail()

    def open_resources(self):
        from .translator import model_busy
        if model_busy():
            self.status.setText("请先停止字幕并等待当前翻译结束，再安装资源。")
            return
        from .resource_setup import ResourceSetupDialog
        dialog = ResourceSetupDialog(self)
        if self.model_selector.currentData() == "qwen-asr":
            dialog.qwen_asr.setChecked(True)
        else:
            dialog.subtitles.setChecked(True)
        dialog.resources_installed.connect(self.refresh_models)
        dialog.exec()
        self.refresh_models()

    def refresh_devices(self):
        self.refresh_button.setEnabled(False)
        bridge = self.bridge
        def fetch():
            try:
                result = [device.name for device in list_loopback_devices()]
            except Exception as exc:
                result = str(exc)
            bridge.devices.emit(result)
        Thread(target=fetch, daemon=True, name='TriloaDevices').start()

    def _devices_loaded(self, result):
        self.refresh_button.setEnabled(self.runner is None)
        if isinstance(result, str):
            self.status.setText('无法读取播放设备：' + result)
            return
        saved = self.device_selector.currentData()
        self.device_selector.blockSignals(True)
        self.device_selector.clear()
        self.device_selector.addItem('系统默认播放设备', None)
        for name in result:
            self.device_selector.addItem(name, name)
        if saved and self.device_selector.findData(saved) < 0:
            self.device_selector.addItem(saved + '（当前不可用）', saved)
        self.device_selector.setCurrentIndex(max(0, self.device_selector.findData(saved)))
        self.device_selector.blockSignals(False)

    def toggle_overlay(self):
        self._overlay_hidden = not self._overlay_hidden
        if self._overlay_hidden:
            self.overlay.hide()
        elif self._display_enabled and self._latest_subtitle is not None:
            self.overlay.show_subtitle(self._latest_subtitle)

    def toggle_history(self):
        if self.history.isVisible():
            self.history.hide()
        else:
            self.history.place_on_screen(QApplication.primaryScreen())
            self.history.show()

    def reset_positions(self):
        self.overlay._has_initial_placement = False
        self.overlay._place_initially()
        self.history._placed = False
        self.history.place_on_screen(QApplication.primaryScreen())

    def appearance_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('字幕外观')
        form = QFormLayout(dialog)
        fields = []
        for key, label, default, low, high, suffix in (
            ('original_size', '原文字号', 18, 12, 48, ' px'),
            ('translated_size', '译文字号', 22, 12, 48, ' px'),
            ('opacity', '背景不透明度', 88, 30, 100, '%'),
            ('ratio', '原文所占高度', 50, 25, 75, '%'),
            ('hide_seconds', '无更新后隐藏（0 为常驻）', 10, 0, 120, ' 秒'),
        ):
            field = QSpinBox()
            field.setRange(low, high)
            field.setSuffix(suffix)
            field.setValue(int(preferences.number('captions.' + key, default, low, high)))
            form.addRow(label, field)
            fields.append((key, field))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.Accepted:
            for key, field in fields:
                preferences.put('captions.' + key, field.value())
            self.overlay.apply_appearance()

    def _update_model_detail(self, _index: int = -1):
        name = self.model_selector.currentData()
        self.qwen_directory_row.setVisible(name == "qwen-asr")
        path = self.model_paths[name]
        if self.model_available[name]:
            descriptions = {
                "base": "base 更快，适合优先降低字幕延迟。",
                "small": "small 通常识别更准，代价是处理时间更长。",
                "nemotron": "流式识别可更快更新草稿；首次使用需手动放入本地运行库和模型。",
                "qwen-asr": "Qwen3-ASR 负责识别，译文使用首页所选翻译模型。" + (
                    "当前便携包使用 CPU；源码版可配置 CUDA 加速。" if portable()
                    else "安装显卡依赖后自动使用 CUDA。"
                ) + "实时模式按音频片段更新。",
            }
            self.model_detail.setText(
                descriptions[name]
            )
        else:
            if name == "qwen-asr":
                self.model_detail.setText("请在资源管理下载 Qwen3-ASR，或在上方选择完整的本地模型目录。下载成功后会自动填写目录。")
            elif name == "nemotron":
                self.model_detail.setText(f"Nemotron 模型或运行库未安装，无法启动：{path}")
            else:
                self.model_detail.setText(f"本地模型未安装，无法启动：{path}")
        self.start_button.setEnabled(
            self.model_available[name] and self.runner is None
        )

    def _start(self):
        if self.runner is not None:
            return
        name = self.model_selector.currentData()
        model_path = self.model_paths[name]
        installed = self._model_ready(name)
        if not installed:
            self.model_available[name] = False
            item = self.model_selector.model().item(self.model_selector.currentIndex())
            if item is not None:
                item.setEnabled(name == "qwen-asr")
            self._update_model_detail()
            return

        try:
            begin_subtitle_session()
        except RuntimeError as exc:
            self.status.setText(str(exc))
            return
        from .translator import model_label
        self._translation_label = model_label()
        self._failed = False
        self._latest_subtitle = None
        self._display_enabled = True
        self._running_model = name
        self.stop_button.setEnabled(True)
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is not None:
            self.history.place_on_screen(screen)
        self.history.show()
        self.model_selector.setEnabled(False)
        self.mode_selector.setEnabled(False)
        self.language_selector.setEnabled(False)
        self.device_selector.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.resources_button.setEnabled(False)
        self.qwen_folder_button.setEnabled(False)
        self.qwen_directory.setEnabled(False)
        self.start_button.setEnabled(False)
        model_label = self._model_label()
        self.status.setText(f"正在加载本地 {model_label} 模型…")
        runner_type = {"nemotron": NemotronSpeechSubtitleRunner, "qwen-asr": QwenASRSpeechSubtitleRunner}.get(name, SpeechSubtitleRunner)
        runner_kwargs = {
            "mode": self.mode_selector.currentData(),
            "language": self.language_selector.currentData(),
            "on_subtitle": self.bridge.subtitle.emit,
            "on_ready": self.bridge.ready.emit,
            "on_error": self.bridge.error.emit,
            "on_level": self.bridge.level.emit,
            "on_status": self.bridge.phase.emit,
            "device_name": self.device_selector.currentData(),
        }
        if name != "nemotron":
            runner_kwargs["model_path"] = model_path
        self.runner = runner_type(**runner_kwargs)
        self.worker = Thread(target=self._run, daemon=True, name="TriloaSpeech")
        self.worker.start()

    def _run(self):
        runner = self.runner
        if runner is None:
            return
        try:
            runner.run()
        except Exception as exc:
            if not runner.stop_event.is_set():
                from .diagnostics import report_error
                report_error("字幕运行", exc)
                self.bridge.error.emit(str(exc))
        finally:
            try:
                end_subtitle_session()
                release_translator()
            finally:
                self.bridge.stopped.emit()

    def _on_ready(self, device_name: str):
        if not self._display_enabled:
            return
        self.status.setText(
            f"正在监听系统声音：{device_name} · {self._model_label()}"
        )

    def _display_subtitle(self, subtitle: SpeechSubtitle):
        if not self._display_enabled or self.runner is None:
            return
        self._latest_subtitle = subtitle
        if not self._overlay_hidden:
            self.overlay.show_subtitle(subtitle)
        if subtitle.final:
            self.history.add_final(
                " ".join(subtitle.original.split()),
                " ".join(subtitle.chinese.split()),
            )
        self._on_subtitle(subtitle)

    def _on_subtitle(self, subtitle: SpeechSubtitle):
        self._failed = False
        stage = "句末定稿" if subtitle.final else "实时草稿"
        self.status.setText(
            f"{stage} · {self._model_label()} · {getattr(self, '_translation_label', '本地翻译')}"
        )

    def _model_label(self) -> str:
        if self._running_model == "qwen-asr":
            device = getattr(self.runner, "inference_device", "")
            return "Qwen3-ASR-0.6B" + (" · CUDA" if device.startswith("cuda") else " · CPU" if device == "cpu" else "")
        return {"nemotron": "Nemotron 3.5", "qwen-asr": "Qwen3-ASR-0.6B"}.get(self._running_model, f"faster-whisper {self._running_model}")

    def _show_error(self, message: str):
        if not self._display_enabled:
            return
        self._failed = True
        self.status.setText(f"语音字幕未能运行：{message}")

    def _stop(self):
        self._display_enabled = False
        self.overlay.hide()
        if self.runner is None:
            self.stop_button.setEnabled(False)
            return
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.status.setText("正在停止实时字幕…")
        self.runner.stop()

    def _stopped(self):
        self._display_enabled = False
        self.overlay.hide()
        self.stop_button.setEnabled(False)
        if not self._failed:
            self.status.setText("语音字幕已停止")
        self.runner = None
        self.worker = None
        self.model_selector.setEnabled(True)
        self.mode_selector.setEnabled(True)
        self.language_selector.setEnabled(True)
        self.device_selector.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.resources_button.setEnabled(True)
        self.qwen_folder_button.setEnabled(True)
        self.qwen_directory.setEnabled(True)
        self.audio_level.setValue(0)
        self._update_model_detail()
        self._failed = False

    def closeEvent(self, event):
        self._stop()
        self.overlay.close()
        self.history.close()
        event.accept()


def main() -> int:
    app = QApplication([])
    app.setApplicationName("Triloa Subtitles")
    apply_app_style(app)
    control = SubtitleControl()
    control.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
