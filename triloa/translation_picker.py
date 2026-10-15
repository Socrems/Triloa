"""Shared translation model chooser; weights load on worker threads."""
import os
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QComboBox, QPushButton, QFileDialog,
    QMessageBox, QLabel, QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QMenu, QSizePolicy,
)

from . import translator
from .translation_models import PROFILES, EXECUTIONS, registered_models, same_path, guess_profile
from .ui_style import ElidingComboBox


class LocalModelDialog(QDialog):
    def __init__(self, parent, path, model=None):
        super().__init__(parent)
        self.model_id = model.id if model is not None else None
        self.setWindowTitle('模型设置' if model is not None else '添加本地翻译模型')
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        hint = QLabel('选择已下载的 GGUF 翻译或对话模型。文件保留在原位置，启动后按需加载。')
        hint.setObjectName('cardHint')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)
        self.name = QLineEdit(model.name if model is not None else Path(path).stem)
        self.name.setMaxLength(80)
        form.addRow('显示名称', self.name)
        self.path = QLineEdit(str(path))
        self.path.setReadOnly(True)
        self.path.setToolTip(str(path))
        self.path.setMinimumWidth(0)
        self.path.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        file_row.addWidget(self.path, 1)
        browse = QPushButton('选择文件')
        browse.clicked.connect(self.browse_path)
        file_row.addWidget(browse)
        form.addRow('模型文件', file_row)
        self.profile = QComboBox()
        for key, label in PROFILES.items():
            self.profile.addItem(label, key)
        self.profile.setCurrentIndex(self.profile.findData(model.profile if model else guess_profile(Path(path))))
        form.addRow('模型类型', self.profile)
        self.execution = QComboBox()
        for key, label in EXECUTIONS.items():
            self.execution.addItem(label, key)
        self.execution.setCurrentIndex(self.execution.findData(model.execution if model else 'auto'))
        form.addRow('运行方式', self.execution)
        layout.addLayout(form)
        detail = QLabel('通用模型使用文件自带的对话模板；Qwen 配置会关闭思考。'
                        '仅 CPU 通常更慢。兼容性、中文翻译质量和内存需求取决于所选模型。')
        detail.setWordWrap(True)
        detail.setObjectName('cardHint')
        layout.addWidget(detail)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('保存并使用')
        buttons.button(QDialogButtonBox.Save).setObjectName('primaryButton')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.save_model)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse_path(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 GGUF 翻译模型',
                                             str(Path(self.path.text()).parent), 'GGUF 模型 (*.gguf)')
        if path:
            previous = Path(self.path.text())
            if self.name.text() == previous.stem:
                self.name.setText(Path(path).stem)
            self.path.setText(path)
            self.path.setToolTip(path)
            self.profile.setCurrentIndex(self.profile.findData(guess_profile(Path(path))))

    def save_model(self):
        try:
            translator.save_local_model(self.path.text(), self.name.text(), self.profile.currentData(),
                                        self.execution.currentData(), model_id=self.model_id)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, '翻译模型', str(exc))
            return
        self.accept()


