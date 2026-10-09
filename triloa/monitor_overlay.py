"""Right-side translation window for continuous screen monitoring."""

from __future__ import annotations

from .window_state import WindowState
from collections.abc import Callable
import ctypes
import sys

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QScreen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def set_capture_excluded(widget: QWidget, excluded: bool) -> bool:
    """Keep our own floating windows out of Windows screen captures."""
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(widget.winId())
        affinity = 0x11 if excluded else 0  # WDA_EXCLUDEFROMCAPTURE / WDA_NONE
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, affinity))
    except (AttributeError, OSError, ValueError):
        return False


class MonitorTranslationOverlay(QWidget):
    def __init__(self, on_restore: Callable[[], None], on_stop: Callable[[], None], on_retry: Callable[[], None] | None = None):
        super().__init__()
        self.setWindowTitle("Triloa · 实时翻译")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(290, 200)
        self.resize(360, 300)

        self._locked = True
        self._has_initial_placement = False
        self._drag_origin: QPoint | None = None
        self._drag_window_origin: QPoint | None = None
        self._hover_hide_timer = QTimer(self)
        self._hover_hide_timer.setSingleShot(True)
        self._hover_hide_timer.timeout.connect(self._hide_hover_controls_if_outside)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("monitorPanel")
        panel.setStyleSheet("""
            QFrame#monitorPanel {
                background-color: rgba(12, 14, 17, 230);
                border: 1px solid rgba(255, 255, 255, 55);
                border-radius: 13px;
            }
            QLabel#monitorTitle {
                color: white;
                font-size: 14px;
                font-weight: 600;
            }
            QLabel#monitorStatus {
                color: #bbc4ce;
                font-size: 12px;
            }
            QPushButton#monitorAction {
                background-color: rgba(255, 255, 255, 28);
                border: 1px solid rgba(255, 255, 255, 55);
                border-radius: 6px;
                color: white;
                min-height: 20px;
                padding: 3px 8px;
            }
            QPushButton#monitorAction:hover {
                background-color: rgba(255, 255, 255, 55);
            }
            QTextEdit#monitorTranslation {
                background: transparent;
                border: none;
                color: white;
                font-size: 16px;
                padding: 0;
                selection-background-color: #397da7;
            }
        """)
        outer.addWidget(panel)

        content = QVBoxLayout(panel)
        content.setContentsMargins(15, 13, 15, 15)
        content.setSpacing(10)
        self.header_widget = QWidget(panel)
        header = QHBoxLayout(self.header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("中文实时翻译")
        title.setObjectName("monitorTitle")
        header.addWidget(title)
        header.addStretch()
        self.lock_button = QPushButton("🔒")
        self.lock_button.setObjectName("monitorAction")
        self.lock_button.setFixedSize(32, 28)
        self.lock_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lock_button.setToolTip("点击解锁位置和大小")
        self.lock_button.clicked.connect(self._toggle_locked)
        self.lock_button.hide()
        header.addWidget(self.lock_button)
        restore = QPushButton("恢复主窗口")
        restore.setObjectName("monitorAction")
        restore.setToolTip("恢复 Triloa 主窗口，持续监视保持运行")
        restore.clicked.connect(on_restore)
        header.addWidget(restore)
        stop = QPushButton("停止监视")
        stop.setObjectName("monitorAction")
        stop.setToolTip("停止持续监视并恢复主窗口")
        stop.clicked.connect(on_stop)
        header.addWidget(stop)
        content.addWidget(self.header_widget)

        self.status = QLabel("等待识别所选区域…")
        self.status.setObjectName("monitorStatus")
        self.status.setWordWrap(True)
        content.addWidget(self.status)
        if on_retry:
            retry = QPushButton("重新识别")
            retry.clicked.connect(on_retry)
            content.addWidget(retry)
        self.translation = QTextEdit()
        self.translation.setObjectName("monitorTranslation")
        self.translation.setReadOnly(True)
        self.translation.setPlaceholderText("中文译文将在这里显示")
        content.addWidget(self.translation, 1)

        self.resize_grip = QSizeGrip(self)
        self.resize_grip.setToolTip("拖动以调整大小")
        self.resize_grip.hide()
        self._drag_targets = (
            panel, self.header_widget, title, self.status, self.translation,
        )
        for target in self._drag_targets:
            target.installEventFilter(self)

        self.window_state = WindowState(self, "monitor")
        self._has_initial_placement = self.window_state.restored
        self.lock_button.clicked.connect(self.window_state.save)

    def showEvent(self, event):
        super().showEvent(event)
        set_capture_excluded(self, True)

    def closeEvent(self, event):
        set_capture_excluded(self, False)
        super().closeEvent(event)

    def _toggle_locked(self):
        self._locked = not self._locked
        self.lock_button.setText("🔒" if self._locked else "🔓")
        self.lock_button.setToolTip(
            "点击解锁位置和大小" if self._locked else "点击锁定位置和大小"
        )
        self.resize_grip.setVisible(
            not self._locked and self.frameGeometry().contains(QCursor.pos())
        )

    def _show_hover_controls(self):
        self._hover_hide_timer.stop()
        self.lock_button.show()
        self.resize_grip.setVisible(not self._locked)

    def _hide_hover_controls_if_outside(self):
        if not self.isVisible() or not self.frameGeometry().contains(QCursor.pos()):
            self.lock_button.hide()
            self.resize_grip.hide()

    def enterEvent(self, event):
        self._show_hover_controls()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_hide_timer.start(120)
        super().leaveEvent(event)

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type == QEvent.Type.Enter:
            self._show_hover_controls()
        elif event_type == QEvent.Type.Leave:
            self._hover_hide_timer.start(120)
        elif event_type == QEvent.Type.MouseButtonPress:
            if not self._locked and event.button() == Qt.MouseButton.LeftButton:
                self._drag_origin = event.globalPosition().toPoint()
                self._drag_window_origin = self.pos()
        elif event_type == QEvent.Type.MouseMove:
            if (
                not self._locked
                and self._drag_origin is not None
                and self._drag_window_origin is not None
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                delta = event.globalPosition().toPoint() - self._drag_origin
                if delta.manhattanLength() >= QApplication.startDragDistance():
                    self.move(self._drag_window_origin + delta)
                    event.accept()
                    return True
        elif event_type == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_origin = None
                self._drag_window_origin = None
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_window_origin = self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            not self._locked
            and self._drag_origin is not None
            and self._drag_window_origin is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            delta = event.globalPosition().toPoint() - self._drag_origin
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self.move(self._drag_window_origin + delta)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            self._drag_window_origin = None
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        size = self.resize_grip.sizeHint()
        self.resize_grip.setGeometry(
            self.width() - size.width(), self.height() - size.height(),
            size.width(), size.height(),
        )
        super().resizeEvent(event)

    def place_on_screen(self, screen: QScreen) -> None:
        if self._has_initial_placement:
            return
        self._has_initial_placement = True
        area = screen.availableGeometry()
        margin_x = min(15, max(8, area.width() // 40))
        margin_y = min(15, max(8, area.height() // 40))
        min_width = max(160, min(290, area.width() - 2 * margin_x))
        min_height = max(140, min(200, area.height() - 2 * margin_y))
        self.setMinimumSize(min_width, min_height)
        width = min(380, max(min_width, area.width() // 3))
        height = min(320, max(min_height, area.height() // 3))
        x = area.x() + area.width() - width - margin_x
        y = area.top() + min(90, max(15, area.height() // 7))
        y = min(y, area.y() + area.height() - height - margin_y)
        self.setGeometry(x, y, width, height)

    def set_translation(self, text: str) -> None:
        self.translation.setPlainText(text)
        self.translation.verticalScrollBar().setValue(0)
        self.status.setText("持续监视中 · 画面变化后自动更新")

    def set_status(self, message: str) -> None:
        self.status.setText(message)
