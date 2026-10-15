# 从源码启动与高级模型

此页供源码使用者和开发者参考。普通用户请先看 [首页的便携包使用步骤](../README.md)。

面向英语、日语阅读与视频学习的 Windows 本地翻译工具，统一提供屏幕 OCR、网页视口翻译和实时双语字幕。

**当前版本：v0.1.4，本地审核中。** 程序与浏览器扩展内部版本均为 `0.1.4`，后续标签采用 `vX.Y.Z` 格式。首版内部版本为 `0.1.0`，历史标签为 `v0.1`。项目自有源码采用 [MIT](../LICENSE) 许可证。

## 功能

- **文字翻译**：输入文字、读取剪贴板，显示原文和中文；支持复制、清空和取消。
- **屏幕翻译**：框选文字进行 OCR，也可持续监视选定区域；画面变化时更新译文悬浮窗，支持拖动、缩放和固定。
- **网页翻译**：Edge 扩展按网站开启，在可见正文、标题和列表项下方显示中文，保留原文。切换翻译模型或重启本地服务后自动清理旧译文缓存。
- **实时字幕**：识别 Windows 播放设备的系统声音，上半显示原文、下半显示中文；提供独立的会话历史、文字选择、清空和回到最新。
- **本地模型**：保留 HY-MT / Qwen / Argos，支持添加多个自选 GGUF 翻译或对话模型并保存配置；Nemotron / faster-whisper 语音识别。各翻译功能共用所选模型。
- **桌面操作**：托盘、窗口状态记忆、可配置的全局快捷键。默认 `Ctrl+Alt+T` 框选、`Ctrl+Alt+C` 翻译剪贴板、`Ctrl+Alt+S` 显示或隐藏字幕。

Word、PDF 和图片通过屏幕 OCR 处理当前可见内容。网页扩展支持普通网页的 `p`、`h1`–`h6` 和 `li`，滚动后继续翻译；浏览器 PDF、复杂控件和表格可使用屏幕翻译。

## 安装条件

