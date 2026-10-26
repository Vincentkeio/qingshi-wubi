# 第三方来源与许可

青石五笔在以下开源项目基础上构建，保留原作者与项目的权利声明。

| 项目 | 用途 | 许可 / 来源 |
| --- | --- | --- |
| Weasel / 小狼毫 | Windows TSF、候选窗、服务及部署工具 | [GPL-3.0](weasel/LICENSE.txt)，[上游](https://github.com/rime/weasel)，源码基线 `82b50c9e9b9ee0bd31357db6f25ddc804546c7f7`，青石修改保存在本仓库 |
| librime | 输入引擎 | [BSD-3-Clause](https://github.com/rime/librime/blob/33e7814/LICENSE)，发布二进制 revision `33e7814` |
| OpenCC | 简繁转换和转换数据 | [Apache-2.0](https://github.com/BYVoid/OpenCC/blob/master/LICENSE) |
| yaml-cpp | YAML 解析 | [MIT](https://github.com/jbeder/yaml-cpp/blob/master/LICENSE) |
| LevelDB | 数据存储 | [BSD](https://github.com/google/leveldb/blob/main/LICENSE) |
| Boost | C++ 库，1.84.0 | [Boost Software License 1.0](https://www.boost.org/LICENSE_1_0.txt) |
| WinSparkle | 上游运行时组件 | [上游许可](https://github.com/vslavik/winsparkle/blob/master/COPYING) |
| PyQt6 / Qt | 设置中心和安装器界面 | [PyQt6 GPL v3](https://www.riverbankcomputing.com/software/pyqt/)，[Qt 许可](https://www.qt.io/licensing/open-source-lgpl-obligations)；本发布采用开源许可 |
| PyInstaller | 单文件封装 | [GPL 及打包例外](https://pyinstaller.org/en/stable/license.html) |
| CPython | Python 运行时 | [PSF License](https://docs.python.org/3/license.html) |

## 词典

- 五笔 86：极点原版极爽 4.3（2011），来源项目 [KyleBing/wubi-jidan-dict](https://github.com/KyleBing/wubi-jidan-dict)。转换后保留原词序。
- 五笔 98、新世纪五笔：原始输入保存在 `sources/wubi_other`，原始作者和来源声明保留在对应词典文件头中。
- 五笔字型及各词典的权利归原权利人所有；项目代码许可不替代第三方词典的原有声明。

安装载荷包含 Weasel、librime、OpenCC、yaml-cpp 和 LevelDB 的许可原文，位于安装目录的运行时 `licenses` 子目录。上游依赖的其他声明请参阅各自源码及发行包。
