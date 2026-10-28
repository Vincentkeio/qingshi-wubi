# 青石五笔

基于 [小狼毫 Weasel](https://github.com/rime/weasel) 的五笔输入法分支。

- 码表：五笔 **86 / 98 / 06** 三套，默认 86
- 底座：Weasel 1.0.6 fork，版本线 **1.0.7**
- 平台：Windows 8.1 ~ 11
- 许可证：**GPL-3.0**（继承自 Weasel）

---

## 相比原版小狼毫改了什么

### 1. 游戏里能用：TSF 组件装进系统目录

**原版问题**：带反作弊的游戏只加载 `C:\Windows\System32` 下的输入法 DLL。
装在 `Program Files` 里的 `weaselx64.dll` 压根不会被加载，游戏里连候选框都不出现。

**做法**：

- 安装时把 `weaselx64.dll` 复制进 `C:\Windows\System32\`
- **从 System32 那份**调用 `DllRegisterServer`，让 `InprocServer32` 指向系统目录
- 卸载时一并清理

**验证**：LOL 等游戏进程日志出现 `ActivateEx flags=0x00000004|UIELEMENTONLY` + `activated`。

### 2. 候选框右键菜单（原版没有）

右键点候选，弹出菜单：

| 菜单项 | 作用 |
|---|---|
| 固顶「词」 | 把该词提到本编码第一位 |
| 调整位置 → 调到第 N 位 | 把该词挪到指定位置 |
| 取消固顶，恢复原排序 | 还原引擎原始顺序 |
| 青石五笔设置… | 打开设置面板 |
| 重新部署 | 手动全量部署 |

**全部即时生效，不触发部署。** 原版点「固顶」走的是「改 custom_phrase + 重新部署」，
每次要等好几秒，还会弹「部署完成」提示。

### 3. 候选调序走独立的 shadow 层

规则存在 `%APPDATA%\QingshiWubi\shadow_<方案>.yaml`：

```yaml
version: 1
rules:
  "wqiy":
    - "仰泳"
  "ad":
    - "项目"
```

- **不改词库**，不动 `custom_phrase`
- **不触发部署器**，不重建 prism / table / reverse
- 排在候选装配的最后一步，晚于词频重排、不衰减
- 删掉对应编码即恢复默认顺序

### 4. 调序后候选框当场重排

原版候选顺序由引擎决定，改完要重新输入才看得到。

本项目的做法是**纯本地重排**：

```cpp
void CCandidateList::ReorderLocal(const std::wstring& word) {
  auto& candies = _ui->ctx().cinfo.candies;
  // 把 word 从原位移到第一位，同步维护「显示位置 → 引擎索引」映射
  _ui->Refresh();   // 只重排布局 + 重绘
}
```

`_ui->Refresh()` → `panel.Refresh()`：**不销毁窗口、不回调宿主 COM 接口**。

> 踩坑记录：走 `_UpdateUI` 会重入宿主的 `ITfCandidateListUIElement`。
> 在右键回调里调它，宿主进程会直接崩溃退出（记事本会整个消失）。

### 5. 选词键跟随界面顺序

重排只改了显示，引擎内部顺序没变，所以这几类选词键都要换算：

- **空格** → 上屏界面上第一个
- **数字 1–9** → 界面第 N 位
- **分号 `;` / 单引号 `'`** → 对应方案里 `alternative_select_keys: "1;'"` 的第 2、3 位

不换算的话，界面上「仰泳」排第一，按空格上屏的却是「你」。

### 6. 改外观不用重新部署

原版改 `weasel.yaml` 的字号、排列方向、配色、边距，必须重新部署才生效。

本项目：

- `UIImpl::Refresh()` 每次先把最新 `UIStyle` 推给面板（面板构造时只拷贝了一份，之后不跟随）
- 新增 `UI::ForceRefresh()`，清掉「内容没变就不重画」的缓存
- 改完设置 → `/reload` → 界面立刻变，不重启、不部署

### 7. 品牌化

显示名、语言栏、版本资源全部改为「青石五笔」，图标替换为自有 logo，
`app.toml` 的 `display_name` / `publisher` / `start_menu_folder` / `window_title` 同步。

---

## 安装

1. 运行 `QingshiSetup-x.y.z.exe`
2. **需要管理员权限**（要往 `System32` 写 DLL 并注册 COM）
3. 装完在语言栏里选「青石五笔」

用户数据目录：`%APPDATA%\QingshiWubi`

## 构建

需要 Visual Studio 2022（含 C++ 桌面开发）+ Windows SDK 10.0.26100。

```bat
build_weasel_en.bat
```

产物在 `output\`：`WeaselServer.exe`、`WeaselDeployer.exe`、`weaselx64.dll`。

> ⚠️ 这个脚本有时会**假报成功**（增量判断跳过了实际编译）。
> 改完代码请核对 `output\*.exe` 的时间戳，或 `touch` 源文件强制重编。

## 已知限制

- **CS2 等 Trusted Mode 游戏仍可能拒绝加载** —— 它们要求 DLL 有有效的
  **代码签名证书**（Authenticode / EV Code Signing，**不是** HTTPS 证书）。
  目前青石五笔未签名，需要采购 EV 代码签名证书并给 `weaselx64.dll` 签名。
- 卸载第三方输入法会留下「半死」注册项（TIP 注册还在、COM 类已删），
  会让 TSF 整条线程的输入法激活失败。排查游戏兼容时先看这里。

## 许可证

本项目基于 Weasel，整体以 **GPL-3.0** 分发；librime 部分为 BSD-3。
详见 `LICENSE.txt` 与 `librime/LICENSE`。

上游：[rime/weasel](https://github.com/rime/weasel) · [rime/librime](https://github.com/rime/librime) · 项目主页 [rime.im](https://rime.im)
