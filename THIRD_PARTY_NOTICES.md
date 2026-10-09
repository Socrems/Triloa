# 第三方软件与模型

v0.1.1 可添加用户自行下载的 GGUF 文本模型。Triloa 只记录其本地路径，源码包不包含这些权重。自选模型的许可、用途和分发条件应以其原始发布者的说明为准，项目 MIT 许可证只适用于 Triloa 自有代码。

Triloa 自有源码采用根目录的 [MIT 许可证](LICENSE)。本文件列出主要依赖及官方许可来源，不将第三方组件重新授权为 MIT。

源码包包含项目代码、文档和图标，不包含已安装的 Python 软件包、模型权重或原生运行库。安装时获取的第三方文件应保留其原有版权与许可。

## 直接 Python 依赖

以下版本来自项目 requirements 文件；许可标识核对所对应安装包的官方元数据。

| 组件 | 版本 | 安装包声明的许可 | 官方来源 |
|---|---|---|---|
| PySide6 / Qt for Python | 6.9.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only；Qt 各模块及附带库另有许可 | [Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html) |
| Argos Translate | 1.11.0 | MIT（包元数据 License classifier） | [Argos Translate](https://github.com/argosopentech/argos-translate) |
| RapidOCR | 3.9.2 | Apache-2.0 | [RapidOCR](https://github.com/RapidAI/RapidOCR) |
| ONNX Runtime | 1.30.0 | MIT | [ONNX Runtime](https://github.com/microsoft/onnxruntime) |
| SoundCard | 0.4.6 | BSD-3-Clause | [SoundCard](https://github.com/bastibe/SoundCard) |
| faster-whisper | 1.2.1 | MIT | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) |

安装还会解析传递依赖，例如 CTranslate2、Hugging Face Hub、NumPy 等；具体版本和许可应以实际下载的包为准。以上清单不是包含全部依赖的二进制发行包许可清单。PySide6 自带的 Qt Addons、Essentials 和其他库也应逐项核对；项目使用某个 Qt 模块，不代表整个软件包的所有文件都适用同一许可。

## 模型与原生运行库

| 组件 | Triloa 使用方式 | 许可与官方来源 |
|---|---|---|
| HY-MT1.5-1.8B Q8_0 GGUF | 可选本地翻译模型；安装脚本从腾讯 ModelScope 镜像获取，SHA256 固定在下载器中 | [官方模型页](https://huggingface.co/tencent/HY-MT1.5-1.8B-GGUF)、[Tencent HY Community License](https://github.com/Tencent-Hunyuan/HY-MT/blob/main/License.txt) |
| Qwen3-4B GGUF | 用户自行获取并选择本地 GGUF；不自动下载 | [官方 GGUF 模型页](https://huggingface.co/Qwen/Qwen3-4B-GGUF) 当前声明 Apache-2.0；核对所下载文件对应修订的许可 |
| Argos 模型包 | 安装脚本读取 Argos 官方索引并获取 en→zh、ja→en 包 | [Argos 模型索引仓库](https://github.com/argosopentech/argospm-index)；模型包自身、训练数据和软件引擎许可应分别核对 |
| RapidOCR / PP-OCR 模型 | OCR 组件使用本地已有或首次获取的模型资源 | [RapidOCR](https://github.com/RapidAI/RapidOCR)、[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)；保留实际模型来源和随附许可 |
| faster-whisper base / small | 本地 CTranslate2 格式的 Whisper 模型 | [base](https://huggingface.co/Systran/faster-whisper-base)、[small](https://huggingface.co/Systran/faster-whisper-small)、[Whisper](https://github.com/openai/whisper)；核对对应模型卡与转换来源 |
| Nemotron 3.5 Streaming 0.6B | 手动安装的本地 GGUF 语音模型 | [NVIDIA 官方模型页](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) 当前声明 OpenMDW-1.1；还应核对实际下载版本和 GGUF 转换来源的告知 |
| llama.cpp | 用于 HY-MT / Qwen GGUF；快捷脚本使用 b10964 CUDA 12.4 x64 包 | [llama.cpp](https://github.com/ggml-org/llama.cpp) 采用 MIT；预编译包中的 CUDA、OpenMP 等组件按各自许可 |
| NeMo-Speech.cpp | 用户手动获取的 Nemotron 原生运行库 | [NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp) 及对应构建的 LICENSE、NOTICE、第三方许可文件；运行库与模型许可分别核对 |

## HY-MT 使用注意

2026-10-09 核对的官方 HY-MT1.5 许可文本标明发行日期为 2025-12-30。其适用地域排除欧盟、英国和韩国，并附带可接受使用政策、分发告知等条件。下载、运行、部署或分发前，请阅读上表链接的完整协议；本项目的 MIT 许可不能替代该协议。

官方协议还包含向最终用户披露实际服务提供方及说明其与腾讯不存在关联或背书关系的要求。若你部署服务或制作含该模型的产品，请按实际提供方身份落实这些条件；本源码包的 contributors 署名不替代该项披露。

Triloa 是独立项目，与腾讯及其他模型或软件提供方无隶属、赞助或背书关系。这里的名称和链接用于标明可选后端来源。

## 制作二进制发行包

对外分享 EXE 文件夹时，需对实际包含的每个软件包、模型、DLL 和运行库进行许可核对，保留随附 LICENSE、NOTICE 及版权告知；根据对应许可提供必要的源代码、修改信息或其他材料。构建脚本复制 Triloa 的许可说明，并不能自动完成第三方发行义务。

本源码首版不分发上述权重和原生运行库。后续的二进制包应提供与该包实际内容一致的独立许可清单。
