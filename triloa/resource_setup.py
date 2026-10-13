"""First-run feature selection and a resource manager available afterwards."""
from threading import Event

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QTextEdit, QVBoxLayout,
)

from . import preferences
from .paths import ROOT, portable
from .resources import (
    InstallationCancelled, ResourceManager, byte_label, install_resources,
)


class InstallWorker(QThread):
    progress = Signal(object)
    succeeded = Signal()
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, features, parent=None):
        super().__init__(parent)
        self.features = tuple(features)
        self.cancel_event = Event()

    def run(self):
        try:
            install_resources(self.features, self.cancel_event, self.progress.emit)
            self.succeeded.emit()
        except InstallationCancelled:
            self.cancelled.emit()
        except Exception as exc:
            from .diagnostics import report_error
            report_error("安装资源", exc)
            self.failed.emit(str(exc))


class ResourceSetupDialog(QDialog):
    resources_installed = Signal()
    def __init__(self, parent=None, *, first_run=False):
        super().__init__(parent)
        self.first_run = first_run
        self.worker = None
        self._close_after_cancel = False
        self._outcome = "idle"
        self.setWindowTitle("欢迎使用 Triloa" if first_run else "Triloa · 资源管理")
        self.setMinimumWidth(620)
        self.resize(690, 680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        heading = QLabel("先选择你需要的功能" if first_run else "安装或补齐功能资源")
        heading.setObjectName("brand")
        layout.addWidget(heading)
        introduction = QLabel("资源安装完成后可离线使用。已有资源会直接复用，其他 GGUF 模型仍可在首页手动添加。")
        introduction.setWordWrap(True)
        introduction.setObjectName("cardHint")
        layout.addWidget(introduction)
        self.basic = QCheckBox("基础翻译 · 文字、剪贴板和屏幕 OCR")
        self.basic.setChecked(True)
        layout.addWidget(self.basic)
        basic_hint = QLabel("英语和日语翻译为中文；日语通过英语转译。使用 CPU，无需显卡。")
        basic_hint.setWordWrap(True)
        basic_hint.setObjectName("cardHint")
        layout.addWidget(basic_hint)
        self.subtitles = QCheckBox("实时字幕 · 识别电脑播放的声音并翻译")
        layout.addWidget(self.subtitles)
        subtitle_hint = QLabel("安装多语言 faster-whisper base 和语音检测资源，同时准备基础翻译。")
        subtitle_hint.setWordWrap(True)
        subtitle_hint.setObjectName("cardHint")
        layout.addWidget(subtitle_hint)
        from .qwen_asr import runtime_available
        self.qwen_asr = QCheckBox("Qwen3-ASR-0.6B · 可选的日语 / 英语语音识别模型")
        self.qwen_asr.setEnabled(runtime_available())
        layout.addWidget(self.qwen_asr)
        qwen_hint = QLabel("模型约 1.88 GB，含配置和分词文件；同时准备基础翻译。可在字幕页选择已有本地目录。CPU 可运行，但速度取决于硬件。")
        if not runtime_available():
            qwen_hint.setText("源码版先运行 setup_qwen_asr.ps1 安装推理依赖，再在这里下载模型；v0.1.3 便携包已包含依赖。")
        qwen_hint.setWordWrap(True)
        qwen_hint.setObjectName("cardHint")
        layout.addWidget(qwen_hint)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        location = QLabel(f"模型、下载和缓存保存在程序文件夹内：\n{ROOT}\n请解压到可写目录。基础资源另预留约 2 GB；选择 Qwen3-ASR 再增加约 2 GB。")
        if not portable():
            from .paths import MODELS, DATA
            location.setText(f"模型目录：{MODELS}\n设置与断句资源：{DATA}")
        location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        location.setWordWrap(True)
        location.setObjectName("cardHint")
        layout.addWidget(location)
        sources = QLabel("下载来源：Argos、RapidOCR、SYSTRAN/faster-whisper、MiniSBD 和 Qwen 的官方发布。资源适用各自许可，详见包内 THIRD_PARTY_NOTICES.md。")
        sources.setWordWrap(True)
        sources.setObjectName("cardHint")
        layout.addWidget(sources)
        self.status = QLabel("首次下载需要联网。选择功能后点击「开始安装」。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(120)
        self.details.setPlaceholderText("安装步骤和失败原因会显示在这里。")
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.later_button = QPushButton("稍后安装" if first_run else "关闭")
        self.later_button.clicked.connect(self.reject)
        actions.addWidget(self.later_button)
        actions.addStretch()
        self.cancel_button = QPushButton("取消下载")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_install)
        actions.addWidget(self.cancel_button)
        self.start_button = QPushButton("开始安装")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_install)
        actions.addWidget(self.start_button)
        layout.addLayout(actions)
        self.basic.toggled.connect(self.refresh_plan)
        self.subtitles.toggled.connect(self._subtitle_changed)
        self.qwen_asr.toggled.connect(self._subtitle_changed)
        self.refresh_plan()

    def features(self):
        return tuple(key for key, box in (("basic", self.basic), ("subtitles", self.subtitles), ("qwen-asr", self.qwen_asr)) if box.isChecked())

    def _subtitle_changed(self, checked):
        required = self.subtitles.isChecked() or self.qwen_asr.isChecked()
        if required:
            self.basic.setChecked(True)
        self.basic.setEnabled(not required)
        self.refresh_plan()

    def refresh_plan(self):
        manager = ResourceManager()
        plan = manager.plan(self.features())
        missing = [r for r in plan if manager.installed_path(r) is None]
        self.summary.setText(f"已安装 {len(plan) - len(missing)}/{len(plan)} 项 · 还需下载 {byte_label(sum(r.size for r in missing))}")
        self.start_button.setEnabled(bool(plan))
        if not self.worker:
            self.start_button.setText("开始安装" if missing else "完成，开始使用")
        return missing

    def start_install(self):
        if self.worker:
            return
        if not self.refresh_plan():
            self._activate_downloaded_model()
            self.resources_installed.emit()
            self.accept()
            return
        self._outcome = "running"
        self._close_after_cancel = False
        self.details.clear()
        self.status.setText("正在准备资源…")
        self.start_button.setEnabled(False)
        self.later_button.setEnabled(False)
        self.basic.setEnabled(False)
        self.subtitles.setEnabled(False)
        self.qwen_asr.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.worker = InstallWorker(self.features(), self)
        self.worker.progress.connect(self._progress)
        self.worker.succeeded.connect(lambda: self._result("success", "资源安装完成，可以开始使用。"))
        self.worker.failed.connect(lambda message: self._result("failed", message))
        self.worker.cancelled.connect(lambda: self._result("cancelled", "已取消。已安装的资源和可续传的下载进度会保留。"))
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _progress(self, event):
        phase, name = event["phase"], event["resource"]
        prefix = f"{event['index']}/{event['count']} · {name}"
        labels = {"installed": "已就绪", "install": "正在安装", "verify": "正在校验", "retry": f"连接中断，自动重试 {event['attempt']}/2"}
        if phase == "download":
            done, total = event["done"], event["total"]
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(min(100, int(done * 100 / total)))
            self.status.setText(f"{prefix} · {byte_label(done)} / {byte_label(total)}")
        else:
            self.status.setText(f"{prefix} · {labels[phase]}")
            if phase in {"install", "verify"}:
                self.progress_bar.setRange(0, 0)
            if phase == "installed":
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(100)
            self.details.append(self.status.text())

    def _result(self, outcome, message):
        self._outcome = outcome
        self.status.setText(message)
        self.details.append(message)
        self.progress_bar.setRange(0, 100)

    def _finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.cancel_button.setEnabled(False)
        self.later_button.setEnabled(True)
        self.subtitles.setEnabled(True)
        from .qwen_asr import runtime_available
        self.qwen_asr.setEnabled(runtime_available())
        self.basic.setEnabled(not (self.subtitles.isChecked() or self.qwen_asr.isChecked()))
        self.refresh_plan()
        if self._outcome in {"failed", "cancelled"}:
            self.start_button.setText("重试安装")
        if self._outcome == "success":
            self._activate_downloaded_model()
            self.resources_installed.emit()
            preferences.put("setup.seen", True)
            self.progress_bar.setValue(100)
        if self._close_after_cancel:
            self.reject()

    def _activate_downloaded_model(self):
        if self.qwen_asr.isChecked():
            from .qwen_asr import QWEN_ASR_MODEL_PATH, select_model_folder
            try:
                select_model_folder(QWEN_ASR_MODEL_PATH)
            except (ValueError, OSError) as exc:
                self.status.setText(f"资源已安装，但模型目录未能保存：{exc}")

    def cancel_install(self):
        if self.worker:
            self.worker.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.status.setText("正在取消，请等待当前网络请求结束…")

    def reject(self):
        if self.worker:
            self._close_after_cancel = True
            self.cancel_install()
            return
        if self.first_run:
            preferences.put("setup.seen", True)
        super().reject()

    def accept(self):
        if self.worker:
            return
        preferences.put("setup.seen", True)
        super().accept()

    def closeEvent(self, event):
        if self.worker:
            self._close_after_cancel = True
            self.cancel_install()
            event.ignore()
        else:
            self.reject()
            event.accept()
