# 青石五笔输入法

基于 [小狼毫 Weasel](https://github.com/rime/weasel) 和 [Rime](https://github.com/rime/librime) 的 Windows 五笔输入法，内置五笔 86、五笔 98 和新世纪五笔，提供独立安装包和图形设置中心。

## 下载与安装

前往 **[最新版本](https://github.com/Vincentkeio/qingshi-wubi/releases/latest)**，下载 `QingshiSetup.exe`，双击并按向导安装。普通使用无需安装 Python 或开发工具。

- 系统：Windows 10 / 11，x64。
- 当前支持 64 位应用；32 位应用兼容性尚未提供。
- v1.0.7 整合游戏兼容入口及 TSF 关联，已由用户在《英雄联盟》训练模式确认候选词和中文上屏正常。其他游戏仍需分别验证。
- 安装后通过 `Win + 空格` 切换到「青石五笔」。已经打开的应用可能需要重新打开，以加载新的输入法组件。
- 右键输入法托盘图标，选择「青石五笔设置」，可切换方案、调整外观、管理词库和快捷键。
- 在 Windows「设置 → 应用」中卸载，可选择保留设置或删除青石用户数据。被应用占用的组件可能要在系统下次重启后才能清理。

Release 同时提供 `QingshiSetup.sha256`，可用 PowerShell 核对下载文件：

```powershell
Get-FileHash .\QingshiSetup.exe -Algorithm SHA256
```

## 功能

- 五笔 86、五笔 98、新世纪五笔三套方案。
- 86 版采用极点原版词库顺序，不自动按词频重排。
- 图形设置中心：常用设置、外观、词库、自定义词条、快捷键、关于。
- 简繁转换、全角半角、中英文标点切换。
- 自定义词条、候选词固顶及取消固顶。
- Shift 键行为和 Shift + 字母直接输出可设置。
- 独立安装、升级及卸载，安装时保留已有用户词条。

默认常用快捷键：

| 操作 | 快捷键 |
| --- | --- |
| 切换 Windows 输入法 | Win + 空格 |
| 简繁切换 | Ctrl + Shift + F / Ctrl + Shift + T |
| 全角 / 半角 | Shift + 空格 |
| 中英文标点 | Ctrl + . |
| 第二 / 第三候选 | `;` / `'` |

## 源码与构建

```text
gui/                设置中心、安装向导和安装/卸载实现
pkg/                随包提供的三套方案、词典及默认配置
sources/            词典转换的原始输入
include/            青石原生组件公共头文件
weasel/             基于上游修改的 Windows 输入法源码
tests/              安装器及原生组件测试
build_installer.py  单文件 EXE 打包入口
```

请参阅 [构建说明](BUILDING.md) 和 [第三方来源与许可](THIRD_PARTY_NOTICES.md)。

问题反馈请使用 [Issues](https://github.com/Vincentkeio/qingshi-wubi/issues)，附上 Windows 版本、所用应用、输入方案和复现步骤。

## 许可

项目包含基于 Weasel 的修改，按 [GNU GPL v3](LICENSE) 发布。各第三方组件和词典保留各自原有的许可及权利声明，详见 [第三方来源与许可](THIRD_PARTY_NOTICES.md)。
