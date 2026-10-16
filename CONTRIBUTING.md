# Contributing / 参与贡献

English and Chinese reports, documentation improvements, and code contributions are welcome. Please follow the [code of conduct](CODE_OF_CONDUCT.md). For suspected vulnerabilities, read the [security policy](SECURITY.md) before sharing any details.

欢迎使用中文或英文报告问题、改进文档或贡献代码。请遵守[行为准则](CODE_OF_CONDUCT.md)；发现疑似漏洞时，请先阅读[安全政策](SECURITY.md)，再决定如何提供信息。

## Reports and proposals / 报告与建议

Search existing issues first, then describe the problem or use case, reproduction steps, and expected versus actual behavior. Include the Triloa version and relevant environment. Model, CPU/GPU, playback device, or browser details are useful only when related to the issue. For subtitle delays, distinguish recognition from translation and say whether timing includes model loading. Accessibility reports are welcome; see [accessibility notes](ACCESSIBILITY.md).

请先搜索已有议题，再说明问题或使用场景、复现步骤、预期与实际行为，并提供 Triloa 版本及相关环境。模型、CPU/GPU、播放设备或浏览器信息仅在与问题相关时填写。字幕延迟请区分识别与翻译，并说明是否包含模型加载时间。欢迎报告无障碍问题，参见[无障碍说明](ACCESSIBILITY.md)。

## Branches and setup / 分支与安装

Open code pull requests against **`development`**. **`main`** contains the source installation entry points and user documentation; tests and build tools are maintained on `development`. These community documents should stay identical on both branches. For setup, use the [source installation guide on development](https://github.com/Socrems/Triloa/blob/development/docs/SOURCE_INSTALL.md).

代码拉取请求请以 **`development`** 为目标分支。**`main`** 提供源码安装入口与用户文档；测试和构建工具放在 `development`。两条分支的这些社区文档应保持一致。安装步骤见 [development 分支的源码安装说明](https://github.com/Socrems/Triloa/blob/development/docs/SOURCE_INSTALL.md)。

Keep each change focused and explain what it changes and why. Describe how you checked it, including any checks you could not run. For documentation changes, check the wording and links; tests or a package rebuild are not required solely for documentation.

请让每项修改范围清晰，说明改了什么、为什么修改，以及如何验证，包括未能运行的检查。文档修改应检查文字与链接；仅修改文档无需运行测试或重新打包。

## Relevant checks / 按改动选择检查

After setting up the development branch, run checks relevant to the changed behavior. Examples:

完成 development 分支的环境安装后，按受影响的行为选择检查，例如：

```powershell
# Python regressions / Python 回归
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q

# Resource installation changes / 资源安装改动
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_resources.py

# Extension checks: choose affected areas / 扩展检查：选择受影响部分
node tests/test_extension_cache.js
node tests/test_extension_inline.js
node tests/test_extension_popup.js
node tests/test_extension_ball.js

# Whitespace / 空白字符
git diff --check
```

Node.js is used for extension checks; it is not a desktop runtime requirement. Automated checks do not replace manual verification when a change affects playback, installation, keyboard operation, or window behavior. Record the relevant result; repeat checks when new changes or failures warrant it.

Node.js 用于扩展检查，不是桌面程序的运行依赖。改动涉及播放、安装、键盘操作或窗口行为时，自动检查不能替代相关的手动验证。请记录相关结果，并在新修改或失败确有需要时重跑。

## Privacy and licensing / 隐私与许可

Submit only relevant source, documentation, and necessary tests. Keep credentials, `.env` files, personal handoff notes, settings, logs, private screenshots, Python environments, model weights, runtime libraries, and release packages out of commits. Redact personal paths, page content, and other private data from reports; share only what is needed to reproduce the issue.

仅提交相关源码、文档和必要测试。不要提交凭据、`.env`、个人交接记录、设置、日志、私密截图、Python 环境、模型权重、运行库或发布包。报告问题时请遮盖个人路径、网页内容及其他私人信息，只提供复现所需材料。

Project-owned source is licensed under [MIT](https://github.com/Socrems/Triloa/blob/main/LICENSE). Keep required copyright notices, identify third-party sources, and retain their applicable licenses. Third-party models and runtime libraries have their own terms.

项目自有源码采用 [MIT 许可证](https://github.com/Socrems/Triloa/blob/main/LICENSE)。请保留必要的版权告知，注明第三方来源，并保留其适用许可。第三方模型与运行库适用各自条款。
