"""Shared Qt Widgets styling for Triloa's desktop windows."""

from __future__ import annotations

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QAbstractButton, QProxyStyle, QStyle

from .paths import ROOT


APP_QSS = """
QDialog { background: #191b1f; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #202328; color: #aab2bd; padding: 10px 24px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #f1f3f5; background: #292e35; border-bottom: 2px solid #59b3e8; }
QProgressBar { border: none; border-radius: 4px; background: #191b1f; }
QProgressBar::chunk { background: #59b3e8; border-radius: 4px; }
QSplitter::handle { background: #34383e; margin: 5px 2px; }
QSpinBox, QKeySequenceEdit { background: #26292e; padding: 6px; border: 1px solid #4a5058; border-radius: 5px; }
QMenu { background: #26292e; border: 1px solid #4a5058; }
QMenu::item { padding: 8px 20px; }
QMenu::item:selected { background: #344650; }

QWidget {
    color: #f1f3f5;
    font-family: "Segoe UI", "Microsoft YaHei UI";
    font-size: 13px;
}
QMainWindow, QWidget#windowRoot, QWidget#subtitleRoot {
    background-color: #191b1f;
}
QFrame#card {
    background-color: #26292e;
    border: 1px solid #34383e;
    border-radius: 13px;
}
QFrame#statusStrip {
    background-color: #202b33;
    border: 1px solid #344650;
    border-radius: 9px;
}
QLabel#brand {
    color: #f5f7fa;
    font-size: 27px;
    font-weight: 700;
}
QLabel#sectionTitle {
    color: #f4f6f8;
    font-size: 15px;
    font-weight: 600;
}
QLabel#muted, QLabel#eyebrow, QLabel#cardHint {
    color: #aab2bd;
}
QLabel#eyebrow {
    font-size: 11px;
    font-weight: 600;
}
QLabel#statusDot {
    color: #59b3e8;
    font-size: 19px;
}
QLabel#statusText {
    color: #d6e9f3;
}
QPushButton {
    outline: none;
    background-color: #343940;
    border: 1px solid #4a5058;
    border-radius: 8px;
    color: #eef2f6;
    min-height: 22px;
    padding: 8px 14px;
}
QPushButton:hover {
    background-color: #404750;
    border-color: #66a9d6;
}
QPushButton:pressed {
    background-color: #2c617e;
}
QPushButton:focus, QComboBox:focus, QTextEdit:focus, QLineEdit:focus {
    border: 1px solid #65afe0;
}
QPushButton:disabled {
    color: #7d858f;
    background-color: #2c3035;
    border-color: #383d43;
}
QPushButton#primaryButton {
    background-color: #398ac4;
    border: 1px solid #4c9bd2;
    color: white;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background-color: #4b9cd6;
}
QPushButton#primaryButton:disabled {
    background-color: #31506a;
    border-color: #3e6179;
    color: #a8bac8;
}
QPushButton#quietButton {
    background-color: transparent;
}
QPushButton#dangerButton:hover {
    background-color: #60383b;
    border-color: #d9787b;
}
QComboBox, QTextEdit, QLineEdit {
    background-color: #202328;
    border: 1px solid #464c55;
    border-radius: 8px;
    color: #f0f3f6;
    selection-background-color: #397da7;
}
QComboBox {
    min-height: 22px;
    padding: 7px 12px;
}
QPushButton#headerButton, QComboBox#headerModel {
    min-height: 24px;
    padding: 6px 12px;
}
QLineEdit {
    min-height: 22px;
    padding: 7px 9px;
}
QComboBox::drop-down {
    border: none;
    width: 25px;
}
QComboBox QAbstractItemView {
    background-color: #282c32;
    color: #f0f3f6;
    border: 1px solid #4a5058;
    selection-background-color: #397da7;
}
QTextEdit {
    padding: 9px;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: #272c33;
    width: 15px;
    margin: 2px 0;
    border: 1px solid #3b424b;
    border-radius: 3px;
}
QScrollBar:horizontal {
    background: #272c33;
    height: 15px;
    margin: 0 2px;
    border: 1px solid #3b424b;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #85909d;
    border: 2px solid #272c33;
    border-radius: 5px;
    min-height: 32px;
}
QScrollBar::handle:horizontal {
    background: #85909d;
    border: 2px solid #272c33;
    border-radius: 5px;
    min-width: 32px;
}
QScrollBar::handle:hover { background: #b1bcc9; }
QScrollBar::handle:pressed { background: #66b7eb; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: #272c33; }
"""


class AppStyle(QProxyStyle):
    """Keep keyboard focus and the solid QSS border without Windows' dotted inset."""
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_ComboBox_AllowWheelScrolling:
            # Popup lists keep their own scrolling; only clicking commits a choice.
            return 0
        return super().styleHint(hint, option, widget, returnData)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PE_FrameFocusRect and isinstance(widget, QAbstractButton):
            return
        super().drawPrimitive(element, option, painter, widget)


def apply_app_style(app: QApplication) -> None:
    if not getattr(app, '_triloa_focus_style', None):
        app._triloa_focus_style = AppStyle()
        app.setStyle(app._triloa_focus_style)
    app.setWindowIcon(QIcon(str(ROOT / "assets" / "triloa.png")))
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(APP_QSS)
