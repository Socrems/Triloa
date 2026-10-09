"""Remember window geometry on the GUI thread and recover off-screen windows."""
from PySide6.QtCore import QObject, QEvent, QRect, QTimer
from PySide6.QtWidgets import QApplication
from . import preferences
from .diagnostics import report_error

class WindowState(QObject):
    def __init__(self, widget, key):
        super().__init__(widget)
        self.widget, self.key = widget, key
        self.seen = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.save)
        saved = preferences.get('window.' + key)
        self.restored = False
        if isinstance(saved, dict):
            rect = saved.get('rect')
            if isinstance(rect, list) and len(rect) == 4 and all(isinstance(n, int) for n in rect):
                widget.setGeometry(self.clamp(QRect(*rect)))
                self.restored = True
            if hasattr(widget, '_locked') and isinstance(saved.get('locked'), bool):
                if saved['locked'] != widget._locked:
                    widget._toggle_locked()
        widget.installEventFilter(self)
        QApplication.instance().screenRemoved.connect(self.keep_visible)

    def clamp(self, rect):
        screens = QApplication.screens()
        if not screens:
            return rect
        screen = next((s for s in screens if s.availableGeometry().contains(rect.center())), screens[0])
        area = screen.availableGeometry().adjusted(8, 8, -8, -8)
        width = min(max(self.widget.minimumWidth(), rect.width()), area.width())
        height = min(max(self.widget.minimumHeight(), rect.height()), area.height())
        return QRect(max(area.left(), min(rect.x(), area.right() - width + 1)),
                     max(area.top(), min(rect.y(), area.bottom() - height + 1)), width, height)

    def keep_visible(self, *_):
        self.widget.setGeometry(self.clamp(self.widget.geometry()))

    def save(self):
        if not self.seen or self.widget.isMinimized():
            return
        rect = self.widget.normalGeometry() if self.widget.isMaximized() else self.widget.geometry()
        try:
            preferences.put('window.' + self.key, {
                'rect': [rect.x(), rect.y(), rect.width(), rect.height()],
                'locked': getattr(self.widget, '_locked', True),
            })
        except OSError as exc:
            report_error('保存窗口设置', exc)

    def eventFilter(self, watched, event):
        if not hasattr(self, "seen"):
            return False
        if event.type() == QEvent.Type.Show:
            self.seen = True
        if self.seen and event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self.timer.start(400)
        if event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
            self.save()
        return False
