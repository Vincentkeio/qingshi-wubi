#pragma once

#include <WeaselUI.h>

#include <string>
#include <vector>

// 青石托盘菜单：不用系统 HMENU，自己画一个。
// 目的只有一个 —— 跟候选窗和设置面板同一套配色，系统菜单做不到这一点。
class TrayMenu {
 public:
  // Private WM_COMMAND request; handled on the server UI thread.
  static constexpr UINT kShowServerMenu = 0x7f01;
  struct Item {
    UINT id;                    // 0 表示分隔线
    std::wstring text;
    bool enabled = true;
  };

  // 弹出菜单并阻塞到用户选择。返回选中的 id，取消返回 0。
  static UINT Popup(HWND owner,
                    POINT pos,
                    const std::vector<Item>& items,
                    const weasel::UIStyle& style);

  // 菜单资源里的 "(&S)" 和 "&" 是给系统菜单的助记符，自绘时要清掉。
  static std::wstring CleanLabel(const wchar_t* text);
};
