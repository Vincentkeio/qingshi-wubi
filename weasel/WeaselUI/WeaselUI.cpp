#include "WeaselPanel.h"
#include <WeaselUI.h>

namespace weasel {

// 候选调序回调（面板右键「固顶」用）。放在这里而不是 WeaselPanel.cpp：
// 静态库里只有被引用到的 obj 才会被链接，面板那个 obj 平时不会被拉进来，
// 定义在这里能保证符号一定存在。
ShadowActionFunc g_shadow_action;
ShadowRefreshFunc g_shadow_refresh;

void SetGlobalShadowAction(const ShadowActionFunc& func) {
  g_shadow_action = func;
  // 诊断：确认服务端真的把回调注册进来了。
  wchar_t dir[MAX_PATH] = {0};
  if (GetTempPathW(MAX_PATH, dir) == 0)
    return;
  std::wstring path = std::wstring(dir) + L"qingshi-panel.log";
  FILE* f = nullptr;
  if (_wfopen_s(&f, path.c_str(), L"a, ccs=UTF-8") == 0 && f) {
    fwprintf_s(f, L"[register] shadow action installed=%d\n",
               g_shadow_action ? 1 : 0);
    fclose(f);
  }
}

// ----------------------------------------------------------------------------
class UIImpl {
 public:
  WeaselPanel panel;
  UI& ui_;
  UIImpl(UI& ui) : panel(ui), ui_(ui) {}
  ~UIImpl() {}
  bool IsShown() const {
    return panel.IsWindow() && ::IsWindowVisible(panel.hwnd());
  }
  void Refresh() {
    if (!panel.IsWindow())
      return;
    // 每次刷新都同步一次最新样式：panel 构造时只拷贝了一份，
    // 配置热更新（/reload）后不主动推过去的话，界面还停在旧样式上。
    panel.SetStyle(ui_.style());
    panel.Refresh();
  }
  void RepositionPreview() {
    if (panel.IsWindow())
      panel.RepositionPreview();
  }
  void Show() {
    if (!panel.IsWindow())
      return;
    panel.ShowWindow(SW_SHOWNA);
  }
  void Hide() {
    if (!panel.IsWindow())
      return;
    panel.ShowWindow(SW_HIDE);
  }
  void ShowWithTimeout(size_t millisec) { panel.ShowWithTimeout(millisec); }
  bool IsCountingDown() const { return panel.IsCountingDown(); }
};
// ----------------------------------------------------------------------------
BOOL UI::IsCountingDown() const {
  return pimpl_ && pimpl_->panel.IsCountingDown();
};

UI::UI() : pimpl_(nullptr), in_server_(false) {}

UI::~UI() {
  if (pimpl_)
    Destroy(true);
}
BOOL UI::IsShown() const {
  return pimpl_ && pimpl_->IsShown();
}
void UI::UpdateInputPosition(RECT const& rc) {
  if (pimpl_ && pimpl_->panel.IsWindow()) {
    pimpl_->panel.MoveTo(rc);
  }
}
void UI::Update(const Context& ctx, const Status& status) {
  if (ctx_ == ctx && status_ == status)
    return;
  ctx_ = ctx;
  status_ = status;
  if (style_.candidate_abbreviate_length > 0) {
    for (auto& c : ctx_.cinfo.candies) {
      if (c.str.length() > (size_t)style_.candidate_abbreviate_length) {
        c.str =
            c.str.substr(0, (size_t)style_.candidate_abbreviate_length - 1) +
            L"..." + c.str.substr(c.str.length() - 1);
      }
    }
  }
  Refresh();
}
void UI::Refresh() {
  if (pimpl_) {
    pimpl_->Refresh();
  }
}

void UI::ForceRefresh() {
  // 清掉「上次画的是什么」的缓存，让下一次 Update 一定走重建路径。
  ctx_ = Context();
  status_ = Status();
  if (pimpl_) {
    pimpl_->Refresh();
  }
}
void UI::RepositionPreview() {
  if (pimpl_)
    pimpl_->RepositionPreview();
}
void UI::ShowWithTimeout(size_t millisec) {
  if (pimpl_) {
    pimpl_->ShowWithTimeout(millisec);
  }
}
void UI::Show() {
  if (pimpl_) {
    pimpl_->Show();
  }
}
void UI::Hide() {
  if (pimpl_) {
    pimpl_->Hide();
  }
}
void UI::Destroy(bool full) {
  if (pimpl_) {
    if (pimpl_->panel.IsWindow())
      pimpl_->panel.DestroyWindow();
    if (full) {
      // ensure window resources and shared devices are released
      pimpl_->panel.ReleaseAllResources();
      pimpl_.reset();
    }
  }
}
bool UI::Create(HWND parent, bool preview_mode) {
  if (pimpl_) {
    pimpl_->panel.SetPreviewMode(preview_mode);
    pimpl_->panel.Create(parent, preview_mode);
    return true;
  }
  pimpl_ = std::make_unique<UIImpl>(*this);
  if (!pimpl_)
    return false;
  return pimpl_->panel.Create(parent, preview_mode);
}
bool UI::GetIsReposition() {
  return pimpl_ && pimpl_->panel.GetIsReposition();
}

HWND UI::hwnd() {
  if (pimpl_ && pimpl_->panel.IsWindow())
    return pimpl_->panel.hwnd();
  return nullptr;
}
}  // namespace weasel
