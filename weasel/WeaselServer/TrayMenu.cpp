#include "stdafx.h"
#include <TrayMenu.h>

#include <algorithm>
#include <windowsx.h>
#include <gdiplus.h>
#include <resource.h>
#pragma comment(lib, "gdiplus.lib")

namespace {

const wchar_t* kMenuClass = L"QingshiTrayMenuWindow";

int ScaleForDpi(int value, int dpi) {
  return MulDiv(value, dpi, 96);
}

int DpiOfWindow(HWND hwnd) {
  using GetDpiForWindowFn = UINT(WINAPI*)(HWND);
  static auto get_dpi = reinterpret_cast<GetDpiForWindowFn>(
      GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForWindow"));
  if (get_dpi) {
    UINT dpi = get_dpi(hwnd);
    if (dpi)
      return static_cast<int>(dpi);
  }
  int dpi = 96;
  HDC dc = GetDC(nullptr);
  if (dc) {
    dpi = GetDeviceCaps(dc, LOGPIXELSY);
    ReleaseDC(nullptr, dc);
  }
  return dpi > 0 ? dpi : 96;
}

// UIStyle 里存的是 0xAARRGGBB，COLORREF 要的是 0x00BBGGRR，必须走 RGB()。
COLORREF ColorRefOf(int argb) {
  return RGB((argb >> 16) & 0xff, (argb >> 8) & 0xff, argb & 0xff);
}

bool IsOpaque(int argb) {
  return (argb & 0xff000000) != 0;
}

COLORREF Mix(COLORREF a, COLORREF b, int weight_a) {
  const int wa = std::clamp(weight_a, 0, 100);
  const int wb = 100 - wa;
  return RGB((GetRValue(a) * wa + GetRValue(b) * wb) / 100,
             (GetGValue(a) * wa + GetGValue(b) * wb) / 100,
             (GetBValue(a) * wa + GetBValue(b) * wb) / 100);
}

struct MenuState {
  std::vector<TrayMenu::Item> items;
  weasel::UIStyle style;
  HWND hwnd = nullptr;
  HFONT font = nullptr;
  int hover = -1;
  int pressed = -1;
  UINT result = 0;
  int dpi = 96;
  int item_height = 32;
  int pad_x = 16;
  int pad_y = 8;
  int radius = 8;
  int width = 180;
  int height = 0;
};

MenuState* StateOf(HWND hwnd) {
  return reinterpret_cast<MenuState*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
}

// 底色用候选区底色（透明时退回候选窗底色），文字用主题文字色。
COLORREF BackColorOf(const MenuState& s) {
  if (IsOpaque(s.style.candidate_back_color))
    return ColorRefOf(s.style.candidate_back_color);
  return ColorRefOf(s.style.back_color);
}

COLORREF TextColorOf(const MenuState& s) {
  if (s.style.candidate_text_color)
    return ColorRefOf(s.style.candidate_text_color);
  return ColorRefOf(s.style.text_color);
}

COLORREF HoverBackOf(const MenuState& s) {
  return Mix(TextColorOf(s), BackColorOf(s), 8);
}

COLORREF HoverTextOf(const MenuState& s) {
  return TextColorOf(s);
}

Gdiplus::Color GdiColor(COLORREF c) {
  return Gdiplus::Color(255, GetRValue(c), GetGValue(c), GetBValue(c));
}

void RoundPath(Gdiplus::GraphicsPath& path, float x, float y, float w,
               float h, float radius) {
  const float d = radius * 2;
  path.AddArc(x, y, d, d, 180, 90);
  path.AddArc(x + w - d, y, d, d, 270, 90);
  path.AddArc(x + w - d, y + h - d, d, d, 0, 90);
  path.AddArc(x, y + h - d, d, d, 90, 90);
  path.CloseFigure();
}

int RowHeight(const MenuState& s, const TrayMenu::Item& item) {
  return item.id == 0 ? ScaleForDpi(9, s.dpi) : s.item_height;
}

// All glyphs share a 20 DIP grid and a 1.4 DIP stroke; no font symbols.
void DrawIcon(Gdiplus::Graphics& g, UINT id, float x, float y,
              float scale, COLORREF color) {
  Gdiplus::GraphicsState saved = g.Save();
  g.TranslateTransform(x, y);
  g.ScaleTransform(scale, scale);
  Gdiplus::Pen pen(GdiColor(color), 1.4f);
  pen.SetStartCap(Gdiplus::LineCapRound);
  pen.SetEndCap(Gdiplus::LineCapRound);
  if (id == ID_WEASELTRAY_SETTINGS) {
    for (int row = 0; row < 3; ++row) {
      const float cy = 5.0f + row * 5.0f;
      const float cx = row == 1 ? 12.5f : 7.0f;
      g.DrawLine(&pen, 3.0f, cy, cx - 2.0f, cy);
      g.DrawLine(&pen, cx + 2.0f, cy, 17.0f, cy);
      g.DrawEllipse(&pen, cx - 2, cy - 2, 4.0f, 4.0f);
    }
  } else if (id == ID_WEASELTRAY_CHECKUPDATE) {
    g.DrawArc(&pen, 3.5f, 3.5f, 13.0f, 13.0f, 145.0f, 280.0f);
    g.DrawLine(&pen, 3.5f, 5.0f, 3.5f, 9.0f);
    g.DrawLine(&pen, 3.5f, 9.0f, 7.5f, 9.0f);
  } else {
    g.DrawEllipse(&pen, 3.0f, 3.0f, 14.0f, 14.0f);
    g.DrawLine(&pen, 10.0f, 9.0f, 10.0f, 14.0f);
    Gdiplus::SolidBrush dot(GdiColor(color));
    g.FillEllipse(&dot, 9.2f, 5.7f, 1.6f, 1.6f);
  }
  g.Restore(saved);
}

void PaintMenu(HWND hwnd, MenuState& s) {
  PAINTSTRUCT ps;
  HDC dc = BeginPaint(hwnd, &ps);
  RECT rc;
  GetClientRect(hwnd, &rc);
  if (rc.right <= 0 || rc.bottom <= 0) {
    EndPaint(hwnd, &ps);
    return;
  }

  HDC mem = CreateCompatibleDC(dc);
  HBITMAP bitmap = CreateCompatibleBitmap(dc, rc.right, rc.bottom);
  HGDIOBJ old_bitmap = SelectObject(mem, bitmap);
  HGDIOBJ old_font = SelectObject(mem, s.font);
  SetBkMode(mem, TRANSPARENT);

  const COLORREF back = BackColorOf(s);
  const COLORREF text = TextColorOf(s);
  const COLORREF hover_back = HoverBackOf(s);
  const COLORREF hover_text = HoverTextOf(s);
  const COLORREF divider = Mix(text, back, 12);

  HBRUSH background = CreateSolidBrush(back);
  FillRect(mem, &rc, background);
  DeleteObject(background);

  {
  Gdiplus::Graphics graphics(mem);
  graphics.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
  int y = s.pad_y;
  for (size_t i = 0; i < s.items.size(); ++i) {
    const TrayMenu::Item& item = s.items[i];
    const int row_height = RowHeight(s, item);
    RECT row{s.pad_y, y, rc.right - s.pad_y, y + row_height};
    if (item.id == 0) {
      const int line_y = y + row_height / 2;
      RECT line{ScaleForDpi(12, s.dpi), line_y, rc.right - ScaleForDpi(12, s.dpi),
                line_y + 1};
      HBRUSH brush = CreateSolidBrush(divider);
      FillRect(mem, &line, brush);
      DeleteObject(brush);
    } else {
      const bool hovered = item.enabled && static_cast<int>(i) == s.hover;
      if (hovered) {
        Gdiplus::GraphicsPath path;
        RoundPath(path, static_cast<float>(row.left), static_cast<float>(row.top),
                  static_cast<float>(row.right - row.left),
                  static_cast<float>(row.bottom - row.top),
                  static_cast<float>(ScaleForDpi(5, s.dpi)));
        Gdiplus::SolidBrush brush(GdiColor(s.pressed == static_cast<int>(i)
            ? Mix(text, back, 14) : hover_back));
        graphics.FillPath(&brush, &path);
      }
      const COLORREF foreground = !item.enabled ? Mix(text, back, 40)
                                               : hovered ? hover_text : text;
      DrawIcon(graphics, item.id, static_cast<float>(ScaleForDpi(16, s.dpi)),
               static_cast<float>(y + (row_height - ScaleForDpi(20, s.dpi)) / 2),
               s.dpi / 96.0f, item.enabled ? Mix(foreground, back, 78) : foreground);
      SetTextColor(mem, foreground);
      RECT label = row;
      label.left = s.pad_x;
      label.right = rc.right - ScaleForDpi(18, s.dpi);
      DrawTextW(mem, item.text.c_str(), -1, &label,
                DT_SINGLELINE | DT_VCENTER | DT_LEFT | DT_NOPREFIX);
    }
    y += row_height;
  }

  Gdiplus::GraphicsPath outline;
  RoundPath(outline, 0.5f, 0.5f, rc.right - 1.0f, rc.bottom - 1.0f,
            static_cast<float>(s.radius));
  Gdiplus::Pen border(GdiColor(divider), 1.0f);
  graphics.DrawPath(&border, &outline);
  graphics.Flush(Gdiplus::FlushIntentionSync);
  }

  BitBlt(dc, 0, 0, rc.right, rc.bottom, mem, 0, 0, SRCCOPY);
  SelectObject(mem, old_font);
  SelectObject(mem, old_bitmap);
  DeleteObject(bitmap);
  DeleteDC(mem);
  EndPaint(hwnd, &ps);
}

int ItemAtPoint(const MenuState& s, POINT pt) {
  if (pt.x < s.pad_y || pt.x >= s.width - s.pad_y || pt.y < s.pad_y)
    return -1;
  int y = s.pad_y;
  for (size_t i = 0; i < s.items.size(); ++i) {
    y += RowHeight(s, s.items[i]);
    if (pt.y < y)
      return s.items[i].id && s.items[i].enabled ? static_cast<int>(i) : -1;
  }
  return -1;
}

LRESULT CALLBACK MenuProc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
  MenuState* state = StateOf(hwnd);
  switch (message) {
    case WM_MOUSEMOVE: {
      if (!state)
        break;
      POINT pt{GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam)};
      const int index = ItemAtPoint(*state, pt);
      if (index != state->hover) {
        state->hover = index;
        InvalidateRect(hwnd, nullptr, FALSE);
      }
      // 悬停时也要能关掉：鼠标离开窗口区域由 TrackMouseEvent 处理。
      TRACKMOUSEEVENT track{sizeof(track), TME_LEAVE, hwnd, 0};
      TrackMouseEvent(&track);
      return 0;
    }
    case WM_MOUSELEAVE: {
      if (!state)
        break;
      if (state->hover != -1) {
        state->hover = -1;
        InvalidateRect(hwnd, nullptr, FALSE);
      }
      return 0;
    }
    case WM_LBUTTONDOWN:
      if (state) {
        state->pressed = ItemAtPoint(*state, {GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam)});
        InvalidateRect(hwnd, nullptr, FALSE);
      }
      return 0;
    case WM_LBUTTONUP: {
      if (!state)
        break;
      POINT pt{GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam)};
      const int index = ItemAtPoint(*state, pt);
      if (index >= 0 && index == state->pressed)
        state->result = state->items[index].id;
      DestroyWindow(hwnd);
      return 0;
    }
    case WM_RBUTTONUP:
    case WM_MBUTTONUP:
      DestroyWindow(hwnd);
      return 0;
    case WM_KEYDOWN: {
      if (wparam == VK_ESCAPE)
        DestroyWindow(hwnd);
      else if (state && wparam == VK_RETURN && state->hover >= 0) {
        state->result = state->items[state->hover].id;
        DestroyWindow(hwnd);
      } else if (state && (wparam == VK_UP || wparam == VK_DOWN ||
                           wparam == VK_HOME || wparam == VK_END)) {
        const int count = static_cast<int>(state->items.size());
        const int step = wparam == VK_UP || wparam == VK_END ? -1 : 1;
        int next = wparam == VK_HOME ? -1 : wparam == VK_END ? count : state->hover;
        if (next < 0 && step < 0) next = count;
        for (int i = 0; i < count; ++i) {
          next = (next + step + count) % count;
          if (state->items[next].id && state->items[next].enabled) {
            state->hover = next;
            break;
          }
        }
        InvalidateRect(hwnd, nullptr, FALSE);
      }
      return 0;
    }
    case WM_ACTIVATE:
      if (LOWORD(wparam) == WA_INACTIVE)
        DestroyWindow(hwnd);
      return 0;
    case WM_KILLFOCUS:
      DestroyWindow(hwnd);
      return 0;
    case WM_PAINT:
      if (state)
        PaintMenu(hwnd, *state);
      return 0;
    case WM_ERASEBKGND:
      return 1;
    case WM_DESTROY:
      if (state) {
        state->hwnd = nullptr;
        if (state->font) {
          DeleteObject(state->font);
          state->font = nullptr;
        }
      }
      return 0;
    default:
      break;
  }
  return DefWindowProcW(hwnd, message, wparam, lparam);
}

