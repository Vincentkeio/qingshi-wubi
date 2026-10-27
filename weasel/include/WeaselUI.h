#pragma once
#include <WeaselIPCData.h>
#include <functional>
#include <memory>
#include <string>
#include <windows.h>
#include <wrl.h>

namespace weasel {
using namespace Microsoft::WRL;

template <typename T>
using an = std::shared_ptr<T>;
template <typename T>
using the = std::unique_ptr<T>;
typedef std::function<
    void(size_t* const, size_t* const, bool* const, bool* const)>
    UICallbackFunc;

// 候选调序请求：index 是「界面上看到的」序号，action 见 WEASEL_SHADOW_ACTION。
// 由服务端注册，候选窗右键菜单直接调它 —— 走内存里的 shadow 层，
// 不再触发「改词库 + 重新部署」那条慢路径。
typedef std::function<void(size_t index, int action)> ShadowActionFunc;

// 候选窗右键「固顶」用。走进程级全局回调而不是 UI 成员引用：
// 面板是在 UI 里构造的，而回调是服务端 handler 之后才注册的，
// 用成员引用时两边生命周期容易对不上（实测拿不到回调、退回全量部署）。
// 面板与 handler 同在 WeaselServer 进程里，全局变量最省事也最可靠。
void SetGlobalShadowAction(const ShadowActionFunc& func);
// 定义在 WeaselUI.cpp（那个 obj 一定会被链接）；面板直接读它。
extern ShadowActionFunc g_shadow_action;
// 调序后的延迟刷新：面板收到 WM_APP+0x51 时调它，
// 由 TSF 侧注册（取回新候选并重绘）。必须在消息循环里执行，
// 不能在右键回调里同步重绘 —— 那会重入窗口过程把宿主带崩。
typedef std::function<void()> ShadowRefreshFunc;
extern ShadowRefreshFunc g_shadow_refresh;
#define WEASEL_WM_SHADOW_REFRESH (WM_APP + 0x51)

enum ClientCapabilities {
  INLINE_PREEDIT_CAPABLE = 1,
};

class UIImpl;
class UI {
 public:
  UI();
  virtual ~UI();
  // 创建输入法界面
  bool Create(HWND parent, bool preview_mode = false);
  // 销毁界面
  void Destroy(bool full = false);
  // 界面显隐
  void Show();
  void Hide();
  void ShowWithTimeout(size_t millisec);
  BOOL IsCountingDown() const;
  BOOL IsShown() const;
  // 重绘界面
  void Refresh();
  // 样式变了（配置热更新）时用：清掉内容缓存再重建，绕开 Update 的「内容没变就不重画」。
  void ForceRefresh();
  // Reattach an undragged preview window to its parent dialog.
  void RepositionPreview();
  // 置输入焦点位置（光标跟随时移动候选窗）但不重绘
  void UpdateInputPosition(RECT const& rc);
  // 更新界面显示内容
  void Update(Context const& ctx, Status const& status);
  Context& ctx() { return ctx_; }
  Status& status() { return status_; }
  UIStyle& style() { return style_; }
  UIStyle& ostyle() { return ostyle_; }
  bool GetIsReposition();
  UICallbackFunc& uiCallback() { return _uiCallback; }
  // compatibility shim for existing call sites
  void SetUICallBack(const UICallbackFunc& func) { _uiCallback = func; }
  void SetCallback(const UICallbackFunc& func) { _uiCallback = func; }
  bool& InServer() { return in_server_; }
  ShadowActionFunc& shadowAction() { return _shadowAction; }
  // 同时写进程级全局：面板读的是全局那份（跨 UI 实例也能拿到）。
  void SetShadowAction(const ShadowActionFunc& func) {
    _shadowAction = func;
    g_shadow_action = func;
  }
  HWND hwnd();

 private:
  the<UIImpl> pimpl_;
  Context ctx_;
  Status status_;
  UIStyle style_;
  UIStyle ostyle_;
  bool in_server_;
  UICallbackFunc _uiCallback;
  ShadowActionFunc _shadowAction;
};
}  // namespace weasel