class TranslationModelPicker(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel('翻译模型'))
        self.choice = ElidingComboBox()
        self.choice.setObjectName('headerModel')
        self.choice.setMinimumWidth(160)
        self.choice.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.choice.setMinimumContentsLength(15)
        self.choice.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.choice.currentIndexChanged.connect(self.choose)
        row.addWidget(self.choice, 1)
        self.manage = QPushButton('管理模型')
        self.manage.setObjectName('headerButton')
        menu = QMenu(self.manage)
        self.browse = menu.addAction('添加 GGUF 模型…', self.browse_model)
        self.edit = menu.addAction('编辑当前模型…', self.edit_model)
        self.remove = menu.addAction('移除当前记录', self.remove_model)
        self.remove.setToolTip('从选择列表移除这条记录，模型文件保留在原位置')
        self.manage.setMenu(menu)
        row.addWidget(self.manage)
        layout.addLayout(row)
        self.detail = QLabel()
        self.detail.setObjectName('cardHint')
        self.detail.setWordWrap(True)
        self.detail.setMinimumWidth(0)
        self.detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.detail)
        self._entries = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def _current_record(self):
        choice = self.choice.currentData() or ''
        identifier = choice.removeprefix('custom:') if choice.startswith('custom:') else None
        return next((model for model in registered_models() if model.id == identifier), None)

    def refresh(self):
        models = registered_models()
        entries = [('auto', 'HY-MT · 默认 / Argos 备用', ''),
                   ('qwen', 'Qwen · 已有配置', ''), ('argos', 'Argos · CPU', '')]
        for model in models:
            label = model.name if model.path.is_file() else model.name + ' · 文件缺失'
            entries.append(('custom:' + model.id, label, str(model.path)))
        self.choice.blockSignals(True)
        if entries != self._entries:
            self.choice.clear()
            for identifier, label, path in entries:
                self.choice.addItem(label, identifier)
                self.choice.setItemData(self.choice.count() - 1, label + ('\n' + path if path else ''), Qt.ToolTipRole)
            self._entries = entries
        backend = translator.selected_backend()
        selected = translator.selected_local_model() if backend == 'custom' else None
        identifier = 'custom:' + selected.id if selected is not None else 'auto' if backend == 'hy' else backend
        self.choice.setCurrentIndex(self.choice.findData(identifier))
        self.choice.setToolTip(self.choice.currentData(Qt.ToolTipRole) or self.choice.currentText())
        self.choice.blockSignals(False)
        locked = translator.model_busy()
        controlled = bool(os.getenv('TRILOA_TRANSLATOR'))
        self.choice.setEnabled(not locked and not controlled)
        self.manage.setEnabled(not locked and not controlled)
        self.browse.setEnabled(not locked and not controlled)
        self.edit.setEnabled(not locked and not controlled and selected is not None)
        self.remove.setEnabled(not locked and not controlled and selected is not None)
        if selected is not None:
            state = PROFILES[selected.profile] + ' · ' + EXECUTIONS[selected.execution]
            message = f'{state} · {selected.path.name}' if selected.path.is_file() else '模型文件缺失，请在“模型设置”中重新选择文件'
            self.detail.setToolTip(str(selected.path))
        elif backend == 'qwen':
            path = translator.qwen_model()
            message = path.name if path is not None else 'Qwen 尚未配置，请通过“添加 GGUF”选择本地模型'
            self.detail.setToolTip(str(path) if path is not None else '')
        elif backend == 'custom':
            message = '所选模型记录缺失，请重新添加模型或切换选择'
            self.detail.setToolTip('')
        else:
            message = '所有文字、OCR、网页和字幕翻译共用此选择；添加的模型会保留在列表中'
            self.detail.setToolTip('')
        if controlled:
            message = '模型由 TRILOA_TRANSLATOR 环境变量指定，清除该变量并重启后可在这里选择'
        elif locked:
            message = '模型正在使用，请停止字幕并等待翻译结束后再切换或修改'
        self.detail.setText(message)

    def choose(self):
        choice = self.choice.currentData()
        if not choice:
            return
        try:
            if choice.startswith('custom:'):
                translator.set_backend('custom', model_id=choice.removeprefix('custom:'))
            else:
                translator.set_backend(choice)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.information(self, '翻译模型', str(exc))
        self.refresh()

    def browse_model(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择本地 GGUF 翻译模型', '', 'GGUF 模型 (*.gguf)')
        if path:
            existing = next((model for model in registered_models() if same_path(model.path, Path(path))), None)
            LocalModelDialog(self, path, existing).exec()
        self.refresh()

    def edit_model(self):
        model = self._current_record()
        if model is not None:
            LocalModelDialog(self, model.path, model).exec()
        self.refresh()

    def remove_model(self):
        model = self._current_record()
        if model is not None:
            try:
                translator.remove_local_model(model.id)
            except (OSError, ValueError, RuntimeError) as exc:
                QMessageBox.information(self, '翻译模型', str(exc))
        self.refresh()