bool EnsureClassRegistered(HINSTANCE instance) {
  static bool registered = false;
  if (registered)
    return true;
  WNDCLASSEXW wc{};
  wc.cbSize = sizeof(wc);
  wc.style = CS_HREDRAW | CS_VREDRAW | CS_DROPSHADOW;
  wc.lpfnWndProc = MenuProc;
  wc.hInstance = instance;
  wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
  wc.lpszClassName = kMenuClass;
  registered = RegisterClassExW(&wc) != 0 || GetLastError() == ERROR_CLASS_ALREADY_EXISTS;
  return registered;
}

int MeasureWidth(MenuState& s, HDC dc) {
  HGDIOBJ old = SelectObject(dc, s.font);
  int widest = 0;
  for (const TrayMenu::Item& item : s.items) {
    if (item.id == 0)
      continue;
    SIZE size{};
    GetTextExtentPoint32W(dc, item.text.c_str(),
                          static_cast<int>(item.text.size()), &size);
    widest = std::max<int>(widest, size.cx);
  }
  SelectObject(dc, old);
  return widest + s.pad_x + ScaleForDpi(24, s.dpi);
}

}  // namespace

std::wstring TrayMenu::CleanLabel(const wchar_t* text) {
  std::wstring label(text ? text : L"");
  const size_t marker = label.rfind(L"(&");
  if (marker != std::wstring::npos && !label.empty() && label.back() == L')') {
    size_t cut = marker;
    while (cut > 0 && label[cut - 1] == L' ')
      --cut;
    label.erase(cut);
  }
  label.erase(std::remove(label.begin(), label.end(), L'&'), label.end());
  return label;
}