- Windows 11 x64；其他 Windows 版本和平台尚未验证。
- Python **3.11–3.13 x64**，建议 3.12。可从 [Python 官网](https://www.python.org/downloads/windows/) 安装并加入 PATH，也可以在安装脚本中指定已有 Python。
- 首次安装需要联网获取 Python 依赖及所选模型，之后已有本地模型可以离线推理。
- Argos 翻译和 faster-whisper 识别可以使用 CPU。HY-MT / Qwen 的快捷安装脚本使用 llama.cpp CUDA 12.4 预编译运行库，需要兼容的 NVIDIA 显卡驱动；该脚本无需安装完整 CUDA Toolkit。
- 磁盘空间取决于选择的模型。源码很小，依赖和模型可能需要数 GB；HY-MT Q8_0 文件约 1.91 GB，Qwen3-4B Q4_K_M 文件约 2.50 GB。

源码仓库和源码 ZIP 包未包含 EXE、Python 环境、模型或第三方运行库。

## 从源码启动

将源码解压或克隆到可写目录，在该目录打开 PowerShell。目录可以位于 D 盘或其他数据盘；安装脚本会将环境、模型及主要缓存放在项目目录内。

### 1. 安装基础功能

确认 `python --version` 显示受支持版本，然后运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
```

`setup.ps1` 安装桌面、OCR 和 Argos 依赖，并获取英语→中文、日语→英语、断句和 OCR 资源。Argos 的日语翻译会经英语转译为中文。已存在的资源会复用，缺失项也可通过界面“资源管理”安装。

如果 Python 没有加入 PATH，使用 `setup.ps1 -Python` 指定已有解释器的完整路径。安装脚本会检查 Python 的版本与位数，不依赖 Anaconda。

### 2. 安装系统声音字幕（可选）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_speech.ps1
```

脚本安装语音依赖、多语言 faster-whisper base、语音检测及基础翻译资源。然后在桌面程序的“实时字幕”页选择识别模型、语言及播放设备，并开始字幕。也可单独运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_subtitles.ps1
```

faster-whisper 默认使用 CPU。如使用 small 模型，将对应的 CTranslate2 模型目录放入 `models/faster-whisper/small/`，其中应包含 `model.bin` 等完整模型文件。程序只读取已有模型，运行时不会自动下载缺失模型。

### 3. 安装 HY-MT（可选）

先阅读 [Tencent HY Community License](https://github.com/Tencent-Hunyuan/HY-MT/blob/main/License.txt)。该许可将适用地域排除欧盟、英国和韩国，并包含使用与分发条件。确认你的使用符合该模型许可后运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_hy.ps1
```

脚本获取 HY-MT1.5-1.8B Q8_0 和固定版本的 llama.cpp CUDA 运行库。下载并校验后，默认翻译后端优先使用 HY-MT；模型或服务不可用时退回 Argos。首次使用需要加载模型。

已有官方 GGUF 可放在 `models/hy-mt/HY-MT1.5-1.8B-Q8_0.gguf`，再运行以下命令进行 SHA256 校验并生成校验标记；完整文件只校验：

```powershell
.\.venv\Scripts\python.exe -B -m triloa.download_hy_model
```

若需要强制使用 Argos，可在启动前设置：

```powershell
$env:TRILOA_TRANSLATOR = 'argos'
```

### 4. 使用 Qwen（可选）

从 [Qwen 官方 GGUF 模型页](https://huggingface.co/Qwen/Qwen3-4B-GGUF) 获取 Qwen3-4B GGUF，例如 `Qwen3-4B-Q4_K_M.gguf`，放入 `models/qwen3/`；也可在“管理模型”菜单点击“添加 GGUF”，把不同 Qwen 文件分别保存到选择列表。

Qwen 和 HY-MT 共用 `runtime/llama/llama-server.exe` 及对应 DLL。已有 HY-MT 安装可复用运行库；只使用 Qwen 时，也可从 [脚本所用的 llama.cpp 发布版本](https://github.com/ggml-org/llama.cpp/releases/tag/b10964) 获取 Windows CUDA 12.4 x64 程序包及配套 CUDA 运行库，解压后确保可执行文件和所需 DLL 位于 `runtime/llama/`。

主窗口顶部选择 Qwen 后，文字、屏幕、网页及字幕翻译都会使用它。原有 Qwen 文件配置仍可使用。模型出错会提示；翻译进行中或字幕启动后暂时不能切换或修改模型，请先停止并等待任务结束。

### 5. 添加其他本地 GGUF 翻译模型（v0.1.1 起）

1. 从模型发布者处下载兼容本机 [llama.cpp](https://github.com/ggml-org/llama.cpp) 的 GGUF 翻译或对话模型。请选择能够输出中文译文、带有适用对话模板的模型，并按其许可证使用。
2. 准备 `runtime/llama/llama-server.exe` 及配套 DLL。已有 HY-MT / Qwen 运行库可以复用；只使用自选模型时，可从 [llama.cpp 发布页](https://github.com/ggml-org/llama.cpp/releases) 获取兼容的 Windows x64 CPU 或对应显卡程序包。无需为了添加自选模型而下载 HY-MT 权重。
3. 在主窗口顶部“管理模型”菜单点击“添加 GGUF”，选择文件，填写显示名称。
4. 选择模型类型：普通模型选“通用对话模型”，由 llama.cpp 使用文件自带的模板；Qwen 可选“Qwen · 关闭思考”，HY-MT 可选对应翻译配置。文件名含 Qwen / HY-MT 时会预选相应类型，仍可手动修改。
5. 选择运行方式：默认自动分配显卡和内存，也可选“仅 CPU”。点击“保存并使用”，之后可以在下拉列表中切换已添加的模型。

支持保存多个不同模型文件，重复添加同一路径会更新已有记录。名称、路径、模型类型、运行方式和当前选择保存在本地设置，重启后恢复；添加模型只记录路径，不复制或自动下载权重。文件可以放在其他数据盘或文件夹，移动后在“管理模型”的“模型设置”中重新选文件。“移除”只移除列表记录，保留模型文件；移除当前模型后恢复默认 HY-MT / Argos 选择。

所选模型用于文字、剪贴板、屏幕 OCR、网页和字幕翻译。字幕运行或有翻译任务时无法切换、添加、编辑或移除模型。明确选定的自选模型或 Qwen 加载失败时会报错；默认 HY-MT 的 Argos 备用逻辑保留。网页扩展通过现有模型标识自动更新译文缓存。

GGUF 是文件格式；具体架构是否支持仍取决于本机 llama.cpp 版本，较新的模型可能需要更新运行库。基础预训练模型、纯嵌入模型和必须输出长篇思考的模型不一定适合直接翻译。此版本仅接入本地 GGUF 文本模型；语音模型选择方式保持现有支持范围。加载失败可查看 `cache/llama-server.log`，该日志仅保留在本机。

### 6. 使用 Nemotron（可选）

先安装语音依赖，再按 [NeMo-Speech.cpp 官方说明](https://github.com/NVIDIA/NeMo-Speech.cpp) 获取兼容的 Windows 运行库和对应 GGUF 模型：

- 模型：`models/nemotron/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf`
- 程序：`runtime/nemo-speech/bin/nemo-speech.exe`

只有两者均存在时界面才会启用 Nemotron。程序不会自动下载这组文件。模型与运行库的许可分别核对，见 [第三方说明](../THIRD_PARTY_NOTICES.md)。

## Qwen3-ASR-0.6B（可选）

源码环境先运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_qwen_asr.ps1
```

再从首页“资源管理”勾选 Qwen3-ASR，下载约 1.88 GB 的官方模型，成功后会自动填好目录。已有模型时在字幕页“模型目录”点击“选择文件夹”，需包含配置、处理器、词表、提示模板和 Safetensors 权重；这不是 GGUF 文本模型。内置下载目录为 `models/qwen3-asr`，选择外部目录不会复制权重。

字幕页选择 Qwen3-ASR、识别语言和声音来源后开始。支持英语、日语及自动检测，识别结果仍使用首页选定的翻译模型。整句模式在句末识别；实时模式按累积音频片段更新草稿。这是 Windows Transformers 实现，不是 vLLM 原生流式接口。CPU 可运行但未保证低延迟；源码环境安装 CUDA PyTorch 时自动使用 CUDA，便携包使用 CPU。没有安装对齐模型、vLLM 或演示网页依赖。

NVIDIA 显卡加速（源码版，可选）：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_qwen_cuda.ps1
```

该脚本将 PyTorch 2.14.0 + CUDA 13.0 安装到项目内的 `runtime/qwen-cuda`，验证显卡后写入就绪标记；不替换主虚拟环境的 CPU PyTorch。安装及下载缓存放在项目目录，CUDA wheel 约 1.99 GB，解压和缓存需额外空间。无需安装完整 CUDA Toolkit，需兼容的 NVIDIA 驱动。完全退出旧实例后重新运行 `run.ps1`，源码版会优先读取该运行目录。普通便携包使用随附 CPU 依赖。检查启动后的字幕状态是否显示“CUDA”。

Qwen3-ASR 的当前识别提示没有启用文本模型的思考流程；译文的 Qwen 提示配置已关闭思考。识别延迟还受硬件、音频分段及翻译处理耗时影响。

## Edge 扩展

1. 启动桌面程序，或单独启动本地翻译服务。
2. 打开 `edge://extensions`，启用开发人员模式，选择“加载解压缩的扩展”并指向源码根目录下的 `extension`。
3. 点击扩展图标，开启当前网站的翻译开关；可在设置中开启全局悬浮球。

每个网站默认关闭。开启后译文出现在原文下面；关闭后清理插入的节点。逐网站开关保存在扩展本地存储。悬浮球默认关闭，启用后单击切换本站翻译与原文，悬停或键盘聚焦展开操作；支持拖动、左右吸边与跨网站高度记忆，本站隐藏仅隐藏球。更新后需要重新加载扩展；普通 HTTP(S) 页面支持补充注入，受限页面不支持，已打开的 v0.1.3 页面若保留旧脚本则仍需刷新。详细说明见 [extension/README.md](../extension/README.md)。

单独启动本地服务：

```powershell
.\.venv\Scripts\python.exe -m triloa serve
```

## 数据与隐私

翻译和语音推理在本机执行。本地网页翻译服务仅监听 `127.0.0.1:8765`；llama.cpp 使用 `127.0.0.1:8766`，Nemotron 也使用回环地址。程序启动这些本地服务时不会将其监听到外部网络。

- 桌面设置保存于 `data/preferences.json`；错误日志和可选的启动诊断日志可能包含文件路径或错误详情。
- 字幕历史与翻译缓存仅保留在会话内存中，退出后不保存字幕原文和译文。
- Edge 扩展将已开启网站的可见段落发送到本机服务，不向翻译服务发送网页 URL；逐网站设置会在浏览器本地保存。
- 首次安装及用户主动下载模型需要访问依赖或模型托管服务。这与运行时的本地翻译不同。
- 本地设置、缓存、日志、模型及运行库被 Git 忽略。反馈问题或制作发行包时，请自行核对要分享的文件。

## 本地目录

| 目录 | 内容 |
|---|---|
| `.venv/` | 项目 Python 环境 |
| `models/` | 翻译、OCR 和语音模型，具体缓存位置由组件决定 |
| `runtime/` | 手动或脚本安装的原生运行库 |
| `cache/` | 临时文件、pip、模型下载缓存和构建缓存 |
| `data/` | 设置、Argos 数据和错误日志 |
| `downloads/` | 下载分片及运行库压缩包 |
| `dist/` | 本地构建产物 |

Portable 构建默认将设置保存在程序目录的 `data`；旧 Full/Common 文件夹版的数据路径继续保留，独立移动时默认使用目录旁的 `<程序目录名>Data`。也可使用环境变量 `TRILOA_DATA_DIR` 指定位置。Windows、驱动和浏览器仍可能产生各自的系统缓存。

## 本地构建 Windows 文件夹版

构建不含模型的便携包，先安装基础与语音 Python 依赖，再运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1 -Profile Portable
```

生成 `dist/Triloa-Portable/Triloa.exe`，不会修改已有 `dist/Triloa`。脚本移除依赖内的 OCR、VAD 和示例模型；保留实际软件包的许可清单。如果已有 `runtime/llama`，仅带入 CPU 服务与所需 DLL。构建脚本可用 `-Python` 指定已有虚拟环境，也可用 `-SourceRoot` 指定公开源码目录。

安装基础和语音依赖，以及构建所需模型和运行库后，运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1
```

生成 `dist/Triloa/Triloa.exe`。必须保留整个产物文件夹。脚本会带入已有模型和运行库，同盘时优先使用硬链接；移动或压缩后体积由实际包含的文件决定。

`build_exe.ps1 -Profile Common` 生成 `dist/Triloa-Common/`，仅带 HY-MT 与 Nemotron 模型，但保留 Python 依赖。这仍是包含模型的构建方式。

构建脚本用于本地使用。对外提供包含依赖或模型的二进制包前，需核对全部实际打包组件的许可证、版权告知及必要源代码提供义务；根目录 MIT 文件仅授权 Triloa 自有代码。[第三方说明](../THIRD_PARTY_NOTICES.md) 列出主要组件和官方来源。

## 当前限制

- OCR 对低清晰度、复杂排版和日文小字可能误识别；多栏排序是启发式处理。
- 语音捕获播放设备的混音，音乐和音效可能触发识别；尚未完成不同播放器与连续真实视频的全面验证。
- 模型加载、语音识别和翻译都会影响延迟，不保证固定刷新时间。Nemotron 的过期定稿可能被跳过并提示，以减少字幕积压。
- 已开始的单次模型推理不能强制中断；取消操作会丢弃结果并跳过后续任务。
- 首版尚未完成全新电脑上的完整安装验证。

开发与回归方法见 [CONTRIBUTING.md](../CONTRIBUTING.md)，版本变化见 [CHANGELOG.md](../CHANGELOG.md)。

## 许可

Copyright (c) 2026 Triloa contributors。Triloa 源码采用 [MIT](../LICENSE)；第三方软件和模型按各自许可使用，不受该 MIT 文件重新授权。项目与所链接的模型提供方无隶属、赞助或背书关系。
