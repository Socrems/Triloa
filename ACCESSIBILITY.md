# Accessibility / 无障碍说明

These notes describe the current implementation as of **2026-10-16**. Triloa primarily targets **Windows 11 x64 and Microsoft Edge**. Other platforms have not been verified. Full screen-reader compatibility and WCAG conformance have not been established.

本说明记录截至 **2026-10-16** 的当前实现。Triloa 主要面向 **Windows 11 x64 与 Microsoft Edge**，其他平台尚未验证。目前尚未确认完整的屏幕阅读器兼容性或 WCAG 符合性。

## Available controls / 已有操作

- **Desktop translation:** press `Ctrl+Enter` to translate text in the main window.
- **Extension floating ball:** Tab focus expands its controls; buttons support Enter and Space. Visible focus indicators and ARIA labels/states are provided. Escape closes the expanded controls/settings and returns focus to the ball. Its transitions and animations respect `prefers-reduced-motion`.
- **Subtitle overlay:** the window does not accept keyboard focus. When unlocked, moving and resizing use pointer controls; equivalent keyboard controls have not been established.

- **桌面文字翻译：**在主窗口按 `Ctrl+Enter` 可翻译文字。
- **扩展悬浮球：**用 Tab 聚焦可展开操作，按钮支持 Enter 与空格。已有可见焦点提示及 ARIA 标签和状态。Escape 可收起展开的操作或设置，并把焦点返回悬浮球。其过渡和动画遵循 `prefers-reduced-motion` 设置。
- **字幕悬浮窗：**窗口不接受键盘焦点。解锁后移动与缩放依赖指针操作，目前尚未建立等效的键盘操作。

These features do not verify the accessibility of every desktop dialog, translated webpage, or assistive-technology combination. OCR, speech recognition, and translation can also contain errors.

上述功能不代表每个桌面对话框、翻译后的网页或辅助技术组合都已通过无障碍验证。OCR、语音识别和翻译结果也可能存在错误。

## Report a barrier / 报告使用障碍

Use a [bug report](https://github.com/Socrems/Triloa/issues/new?template=bug_report.md) in English or Chinese. Describe the task, where focus or interaction fails, steps, and expected versus actual behavior. Include the Triloa and Windows versions, Edge version for extension issues, and assistive technology/version if relevant. Details about keyboard-only use, display scaling, contrast, or motion preferences can help when related. Screenshots or recordings are optional; remove personal information first.

可使用中文或英文提交[问题报告](https://github.com/Socrems/Triloa/issues/new?template=bug_report.md)。请说明要完成的任务、焦点或交互受阻的位置、步骤及预期与实际行为，并提供 Triloa 和 Windows 版本；扩展问题可补充 Edge 版本，相关时注明辅助技术及其版本。纯键盘使用、显示缩放、对比度或动态效果设置等信息仅在相关时提供。截图或录屏为可选，请先移除个人信息。

Accessibility improvements are welcome through [contributions](CONTRIBUTING.md). Reports help identify barriers but do not carry a guaranteed resolution date.

欢迎通过[贡献](CONTRIBUTING.md)改善无障碍体验。报告有助于定位障碍，但不代表承诺具体解决日期。
