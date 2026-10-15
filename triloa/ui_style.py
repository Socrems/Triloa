"""Shared Qt Widgets styling for Triloa's desktop windows."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication, QAbstractButton, QComboBox, QProxyStyle, QStyle,
    QStyleOptionComboBox, QStylePainter,
)

from .paths import ROOT


APP_QSS = """
QWidget {
    color: #223047;
    font-family: "Segoe UI", "Microsoft YaHei UI";
    font-size: 13px;
}
QMainWindow, QDialog, QMessageBox, QWidget#windowRoot, QWidget#subtitleRoot {
    background-color: #F5F7FA;
}
QFrame#card {
    background: #FFFFFF;
    border: 1px solid #D9E0E9;
    border-radius: 12px;
}
QFrame#statusStrip {
    background: #EDF2F7;
    border: 1px solid #D9E0E9;
    border-radius: 8px;
}
QLabel#brand { font-size: 24px; font-weight: 600; }
QLabel#sectionTitle { font-size: 15px; font-weight: 600; }
QLabel#muted, QLabel#eyebrow, QLabel#cardHint {
    color: #637187;
    font-size: 12px;
}
QLabel#eyebrow { font-weight: 600; }
QLabel#statusDot { color: #356AC3; font-size: 16px; }
QLabel#statusText { color: #637187; font-size: 12px; }
QLabel[error="true"], QLabel#cardHint[error="true"], QLabel#statusText[error="true"] { color: #B44848; }
QLabel:disabled, QCheckBox:disabled { color: #8B96A6; }
QPushButton {
    outline: none;
    background: #FFFFFF;
    border: 1px solid #D9E0E9;
    border-radius: 8px;
    color: #223047;
    min-height: 20px;
    padding: 6px 12px;
}
QPushButton:hover { background: #EDF2F7; border-color: #A7B9D2; }
QPushButton:pressed { background: #EAF1FC; border-color: #4F83CD; }
QPushButton:focus, QComboBox:focus, QTextEdit:focus, QLineEdit:focus,
QSpinBox:focus, QKeySequenceEdit:focus, QKeySequenceEdit QLineEdit:focus {
    border: 1px solid #4F83CD;
}
QPushButton:disabled {
    color: #8B96A6;
    background: #EDF2F7;
    border-color: #E1E6EE;
}
QPushButton#primaryButton {
    background: #356AC3;
    border-color: #356AC3;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton#primaryButton:hover { background: #2E5EAF; border-color: #2E5EAF; }
QPushButton#primaryButton:pressed { background: #254E96; }
QPushButton#primaryButton:focus { border: 2px solid #4F83CD; padding: 5px 11px; }
QPushButton#primaryButton:disabled {
    background: #C8D6EB;
    border-color: #C8D6EB;
    color: #F5F7FA;
}
QPushButton#quietButton { background: transparent; }
QPushButton#quietButton:hover { background: #EDF2F7; }
QPushButton#dangerButton:hover { color: #B44848; background: #FBEEEE; border-color: #D9AAAA; }
QComboBox, QTextEdit, QLineEdit, QSpinBox, QKeySequenceEdit {
    background: #FFFFFF;
    border: 1px solid #D9E0E9;
    border-radius: 8px;
    color: #223047;
    selection-background-color: #DCE9FC;
    selection-color: #223047;
}
QComboBox { min-height: 20px; padding: 6px 12px; padding-right: 28px; }
QLineEdit, QSpinBox { min-height: 20px; padding: 6px 9px; }
QKeySequenceEdit { min-height: 20px; padding: 0 2px; }
QKeySequenceEdit QLineEdit { background: transparent; border: none; padding: 6px 7px; }
QLineEdit:read-only, QTextEdit:read-only { background: #FFFFFF; color: #223047; }
QComboBox:disabled, QLineEdit:disabled, QTextEdit:disabled,
QSpinBox:disabled, QKeySequenceEdit:disabled {
    background: #EDF2F7;
    color: #8B96A6;
    border-color: #E1E6EE;
}
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url("__ASSET_ROOT__/chevron-down.svg"); width: 12px; height: 12px; }
QComboBox QAbstractItemView {
    background: #FFFFFF;
    color: #223047;
    border: 1px solid #D9E0E9;
    outline: none;
    selection-background-color: #EAF1FC;
    selection-color: #223047;
    padding: 4px;
}
QComboBox QAbstractItemView::item { min-height: 28px; padding: 2px 8px; }
QComboBox QAbstractItemView::item:disabled { color: #8B96A6; }
QSpinBox { padding-right: 23px; }
QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border;
    width: 22px;
    border-left: 1px solid #D9E0E9;
    background: #EDF2F7;
}
QSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 8px; }
QSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 8px; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #EAF1FC; }
QSpinBox::up-arrow { image: url("__ASSET_ROOT__/chevron-up.svg"); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url("__ASSET_ROOT__/chevron-down.svg"); width: 10px; height: 10px; }
QTextEdit { padding: 9px; }
QCheckBox { spacing: 8px; min-height: 24px; }
QCheckBox::indicator { width: 17px; height: 17px; }
QCheckBox:focus { color: #356AC3; }
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: transparent;
    color: #637187;
    padding: 10px 22px;
    border-bottom: 2px solid #D9E0E9;
}
QTabBar::tab:selected {
    background: #EAF1FC;
    color: #356AC3;
    border-bottom: 2px solid #356AC3;
}
QTabBar::tab:hover { color: #356AC3; background: #EDF2F7; }
QTabBar::tab:focus { border-bottom: 2px solid #4F83CD; }
QMenu {
    background: #FFFFFF;
    color: #223047;
    border: 1px solid #D9E0E9;
    border-radius: 8px;
    padding: 5px;
}
QMenu::item { padding: 8px 22px; border-radius: 4px; }
QMenu::item:selected { background: #EAF1FC; color: #223047; }
QMenu::item:disabled { color: #8B96A6; }
QMenu::separator { height: 1px; background: #D9E0E9; margin: 4px 8px; }
QToolTip { color: #223047; background: #FFFFFF; border: 1px solid #D9E0E9; padding: 6px; }
QProgressBar {
    background: #EDF2F7;
    color: #637187;
    border: 1px solid #D9E0E9;
    border-radius: 4px;
    text-align: center;
    min-height: 8px;
}
QProgressBar::chunk { background: #356AC3; border-radius: 3px; }
QSplitter::handle { background: #D9E0E9; margin: 5px 2px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical {
    background: #EDF2F7; width: 15px; margin: 2px 0;
    border: 1px solid #D9E0E9; border-radius: 3px;
}
QScrollBar:horizontal {
    background: #EDF2F7; height: 15px; margin: 0 2px;
    border: 1px solid #D9E0E9; border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #A4AFBE; border: 2px solid #EDF2F7;
    border-radius: 5px; min-height: 32px;
}
QScrollBar::handle:horizontal {
    background: #A4AFBE; border: 2px solid #EDF2F7;
    border-radius: 5px; min-width: 32px;
}
QScrollBar::handle:hover { background: #7C8CA3; }
QScrollBar::handle:pressed { background: #4F83CD; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: #EDF2F7; }
""".replace('__ASSET_ROOT__', (ROOT / 'assets').as_posix())

# Floating video captions and their history keep a self-contained dark theme.
# A local sheet takes precedence over the application's light control states.
DARK_OVERLAY_QSS = """
QWidget { color: #F1F3F5; background: transparent; }
QLabel { color: #F1F3F5; background: transparent; border: none; }
QPushButton {
    color: #F1F3F5; background: rgba(255,255,255,26);
    border: 1px solid rgba(170,185,200,80); border-radius: 6px;
    min-height: 28px; padding: 0 8px;
}
QPushButton:hover { background: rgba(95,115,138,140); border-color: #8AA8CD; }
QPushButton:pressed { background: #344C68; }
QPushButton:focus { border: 1px solid #82AFE8; }
QPushButton:disabled { color: #7E8997; background: rgba(255,255,255,10); border-color: #414B58; }
QSpinBox {
    color: #F1F3F5; background: #30363D; border: 1px solid #64717D;
    border-radius: 6px; min-height: 28px; padding: 0 25px 0 6px;
    selection-background-color: #397DA7; selection-color: #FFFFFF;
}
QSpinBox:focus { border-color: #82AFE8; }
QSpinBox:disabled { color: #7E8997; background: #272C33; border-color: #414B58; }
QSpinBox QLineEdit { color: #F1F3F5; background: transparent; border: none; padding: 0; min-height: 0; }
QSpinBox::up-button, QSpinBox::down-button { background: #3C4652; border-left: 1px solid #64717D; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #52647B; }
QSpinBox::up-arrow { image: url("__ASSET_ROOT__/chevron-up-light.svg"); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url("__ASSET_ROOT__/chevron-down-light.svg"); width: 10px; height: 10px; }
QTextEdit, QTextEdit:read-only {
    color: #F1F3F5; background: transparent; border: none;
    selection-background-color: #397DA7; selection-color: #FFFFFF;
    font-size: 15px; padding: 0;
}
QTextEdit:focus { border: none; }
QScrollBar:vertical { background: #272C33; border-color: #3B424B; width: 15px; }
QScrollBar:horizontal { background: #272C33; border-color: #3B424B; height: 15px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #85909D; border-color: #272C33; }
QScrollBar::handle:hover { background: #B1BCC9; }
QScrollBar::handle:pressed { background: #66B7EB; }
QScrollBar::add-page, QScrollBar::sub-page, QAbstractScrollArea::corner { background: #272C33; }
""".replace('__ASSET_ROOT__', (ROOT / 'assets').as_posix())


class ElidingComboBox(QComboBox):
    """Keep long model/device names inside their available field width."""
    def paintEvent(self, event):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        field = self.style().subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self)
        option.currentText = option.fontMetrics.elidedText(option.currentText, Qt.ElideRight, max(0, field.width() - 4))
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        painter.drawControl(QStyle.CE_ComboBoxLabel, option)


def apply_dark_overlay_style(widget) -> None:
    palette = widget.palette()
    for role, color in ((QPalette.WindowText, '#F1F3F5'), (QPalette.Text, '#F1F3F5'),
                        (QPalette.ButtonText, '#F1F3F5'), (QPalette.PlaceholderText, '#9EADBE'),
                        (QPalette.Base, '#1B1E23'), (QPalette.Highlight, '#397DA7'),
                        (QPalette.HighlightedText, '#FFFFFF')):
        palette.setColor(role, QColor(color))
    widget.setPalette(palette)
    widget.setStyleSheet(DARK_OVERLAY_QSS)


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
    # Native popup surfaces and indicators must remain light on a dark Windows theme.
    palette = QPalette()
    for role, color in (
        (QPalette.Window, '#F5F7FA'), (QPalette.WindowText, '#223047'),
        (QPalette.Base, '#FFFFFF'), (QPalette.AlternateBase, '#EDF2F7'),
        (QPalette.Text, '#223047'), (QPalette.Button, '#FFFFFF'),
        (QPalette.ButtonText, '#223047'), (QPalette.Highlight, '#EAF1FC'),
        (QPalette.HighlightedText, '#223047'), (QPalette.ToolTipBase, '#FFFFFF'),
        (QPalette.ToolTipText, '#223047'), (QPalette.PlaceholderText, '#637187'),
        (QPalette.Light, '#FFFFFF'), (QPalette.Midlight, '#EDF2F7'),
        (QPalette.Mid, '#D9E0E9'), (QPalette.Dark, '#A4AFBE'),
        (QPalette.Shadow, '#637187'), (QPalette.Link, '#356AC3'),
    ):
        palette.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor('#8B96A6'))
    palette.setColor(QPalette.Disabled, QPalette.Base, QColor('#EDF2F7'))
    app.setPalette(palette)
    app.setWindowIcon(QIcon(str(ROOT / 'assets' / 'triloa.png')))
    app.setFont(QFont('Segoe UI', 10))
    app.setStyleSheet(APP_QSS)
