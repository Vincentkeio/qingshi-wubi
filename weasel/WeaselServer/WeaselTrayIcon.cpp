#include "stdafx.h"
#include "WeaselTrayIcon.h"
#include <TrayMenu.h>
#include <algorithm>

// nasty
#include <resource.h>

static UINT mode_icon[] = {IDI_ZH, IDI_ZH, IDI_EN, IDI_RELOAD};

WeaselTrayIcon::WeaselTrayIcon(weasel::UI& ui)
    : m_style(ui.style()),
      m_status(ui.status()),
      m_mode(INITIAL),
      m_schema_zhung_icon(),
      m_schema_ascii_icon() {}

void WeaselTrayIcon::CustomizeMenu(HMENU hMenu) {}

void WeaselTrayIcon::ShowMenu() {
  HMENU menu = LoadMenuW(GetModuleHandleW(nullptr), MAKEINTRESOURCE(IDR_MENU_POPUP));
  if (!menu) return;
  POINT pos{};
  GetCursorPos(&pos);
  OnCustomMenu(GetTargetWnd(), pos, GetSubMenu(menu, 0));
  DestroyMenu(menu);
}

bool WeaselTrayIcon::OnCustomMenu(HWND target, POINT pos, HMENU menu) {
  if (!menu)
    return false;
  // A nested message loop still receives tray notifications. Do not open a
  // second popup over the first one when right-clicked repeatedly.
  static bool menu_open = false;
  if (menu_open) return true;
  struct MenuGuard {
    bool& open;
    explicit MenuGuard(bool& value) : open(value) { open = true; }
    ~MenuGuard() { open = false; }
  } guard(menu_open);
  const int count = ::GetMenuItemCount(menu);
  if (count <= 0)
    return false;

  // 文字和 ID 都从资源里读，简中 / 繁中 / 英文自动跟着 rc 走。
  std::vector<TrayMenu::Item> items;
  items.reserve(count);
  for (int i = 0; i < count; ++i) {
    const UINT id = ::GetMenuItemID(menu, i);
    wchar_t text[256] = {0};
    ::GetMenuStringW(menu, i, text, _countof(text), MF_BYPOSITION);
    TrayMenu::Item item;
    item.id = (id == static_cast<UINT>(-1)) ? 0u : id;  // -1 表示分隔线
    item.text = TrayMenu::CleanLabel(text);
    item.enabled = (::GetMenuState(menu, i, MF_BYPOSITION) &
                    (MF_DISABLED | MF_GRAYED)) == 0;
    items.push_back(item);
  }

  const UINT picked = TrayMenu::Popup(target, pos, items, m_style);
  if (picked)
    ::PostMessageW(target, WM_COMMAND, picked, 0);
  return true;
}

BOOL WeaselTrayIcon::Create(HWND hTargetWnd) {
  HMODULE hModule = GetModuleHandle(NULL);
  CIcon icon;
  icon.LoadIconW(IDI_ZH);
  BOOL bRet =
      CSystemTray::Create(hModule, NULL, WM_WEASEL_TRAY_NOTIFY,
                          get_weasel_ime_name().c_str(), icon, IDR_MENU_POPUP);
  if (hTargetWnd) {
    SetTargetWnd(hTargetWnd);
  }
  if (!m_style.display_tray_icon) {
    RemoveIcon();
  } else {
    AddIcon();
  }
  return bRet;
}

void WeaselTrayIcon::RequestRefresh() {
  std::lock_guard<std::mutex> lock(m_state_mutex);
  if (!m_refresh_enabled) {
    return;
  }
  m_pending_state = WeaselTrayIconState::From(m_style, m_status);
  if (m_refresh_pending) {
    return;
  }
  m_refresh_pending = true;
  if (!::PostMessage(GetTargetWnd(), WM_WEASEL_SERVICE_NOTIFY, 0, 0)) {
    m_refresh_pending = false;
  }
}

void WeaselTrayIcon::ApplyRefresh() {
  WeaselTrayIconState state;
  {
    std::lock_guard<std::mutex> lock(m_state_mutex);
    if (!m_refresh_pending || !m_refresh_enabled) {
      return;
    }
    state = m_pending_state;
    m_refresh_pending = false;
    m_refresh_in_progress = true;
  }
  Refresh(state);
  {
    std::lock_guard<std::mutex> lock(m_state_mutex);
    m_refresh_in_progress = false;
  }
  m_state_cv.notify_all();
}

void WeaselTrayIcon::DisableRefresh() {
  std::unique_lock<std::mutex> lock(m_state_mutex);
  m_refresh_enabled = false;
  m_refresh_pending = false;
  m_state_cv.wait(lock, [this] { return !m_refresh_in_progress; });
}

void WeaselTrayIcon::Refresh(const WeaselTrayIconState& state) {
  if (!state.display_tray_icon &&
      !state.disabled)
  {
    if (m_mode != INITIAL) {
      RemoveIcon();
      m_mode = INITIAL;
    }
    return;
  }
  WeaselTrayMode mode = state.disabled     ? DISABLED
                        : state.ascii_mode ? ASCII
                                           : ZHUNG;
  /* change icon, when
          1,mode changed
          2,icon changed
          3,both m_schema_zhung_icon and state.current_zhung_icon empty(for
     initialize) 4,both m_schema_ascii_icon and state.current_ascii_icon
     empty(for initialize)
  */
  if (mode != m_mode || m_schema_zhung_icon != state.current_zhung_icon ||
      (m_schema_zhung_icon.empty() && state.current_zhung_icon.empty()) ||
      m_schema_ascii_icon != state.current_ascii_icon ||
      (m_schema_ascii_icon.empty() && state.current_ascii_icon.empty())) {
    ShowIcon();
    m_mode = mode;
    m_schema_zhung_icon = state.current_zhung_icon;
    m_schema_ascii_icon = state.current_ascii_icon;
    if (mode == ASCII) {
      if (m_schema_ascii_icon.empty())
        SetIcon(mode_icon[mode]);
      else
        SetIcon(m_schema_ascii_icon.c_str());
    } else if (mode == ZHUNG) {
      if (m_schema_zhung_icon.empty())
        SetIcon(mode_icon[mode]);
      else
        SetIcon(m_schema_zhung_icon.c_str());
    } else
      SetIcon(mode_icon[mode]);

    // Deploying is a transient engine state. The settings UI already reports
    // progress; do not interrupt the user with a maintenance balloon.
  } else if (!Visible()) {
    ShowIcon();
  }
}
