"""Shared global translation model chooser; loading happens on worker threads."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QComboBox, QPushButton, QFileDialog, QMessageBox, QLabel
from . import translator

class TranslationModelPicker(QWidget):
    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel('翻译模型'))
        self.choice = QComboBox()
        self.choice.addItem('HY-MT · 默认', 'auto')
        self.choice.addItem('Qwen3-4B', 'qwen')
        self.choice.addItem('Argos · 环境变量', 'argos')
        self.choice.model().item(2).setEnabled(False)
        self.choice.currentIndexChanged.connect(self.choose)
        row.addWidget(self.choice)
        self.browse = QPushButton('选择 GGUF')
        self.browse.clicked.connect(self.browse_model)
        row.addWidget(self.browse)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def refresh(self):
        backend = translator.selected_backend()
        self.choice.blockSignals(True)
        self.choice.setCurrentIndex(max(0, self.choice.findData('auto' if backend == 'hy' else backend)))
        self.choice.blockSignals(False)
        busy = bool(translator._sessions or translator._requests or translator._active)
        self.choice.setEnabled(not busy)
        self.browse.setEnabled(not busy)
        path = translator.qwen_model()
        self.setToolTip(('Qwen：' + str(path) if path else 'Qwen 尚未配置，请选择本地 Qwen3-4B GGUF。') + '\n开始字幕后，请先停止字幕再切换模型。所有翻译功能共用此选择。')

    def choose(self):
        try:
            translator.set_backend(self.choice.currentData())
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.information(self, '翻译模型', str(exc))
        self.refresh()

    def browse_model(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 Qwen3-4B GGUF', '', 'GGUF 模型 (*.gguf)')
        if not path:
            return
        try:
            translator.set_backend('qwen', qwen_path=path)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, '翻译模型', str(exc))
        self.refresh()
