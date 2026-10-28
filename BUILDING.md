# 构建说明

## 发布版本

v1.0.15 面向 Windows 10/11 x64。Release 的 `QingshiSetup.exe` 是独立单文件安装包，内含设置中心及输入法运行时。安装与卸载共用同一程序入口。日常设置使用运行时目录中独立的 `settings/QingshiSettings.exe`，避免每次解压安装包。

## 获取源码

```text
git clone --recurse-submodules https://github.com/Vincentkeio/qingshi-wubi.git
cd qingshi-wubi
```

`weasel/librime` 和 `weasel/plum` 保留为指向上游固定版本的 Git 子模块。GitHub 自动生成的源码 ZIP 不含子模块内容；建议使用上述克隆方式。

## 原生组件

本地发布基线为 Visual Studio 2022 Build Tools、MSVC v143（14.44.35207）、Windows SDK 10.0.26100.0 和 Boost 1.84.0。需安装桌面 C++ 构建工具及 ATL 支持。

1. 在 `weasel/deps/boost_1_84_0` 准备 Boost 头文件和 x64 静态库（`stage/lib`）。
2. 准备 librime 的 x64 头文件、导入库和运行时。发布包使用 [librime 33e7814](https://github.com/rime/librime/commit/33e7814) 的 Windows MSVC 预编译产物，包含 Lua、octagram 和 predict 插件。
3. 将 librime 头文件放入 `weasel/include`，将 x64 `rime.lib` 放入 `weasel/lib64`，将 `rime.dll` 放入 `weasel/output`。依赖包的 OpenCC 数据放入 `rime-bin/rime-deps-33e7814-Windows-msvc-x64/share/opencc`。
4. 检查 `weasel/build_weasel_en.bat` 中的工具链和 SDK 版本与本机一致，再从命令提示符执行该脚本。该脚本会生成 `weasel.props` 并编译 x64 Release。
5. 确保 `weasel/output` 中有 `WeaselServer.exe`、`WeaselDeployer.exe`、`weaselx64.dll`、`rime.dll`、`start_service.bat`、`stop_service.bat` 和 `data/weasel.yaml`。不再使用 WinSparkle。
6. 执行 `weasel/build_ime.bat test`，构建 `qingshi_game.ime` 并验证窗口类、导出接口、UTF-16 结果和消息缓冲区。安装器先将此组件部署到 System32 并调用 ImmInstallIME，再从青石独立的系统目录注册 TSF，使其自动关联兼容布局；卸载仅移除青石自己的布局。

子模块记录上游源码基线；实际随包 librime 二进制版本以 `release-manifest.json` 记录的 revision 为准。仓库不包含本机下载缓存、Boost 库、编译中间产物及用户数据。

## 打包安装器

使用 Windows x64 **Python 3.11**（须与 PyQt6 的 sip 扩展 ABI 匹配），安装 [requirements-build.txt](requirements-build.txt) 后运行：

```text
python -m pip install -r requirements-build.txt
python build_installer.py
```

脚本先调用 `build_settings.py` 生成不含安装数据的目录式设置中心，再从 `weasel/output`、`pkg` 与该设置目录收集运行时及方案，添加第三方许可文件，生成带逐文件校验值的 `gui/payload.zip`，最后用 PyInstaller 打包。产物为 `dist/QingshiSetup.exe` 和 `dist/QingshiSetup.sha256`。

`pkg` 是当前发布配置；`build_pkg.py` 是早期方案生成工具，会重写已调整的方案和主题，修改配置前应保留现有文件。

## 本地检查

安装器自动化检查使用临时目录和模拟注册表，不修改当前安装：

```text
python -m unittest discover -s tests -p test_installer.py
python -m unittest discover -s tests -p test_game_compat.py
```

打包后的 Qt 依赖诊断：

```text
QingshiSetup.exe --diagnose-qt qt-diagnostic.json
```

实际安装、输入兼容性和卸载需在目标 Windows 环境中复核。版本发布不意味着所有第三方应用均已覆盖。