UINT TrayMenu::Popup(HWND owner,
                     POINT pos,
                     const std::vector<Item>& items,
                     const weasel::UIStyle& style) {
  if (items.empty())
    return 0;
  // This code also lives in the TSF DLL. Register against the owning module,
  // not an arbitrary host executable (Explorer, editor, etc.).
  HMODULE instance = nullptr;
  GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                        GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                    reinterpret_cast<LPCWSTR>(&MenuProc), &instance);
  if (!EnsureClassRegistered(instance))
    return 0;
  Gdiplus::GdiplusStartupInput gdiplus_input;
  ULONG_PTR gdiplus_token = 0;
  if (Gdiplus::GdiplusStartup(&gdiplus_token, &gdiplus_input, nullptr) != Gdiplus::Ok)
    return 0;
  struct GraphicsLifetime {
    ULONG_PTR token;
    ~GraphicsLifetime() { Gdiplus::GdiplusShutdown(token); }
  } graphics_lifetime{gdiplus_token};

  MenuState state;
  state.items = items;
  state.style = style;

  HDC screen = GetDC(nullptr);
  state.dpi = DpiOfWindow(owner ? owner : GetDesktopWindow());
  state.item_height = ScaleForDpi(36, state.dpi);
  state.pad_x = ScaleForDpi(46, state.dpi);
  state.pad_y = ScaleForDpi(6, state.dpi);
  state.radius = ScaleForDpi(8, state.dpi);

  LOGFONTW lf{};
  // Menu typography is independent of candidate themes; retain Windows DPI scaling.
  lf.lfHeight = -MulDiv(10, state.dpi, 72);
  lf.lfWeight = FW_NORMAL;
  lf.lfCharSet = DEFAULT_CHARSET;
  lf.lfQuality = CLEARTYPE_QUALITY;
  wcscpy_s(lf.lfFaceName, L"Microsoft YaHei UI");
  state.font = CreateFontIndirectW(&lf);
  if (!state.font) {
    ReleaseDC(nullptr, screen);
    return 0;
  }

  state.width = MeasureWidth(state, screen);
  ReleaseDC(nullptr, screen);
  state.width = (std::max)(state.width, ScaleForDpi(208, state.dpi));
  state.height = state.pad_y * 2;
  for (const auto& item : items)
    state.height += RowHeight(state, item);

  // 屏幕边界收敛：靠右下角弹出时向左上翻。
  RECT work{};
  MONITORINFO monitor{sizeof(monitor)};
  if (GetMonitorInfoW(MonitorFromPoint(pos, MONITOR_DEFAULTTONEAREST), &monitor))
    work = monitor.rcWork;
  else
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
  int x = pos.x - state.width;
  int y = pos.y - state.height;
  if (x < work.left)
    x = work.left;
  if (y < work.top)
    y = pos.y;
  if (x + state.width > work.right)
    x = work.right - state.width;
  if (y + state.height > work.bottom)
    y = work.bottom - state.height;

  // A foreign document window is useful for DPI, but must not own a popup on
  // the shell thread: activation/focus changes can dismiss it immediately.
  HWND hwnd = CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_TOPMOST, kMenuClass, L"青石五笔菜单",
                              WS_POPUP, x, y, state.width, state.height, nullptr,
                              nullptr, instance, nullptr);
  if (!hwnd) {
    DeleteObject(state.font);
    return 0;
  }
  state.hwnd = hwnd;
  SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(&state));

  if (state.radius > 0) {
    HRGN region = CreateRoundRectRgn(0, 0, state.width + 1, state.height + 1,
                                     state.radius * 2, state.radius * 2);
    SetWindowRgn(hwnd, region, TRUE);
  }

  ShowWindow(hwnd, SW_SHOWNOACTIVATE);
  const DWORD foreground_thread = GetWindowThreadProcessId(GetForegroundWindow(), nullptr);
  const DWORD menu_thread = GetCurrentThreadId();
  const bool attached = foreground_thread && foreground_thread != menu_thread &&
      AttachThreadInput(menu_thread, foreground_thread, TRUE);
  SetForegroundWindow(hwnd);
  SetActiveWindow(hwnd);
  SetFocus(hwnd);
  if (attached)
    AttachThreadInput(menu_thread, foreground_thread, FALSE);
  InvalidateRect(hwnd, nullptr, FALSE);
  UpdateWindow(hwnd);

  MSG msg;
  while (IsWindow(hwnd)) {
    const BOOL got = GetMessageW(&msg, nullptr, 0, 0);
    if (got <= 0) {
      if (IsWindow(hwnd)) DestroyWindow(hwnd);
      if (got == 0) PostQuitMessage(static_cast<int>(msg.wParam));
      break;
    }
    TranslateMessage(&msg);
    DispatchMessageW(&msg);
  }
  return state.result;
}
