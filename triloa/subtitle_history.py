"""Session-only history window for completed bilingual subtitles."""

from __future__ import annotations

from datetime import datetime
from html import escape
from . import preferences
from .window_state import WindowState

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QScreen
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSizeGrip,
    QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)


class SubtitleHistoryOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Triloa · 翻译历史")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(350, 190)
        self.resize(460, 340)
        self._locked = True
        self._placed = False
        self._drag_origin: QPoint | None = None
        self._drag_window_origin: QPoint | None = None
        self._entries: list[tuple[str, str, str]] = []
        self._unread = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame(self)
        panel.setObjectName("historyPanel")
        panel.setStyleSheet("""
            QFrame#historyPanel {
                background-color: rgba(20, 23, 27, 233);
                border: 1px solid rgba(170, 185, 200, 70);
                border-radius: 12px;
            }
            QLabel { color: #ffffff; border: none; }
            QPushButton {
                color: white; background: rgba(255, 255, 255, 26);
                border: 1px solid rgba(170, 185, 200, 80);
                border-radius: 6px; padding: 2px;
            }
            QSpinBox {
                color: white; background: #30363d;
                border: 1px solid #64717d; border-radius: 5px;
                min-height: 23px; padding: 1px 5px;
            }
            QTextEdit {
                color: white; background: transparent;
                border: none; font-size: 15px;
            }
        """)
        outer.addWidget(panel)
        content = QVBoxLayout(panel)
        content.setContentsMargins(15, 12, 15, 13)
        content.setSpacing(8)

        header = QWidget(panel)
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("翻译历史")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        row.addWidget(title)
        row.addStretch()
        row.addWidget(QLabel("最近"))
        self.count_selector = QSpinBox()
        self.count_selector.setRange(1, 100)
        self.count_selector.setValue(int(preferences.number('history.count', 5, 1, 100)))
        self.count_selector.setSuffix(" 句")
        self.count_selector.setToolTip("选择显示最近多少句句末定稿")
        self.count_selector.valueChanged.connect(self._count_changed)
        row.addWidget(self.count_selector)
        self.clear_button = QPushButton("清空历史")
        self.clear_button.setMinimumHeight(28)
        self.clear_button.setToolTip("清空本次运行的全部翻译历史，不影响实时字幕")
        self.clear_button.setEnabled(False)
        self.clear_button.clicked.connect(self.clear_history)
        row.addWidget(self.clear_button)
        self.lock_button = QPushButton("🔒")
        self.lock_button.setFixedSize(30, 28)
        self.lock_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lock_button.setToolTip("点击解锁位置和大小")
        self.lock_button.clicked.connect(self._toggle_locked)
        self.lock_button.hide()
        row.addWidget(self.lock_button)
        content.addWidget(header)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.text.setPlaceholderText("等待第一句句末定稿…")
        content.addWidget(self.text, 1)
        self.new_button = QPushButton('回到最新')
        self.new_button.clicked.connect(self._render)
        self.new_button.hide()
        content.addWidget(self.new_button)

        self.resize_grip = QSizeGrip(self)
        self.resize_grip.setToolTip("拖动以调整大小")
        self.resize_grip.hide()
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._hide_hover_controls_if_outside)
        for target in (panel, header, title):
            target.installEventFilter(self)
        self.window_state = WindowState(self, 'history')
        self._placed = self.window_state.restored
        self.lock_button.clicked.connect(self.window_state.save)

    def _count_changed(self, value):
        preferences.put('history.count', value)
        self._render()

    def add_final(self, original: str, chinese: str) -> None:
        self._entries.append((datetime.now().strftime("%H:%M:%S"), original, chinese))
        del self._entries[:-1000]
        self.clear_button.setEnabled(True)
        if self._unread or self.text.verticalScrollBar().value() < self.text.verticalScrollBar().maximum() - 3 or self.text.textCursor().hasSelection():
            self._unread += 1
            self.new_button.setText(f'{self._unread} 条新记录 · 回到最新')
            self.new_button.show()
            return
        self._render()

    def clear_history(self) -> None:
        self._entries.clear()
        self._render()

    def _render(self, _value: int = 0) -> None:
        self._unread = 0
        self.new_button.hide()
        self.clear_button.setEnabled(bool(self._entries))
        items = self._entries[-self.count_selector.value():]
        blocks = []
        for timestamp, original, chinese in items:
            blocks.append(
                '<p style="margin:0 0 13px 0;">'
                f'<span style="color:#8ab9d6;">[{escape(timestamp)}]</span> '
                f'<span style="color:#f5f7f9;">{escape(original)}</span><br>'
                f'<span style="color:#dcebd9;">{escape(chinese)}</span></p>'
            )
        self.text.setHtml("".join(blocks))
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
        self.text.horizontalScrollBar().setValue(0)

    def place_on_screen(self, screen: QScreen) -> None:
        if self._placed:
            return
        self._placed = True
        area = screen.availableGeometry()
        width = min(self.width(), max(350, area.width() - 32))
        height = min(self.height(), max(190, area.height() - 32))
        self.setGeometry(
            area.right() - width - 16,
            area.top() + min(90, max(16, area.height() // 8)),
            width,
            height,
        )

    def _toggle_locked(self) -> None:
        self._locked = not self._locked
        self.lock_button.setText("🔒" if self._locked else "🔓")
        self.lock_button.setToolTip(
            "点击解锁位置和大小" if self._locked else "点击锁定位置和大小"
        )
        self.resize_grip.setVisible(
            not self._locked and self.frameGeometry().contains(QCursor.pos())
        )

    def _show_hover_controls(self) -> None:
        self._hover_timer.stop()
        self.lock_button.show()
        self.resize_grip.setVisible(not self._locked)

    def _hide_hover_controls_if_outside(self) -> None:
        if not self.isVisible() or not self.frameGeometry().contains(QCursor.pos()):
            self.lock_button.hide()
            self.resize_grip.hide()

    def enterEvent(self, event):
        self._show_hover_controls()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_timer.start(120)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._hover_timer.stop()
        self.lock_button.hide()
        self.resize_grip.hide()
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type == QEvent.Type.Enter:
            self._show_hover_controls()
        elif event_type == QEvent.Type.Leave:
            self._hover_timer.start(120)
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

    def resizeEvent(self, event):
        size = self.resize_grip.sizeHint()
        self.resize_grip.setGeometry(
            self.width() - size.width(), self.height() - size.height(),
            size.width(), size.height(),
        )
        super().resizeEvent(event)
