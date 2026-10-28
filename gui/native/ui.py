# -*- coding: utf-8 -*-
"""原生控件层：在 w32 之上搭一套设置中心能用的最小控件集。

刻意保持简单：绝对定位 + 手写布局，没有布局引擎。
所有尺寸都是「96 DPI 下的像素」，实际创建时乘 SCALE。
"""
import ctypes
import ctypes.wintypes as wt

from . import w32
from .w32 import (
    user32, gdi32, kernel32, comctl32, LRESULT, WPARAM, LPARAM, HWND, HDC,
    RECT, WNDCLASSEXW, PAINTSTRUCT, rgb, loword, hiword,
)

SCALE = 1.0
APP_VERSION = ""
FACE = "Microsoft YaHei UI"
FACE_MONO = "Consolas"

# ---- 主题色（对齐原 Qt 版的黑白灰） ----
BG_APP = 0xFAFAFA
BG_PANEL = 0xFFFFFF
BORDER = 0xE9E9E9
TEXT = 0x202020
TEXT_STRONG = 0x171717
MUTED = 0x626262
HINT = 0x797979
BTN_BG = 0xEEEEEE
BTN_HOVER = 0xE5E5E5
BTN_PRESS = 0xE0E0E0
PRIMARY = 0x202020
PRIMARY_HOVER = 0x383838
FIELD_BG = 0xEEEEEE
CARD_BORDER = 0xE6E6E6
SELECTED = 0xF1F1F1
SELECTED_BAR = 0x252525

ODS_SELECTED = 0x0001
ODS_DISABLED = 0x0004
ODS_FOCUS = 0x0010
ODS_COMBOBOXEDIT = 0x1000

TME_LEAVE = 0x00000002


def s(value):
    """把设计稿像素换算成实际像素。"""
    return int(round(value * SCALE))


def client_window_size(width, height, style):
    """Keep design dimensions in the client area, independent of title-bar/DPI."""
    rect = RECT(0, 0, s(width), s(height))
    user32.AdjustWindowRectEx(ctypes.byref(rect), style, False, 0)
    return rect.right - rect.left, rect.bottom - rect.top


def _ptr(text):
    """把 Python 字符串转成 SendMessage 能用的 LPARAM。"""
    return ctypes.cast(ctypes.c_wchar_p(text), ctypes.c_void_p).value


class DRAWITEMSTRUCT(ctypes.Structure):
    _fields_ = [("CtlType", wt.UINT), ("CtlID", wt.UINT), ("itemID", wt.UINT),
                ("itemAction", wt.UINT), ("itemState", wt.UINT), ("hwndItem", HWND),
                ("hDC", HDC), ("rcItem", RECT), ("itemData", ctypes.c_size_t)]


class MEASUREITEMSTRUCT(ctypes.Structure):
    _fields_ = [("CtlType", wt.UINT), ("CtlID", wt.UINT), ("itemID", wt.UINT),
                ("itemWidth", wt.UINT), ("itemHeight", wt.UINT), ("itemData", ctypes.c_size_t)]


class SCROLLINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("fMask", wt.UINT), ("nMin", ctypes.c_int),
                ("nMax", ctypes.c_int), ("nPage", wt.UINT), ("nPos", ctypes.c_int),
                ("nTrackPos", ctypes.c_int)]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("dwFlags", wt.DWORD), ("hwndTrack", HWND),
                ("dwHoverTime", wt.DWORD)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, wt.UINT, WPARAM, LPARAM)
SUBCLASSPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, wt.UINT, WPARAM, LPARAM,
                                  ctypes.c_size_t, ctypes.c_size_t)

BY_HWND = {}
_KEEP = []
_CLASSES = {}


def brand_mark(g, x, y, size):
    """Draw the original PNG with Windows GDI+; no imaging runtime is required."""
    from pathlib import Path
    if "brand-image" not in _CLASSES:
        class Startup(ctypes.Structure):
            _fields_ = [("version", wt.UINT), ("debug", ctypes.c_void_p),
                        ("background", wt.BOOL), ("codecs", wt.BOOL)]
        api = ctypes.WinDLL("gdiplus")
        pointer = ctypes.c_void_p
        api.GdiplusStartup.argtypes = [ctypes.POINTER(pointer), ctypes.POINTER(Startup), pointer]
        api.GdipLoadImageFromFile.argtypes = [wt.LPCWSTR, ctypes.POINTER(pointer)]
        api.GdipCreateFromHDC.argtypes = [HDC, ctypes.POINTER(pointer)]
        api.GdipDrawImageRectI.argtypes = [pointer, pointer, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int]
        api.GdipSetInterpolationMode.argtypes = [pointer, ctypes.c_int]
        api.GdipDeleteGraphics.argtypes = [pointer]
        token, bitmap = pointer(), pointer()
        api.GdiplusStartup(ctypes.byref(token), ctypes.byref(Startup(1, None, False, False)), None)
        asset = Path(__file__).resolve().parent.parent / "qingshi-mark.png"
        status = api.GdipLoadImageFromFile(str(asset), ctypes.byref(bitmap))
        if status:
            raise OSError(f"Cannot load brand asset: {asset} (GDI+ {status})")
        _CLASSES["brand-image"] = api, token, bitmap
    api, token, bitmap = _CLASSES["brand-image"]
    graphics = ctypes.c_void_p()
    api.GdipCreateFromHDC(g.hdc, ctypes.byref(graphics))
    api.GdipSetInterpolationMode(graphics, 7)
    api.GdipDrawImageRectI(graphics, bitmap, s(x), s(y), s(size), s(size))
    api.GdipDeleteGraphics(graphics)

user32.SetScrollInfo.argtypes = [HWND, ctypes.c_int, ctypes.POINTER(SCROLLINFO), wt.BOOL]
user32.GetScrollInfo.argtypes = [HWND, ctypes.c_int, ctypes.POINTER(SCROLLINFO)]
user32.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
user32.SetCursor.argtypes = [wt.HANDLE]


def _dispatch(hwnd, msg, wparam, lparam, default):
    obj = BY_HWND.get(hwnd)
    if obj is None:
        return default(hwnd, msg, wparam, lparam)
    return obj.on_message(msg, wparam, lparam)


def _class_proc(hwnd, msg, wparam, lparam):
    return _dispatch(hwnd, msg, wparam, lparam,
                     lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))


def _subclass_proc(hwnd, msg, wparam, lparam, uidsubclass, dwrefdata):
    return _dispatch(hwnd, msg, wparam, lparam,
                     lambda h, m, w, l: comctl32.DefSubclassProc(h, m, w, l))


_CLASS_PROC = WNDPROC(_class_proc)
_SUBCLASS_PROC = SUBCLASSPROC(_subclass_proc)
_KEEP.extend([_CLASS_PROC, _SUBCLASS_PROC])


def register_class(name, cursor=w32.IDC_ARROW):
    if name in _CLASSES:
        return _CLASSES[name]
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.style = w32.CS_HREDRAW | w32.CS_VREDRAW | w32.CS_DBLCLKS
    wc.lpfnWndProc = ctypes.cast(_CLASS_PROC, ctypes.c_void_p)
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.hCursor = user32.LoadCursorW(None, wt.LPCWSTR(cursor))
    wc.hbrBackground = None
    wc.lpszClassName = name
    atom = user32.RegisterClassExW(ctypes.byref(wc))
    _CLASSES[name] = atom
    return atom


class Fonts:
    """按像素高度缓存字体，避免每次绘制都 CreateFont。"""

    def __init__(self):
        self._cache = {}

    def get(self, px, weight=w32.FW_NORMAL, face=None):
        key = (SCALE, px, weight, face)
        if key not in self._cache:
            self._cache[key] = gdi32.CreateFontW(
                -s(px), 0, 0, 0, weight, 0, 0, 0, w32.DEFAULT_CHARSET, 0, 0,
                w32.CLEARTYPE_QUALITY, 0, face or FACE)
        return self._cache[key]


FONTS = Fonts()


class Widget:
    """所有控件的基类。custom=True 表示用的是我们自己注册的窗口类。"""

    cls = "STATIC"
    style = 0
    exstyle = 0
    custom = False
    popup = False

    def __init__(self, parent, text="", rect=(0, 0, 0, 0), wid=0, style=None, ex=None,
                 visible=True, font_px=13, font_weight=w32.FW_NORMAL):
        self.parent = parent
        self.id = wid
        self.font_px = font_px
        self.font_weight = font_weight
        self.text_value = text
        self.base = (s(rect[0]), s(rect[1]), s(rect[2]), s(rect[3]))
        st = self.style if style is None else style
        exs = self.exstyle if ex is None else ex
        self.hwnd = None
        parent_hwnd = parent.hwnd if parent is not None and getattr(parent, "hwnd", None) else None
        if self.popup:
            self.hwnd = user32.CreateWindowExW(
                exs, self.cls, text, st, self.base[0], self.base[1], self.base[2],
                self.base[3], parent_hwnd, w32.HMENU(wid),
                kernel32.GetModuleHandleW(None), None)
            BY_HWND[self.hwnd] = self
            self.apply_font()
            return
        if parent_hwnd:
            st |= w32.WS_CHILD
            if visible:
                st |= w32.WS_VISIBLE
            self.hwnd = user32.CreateWindowExW(
                exs, self.cls, text, st, self.base[0], self.base[1], self.base[2],
                self.base[3], parent_hwnd, w32.HMENU(wid), kernel32.GetModuleHandleW(None), None)
            BY_HWND[self.hwnd] = self
            if not self.custom:
                comctl32.SetWindowSubclass(self.hwnd, _SUBCLASS_PROC, 0, 0)
            self.apply_font()
            parent.children.append(self)

    # ---- 通用操作 ----
    def apply_font(self):
        if self.hwnd:
            user32.SendMessageW(self.hwnd, 0x0030,
                                w32.WPARAM(FONTS.get(self.font_px, self.font_weight)),
                                w32.LPARAM(1))

    def set_font(self, px=None, weight=None):
        if px is not None:
            self.font_px = px
        if weight is not None:
            self.font_weight = weight
        self.apply_font()
        self.invalidate()

    def move(self, x, y, w=None, h=None):
        x, y = s(x), s(y)
        w = self.base[2] if w is None else s(w)
        h = self.base[3] if h is None else s(h)
        self.base = (x, y, w, h)
        if self.hwnd:
            user32.SetWindowPos(self.hwnd, None, x, y, w, h,
                                w32.SWP_NOZORDER | w32.SWP_NOACTIVATE)

    def set_text(self, value):
        if self.hwnd:
            user32.SetWindowTextW(self.hwnd, value)
        self.text_value = value

    def get_text(self):
        if not self.hwnd:
            return getattr(self, "text_value", "")
        n = user32.GetWindowTextLengthW(self.hwnd)
        buf = ctypes.create_unicode_buffer(n + 2)
        user32.GetWindowTextW(self.hwnd, buf, n + 2)
        return buf.value

    def show(self, flag=True):
        if self.hwnd:
            user32.ShowWindow(self.hwnd, w32.SW_SHOW if flag else w32.SW_HIDE)

    def enable(self, flag=True):
        if self.hwnd:
            user32.EnableWindow(self.hwnd, bool(flag))

    def invalidate(self):
        if self.hwnd:
            user32.InvalidateRect(self.hwnd, None, True)

    def on_command(self, code):
        pass

    def on_message(self, msg, wparam, lparam):
        if self.custom:
            return user32.DefWindowProcW(self.hwnd, msg, wparam, lparam)
        return comctl32.DefSubclassProc(self.hwnd, msg, wparam, lparam)


class Panel(Widget):
    """自绘背景的容器：页面主体 / 侧栏 / 预览框都基于它。"""

    cls = "QSPanel"
    custom = True
    bg = BG_PANEL

    def __init__(self, parent, rect=(0, 0, 0, 0), bg=None, wid=0, scroll=False):
        register_class("QSPanel")
        self.children = []
        self.bg = bg if bg is not None else self.bg
        self.scroll = scroll
        self.offset = 0
        self.content_h = 0
        self.combo_item_h = 26
        self._brush = None
        style = w32.WS_CLIPCHILDREN | (w32.WS_VSCROLL if scroll else 0)
        super().__init__(parent, "", rect, wid, style=style)

    def bg_brush(self):
        if self._brush is None or self._brush[0] != self.bg:
            self._brush = (self.bg, gdi32.CreateSolidBrush(rgb(self.bg)))
        return self._brush[1]

    def on_message(self, msg, wparam, lparam):
        if msg == w32.WM_ERASEBKGND:
            return 1
        if msg == w32.WM_PAINT:
            self.do_paint()
            return 0
        if msg in (w32.WM_CTLCOLORSTATIC, w32.WM_CTLCOLORBTN, w32.WM_CTLCOLOREDIT,
                   w32.WM_CTLCOLORLISTBOX):
            hdc = w32.HDC(wparam)
            gdi32.SetBkMode(hdc, w32.TRANSPARENT)
            target = BY_HWND.get(lparam)
            gdi32.SetTextColor(hdc, rgb(getattr(target, "color", TEXT)))
            if msg in (w32.WM_CTLCOLOREDIT, w32.WM_CTLCOLORLISTBOX):
                return gdi32.CreateSolidBrush(rgb(FIELD_BG))
            return self.bg_brush()
        if msg == w32.WM_DRAWITEM:
            di = ctypes.cast(lparam, ctypes.POINTER(DRAWITEMSTRUCT)).contents
            target = BY_HWND.get(di.hwndItem)
            if target is not None and hasattr(target, "draw_item"):
                target.draw_item(di)
                return 1
            return 0
        if msg == w32.WM_MEASUREITEM:
            mi = ctypes.cast(lparam, ctypes.POINTER(MEASUREITEMSTRUCT)).contents
            mi.itemHeight = s(self.combo_item_h)
            return 1
        if msg == w32.WM_VSCROLL and self.scroll:
            self.on_scroll(wparam, lparam)
            return 0
        if msg == w32.WM_MOUSEWHEEL and self.scroll:
            delta = w32.signed_hiword(wparam)
            self.scroll_by(-delta // 120 * s(72))
            return 0
        if msg == w32.WM_COMMAND:
            target = BY_HWND.get(lparam)
            if target is not None:
                target.on_command(hiword(wparam))
                return 0
        if msg == w32.WM_NOTIFY:
            hdr = ctypes.cast(lparam, ctypes.POINTER(w32.NMHDR)).contents
            target = BY_HWND.get(hdr.hwndFrom)
            if target is not None and hasattr(target, "on_notify"):
                if target.on_notify(hdr.code, lparam):
                    return 1
                return 0
        return user32.DefWindowProcW(self.hwnd, msg, wparam, lparam)

    def do_paint(self):
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(self.hwnd, ctypes.byref(ps))
        g = w32.Gdi(hdc)
        rc = RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        w32.fill(g, (0, 0, rc.right, rc.bottom), self.bg)
        self.paint(g, rc.right, rc.bottom)
        g.free()
        user32.EndPaint(self.hwnd, ctypes.byref(ps))

    def paint(self, g, width, height):
        pass

    # ---- 滚动 ----
    def set_content(self, height):
        self.content_h = s(height)
        self.update_scrollbar()

    def update_scrollbar(self):
        if not self.scroll or not self.hwnd:
            return
        rc = RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        info = SCROLLINFO()
        info.cbSize = ctypes.sizeof(SCROLLINFO)
        info.fMask = w32.SIF_RANGE | w32.SIF_PAGE | w32.SIF_POS
        info.nMin = 0
        info.nMax = max(0, self.content_h - 1)
        info.nPage = max(1, rc.bottom)
        info.nPos = self.offset
        user32.SetScrollInfo(self.hwnd, 1, ctypes.byref(info), True)

    def scroll_by(self, delta):
        self.set_offset(self.offset + delta)

    def set_offset(self, value):
        if not self.scroll:
            return
        rc = RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        max_offset = max(0, self.content_h - rc.bottom)
        value = max(0, min(int(value), max_offset))
        if value == self.offset:
            return
        delta = self.offset - value
        self.offset = value
        for child in self.children:
            if child.hwnd:
                x, y, w, h = child.base
                user32.SetWindowPos(child.hwnd, None, x, y + delta, w, h,
                                    w32.SWP_NOZORDER | w32.SWP_NOACTIVATE)
                child.base = (x, y + delta, w, h)
        self.update_scrollbar()
        self.invalidate()

    def on_scroll(self, wparam, lparam):
        code = loword(wparam)
        rc = RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        line = s(56)
        if code == w32.SB_LINEUP:
            self.scroll_by(-line)
        elif code == w32.SB_LINEDOWN:
            self.scroll_by(line)
        elif code == w32.SB_PAGEUP:
            self.scroll_by(-rc.bottom)
        elif code == w32.SB_PAGEDOWN:
            self.scroll_by(rc.bottom)
        elif code == w32.SB_THUMBTRACK:
            info = SCROLLINFO()
            info.cbSize = ctypes.sizeof(SCROLLINFO)
            info.fMask = w32.SIF_TRACKPOS
            user32.GetScrollInfo(self.hwnd, 1, ctypes.byref(info))
            self.set_offset(info.nTrackPos)
        elif code == w32.SB_TOP:
            self.set_offset(0)
        elif code == w32.SB_BOTTOM:
            self.set_offset(self.content_h)


class Label(Widget):
    cls = "STATIC"
    style = w32.SS_LEFT | w32.SS_NOPREFIX

    def __init__(self, parent, text="", rect=(0, 0, 0, 0), px=13, weight=w32.FW_NORMAL,
                 color=TEXT, align=w32.DT_LEFT, multiline=False):
        self.color = color
        self.align = align
        self.multiline = multiline
        super().__init__(parent, text, rect, style=w32.SS_LEFT | w32.SS_NOPREFIX,
                         font_px=px, font_weight=weight)

    def on_message(self, msg, wparam, lparam):
        if self.multiline and msg == w32.WM_PAINT:
            self.paint_multiline()
            return 0
        if self.multiline and msg == w32.WM_ERASEBKGND:
            return 1
        return comctl32.DefSubclassProc(self.hwnd, msg, wparam, lparam)

    def paint_multiline(self):
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(self.hwnd, ctypes.byref(ps))
        g = w32.Gdi(hdc)
        rc = RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        w32.fill(g, (0, 0, rc.right, rc.bottom), getattr(self.parent, "bg", BG_APP))
        font = FONTS.get(self.font_px, self.font_weight)
        w32.text(g, self.get_text(), (0, 0, rc.right, rc.bottom), font, self.color,
                 self.align | w32.DT_WORDBREAK | w32.DT_NOPREFIX | w32.DT_EDITCONTROL)
        g.free()
        user32.EndPaint(self.hwnd, ctypes.byref(ps))


class Button(Widget):
    cls = "BUTTON"

    def __init__(self, parent, text="", rect=(0, 0, 0, 0), kind="normal", on_click=None,
                 px=12, radius=6):
        self.kind = kind
        self.on_click = on_click
        self.radius = radius
        self.hover = False
        self.pressed = False
        self._track = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE, None, 0)
        super().__init__(parent, text, rect,
                         style=w32.BS_PUSHBUTTON | w32.WS_TABSTOP | w32.BS_OWNERDRAW,
                         font_px=px)

    def on_command(self, code):
        if code == w32.BN_CLICKED and self.on_click:
            self.on_click()

    def on_message(self, msg, wparam, lparam):
        if msg == w32.WM_MOUSEMOVE:
            if not self.hover:
                self.hover = True
                self._track.hwndTrack = self.hwnd
                user32.TrackMouseEvent(ctypes.byref(self._track))
                self.invalidate()
            return 0
        if msg == w32.WM_MOUSELEAVE:
            self.hover = False
            self.pressed = False
            self.invalidate()
            return 0
        if msg == w32.WM_LBUTTONDOWN:
            self.pressed = True
            self.invalidate()
        elif msg == w32.WM_LBUTTONUP:
            self.pressed = False
            self.invalidate()
        elif msg == w32.WM_SETCURSOR:
            user32.SetCursor(user32.LoadCursorW(None, wt.LPCWSTR(w32.IDC_HAND)))
            return 1
        elif msg == w32.WM_KILLFOCUS or msg == w32.WM_SETFOCUS:
            self.invalidate()
        return comctl32.DefSubclassProc(self.hwnd, msg, wparam, lparam)

    def colors(self, disabled=False):
        if disabled:
            return 0xF1F1F1, 0x949494
        if self.kind == "primary":
            return (PRIMARY_HOVER if (self.hover or self.pressed) else PRIMARY), 0xFFFFFF
        if self.kind == "ghost":
            return (0xEDEDED if (self.hover or self.pressed) else None), TEXT
        return (BTN_PRESS if self.pressed else (BTN_HOVER if self.hover else BTN_BG)), TEXT

    def draw_item(self, di):
        g = w32.Gdi(di.hDC)
        enabled = not (di.itemState & ODS_DISABLED)
        bg, fg = self.colors(disabled=not enabled)
        l, t, r, b = di.rcItem.left, di.rcItem.top, di.rcItem.right, di.rcItem.bottom
        w32.fill(g, (l, t, r, b), getattr(self.parent, "bg", BG_APP))
        if bg is not None:
            w32.round_fill(g, (l, t, r, b), s(self.radius), bg)
        weight = w32.FW_SEMIBOLD if self.kind == "primary" else w32.FW_NORMAL
        font = FONTS.get(self.font_px, weight)
        offset = 1 if self.pressed else 0
        w32.text(g, self.get_text(), (l, t + offset, r, b + offset), font, fg,
                 w32.DT_CENTER | w32.DT_VCENTER | w32.DT_SINGLELINE | w32.DT_NOPREFIX)
        if di.itemState & ODS_FOCUS:
            w32.round_stroke(g, (l + s(2), t + s(2), r - s(2), b - s(2)),
                             s(max(1, self.radius - 1)), fg)
        g.free()


class Edit(Widget):
    cls = "EDIT"

    def __init__(self, parent, text="", rect=(0, 0, 0, 0), style=0, px=13):
        self.on_message_extra = None
        super().__init__(parent, text, rect,
                         style=w32.ES_AUTOHSCROLL | style, font_px=px)

    def on_message(self, msg, wparam, lparam):
        if self.on_message_extra:
            result = self.on_message_extra(msg, wparam, lparam)
            if result is not None:
                return result
        return comctl32.DefSubclassProc(self.hwnd, msg, wparam, lparam)


class Check(Widget):
    cls = "BUTTON"

    def __init__(self, parent, text="", rect=(0, 0, 0, 0), on_change=None, checked=False,
                 px=13):
        self.on_change = on_change
        self._silent = False
        super().__init__(parent, text, rect,
                         style=w32.BS_AUTOCHECKBOX | w32.WS_TABSTOP, font_px=px)
        self.set_checked(checked)

    def set_checked(self, value):
        self._silent = True
        user32.SendMessageW(self.hwnd, w32.BM_SETCHECK,
                            w32.WPARAM(w32.BST_CHECKED if value else w32.BST_UNCHECKED), 0)
        self._silent = False

    def is_checked(self):
        return user32.SendMessageW(self.hwnd, w32.BM_GETCHECK, 0, 0) == w32.BST_CHECKED

    def on_command(self, code):
        if code == w32.BN_CLICKED and self.on_change and not self._silent:
            self.on_change(self.is_checked())

    def on_message(self, msg, wparam, lparam):
        if msg == w32.WM_ERASEBKGND:
            return 1
        if msg == w32.WM_PAINT and not isinstance(self, Radio):
            ps = PAINTSTRUCT()
            hdc = user32.BeginPaint(self.hwnd, ctypes.byref(ps))
            g = w32.Gdi(hdc)
            rc = RECT()
            user32.GetClientRect(self.hwnd, ctypes.byref(rc))
            w32.fill(g, (0, 0, rc.right, rc.bottom), getattr(self.parent, "bg", BG_APP))
            enabled = user32.IsWindowEnabled(self.hwnd)
            checked = self.is_checked()
            box = s(16)
            top = (rc.bottom - box) // 2
            w32.round_fill(g, (0, top, box, top + box), s(3),
                           TEXT if checked and enabled else 0xFFFFFF,
                           TEXT if checked and enabled else 0xBABABA)
            if checked:
                ink = 0xFFFFFF if enabled else 0x999999
                w32.line(g, s(3), top + s(8), s(7), top + s(12), ink, s(2))
                w32.line(g, s(6), top + s(12), s(13), top + s(5), ink, s(2))
            w32.text(g, self.get_text(), (s(25), 0, rc.right, rc.bottom),
                     FONTS.get(self.font_px), TEXT if enabled else 0x999999)
            if user32.GetFocus() == self.hwnd:
                w32.round_stroke(g, (s(22), 0, rc.right, rc.bottom), s(3), MUTED)
            g.free()
            user32.EndPaint(self.hwnd, ctypes.byref(ps))
            return 0
        result = super().on_message(msg, wparam, lparam)
        if msg in (w32.WM_LBUTTONUP, w32.WM_KEYUP, w32.WM_SETFOCUS,
                   w32.WM_KILLFOCUS, w32.BM_SETCHECK, 0x000A):
            self.invalidate()
        return result


class Radio(Check):
    def __init__(self, parent, text="", rect=(0, 0, 0, 0), on_change=None, checked=False, px=13):
        Widget.__init__(self, parent, text, rect,
                        style=w32.BS_AUTORADIOBUTTON | w32.WS_TABSTOP, font_px=px)
        self.on_change = on_change
        self._silent = False
        self.set_checked(checked)


class Combo(Widget):
    cls = "COMBOBOX"

    def __init__(self, parent, items=(), rect=(0, 0, 0, 0), on_change=None, px=12,
                 item_h=28, index=0):
        self.items = list(items)
        self.on_change = on_change
        self._silent = False
        if parent is not None:
            parent.combo_item_h = item_h
        style = (w32.CBS_DROPDOWNLIST | w32.CBS_OWNERDRAWFIXED | w32.CBS_HASSTRINGS |
                 w32.CBS_NOINTEGRALHEIGHT | w32.WS_VSCROLL | w32.WS_TABSTOP)
        super().__init__(parent, "", rect, style=style, font_px=px)
        for text, _data in self.items:
            user32.SendMessageW(self.hwnd, w32.CB_ADDSTRING, w32.WPARAM(0),
                                _ptr(text))
        self.set_index(index)

    def move(self, x, y, w=None, h=None):
        # The native combo height includes its drop-down, not only the field.
        if h is not None:
            user32.SendMessageW(self.hwnd, 0x0153, -1, s(h - 4))  # CB_SETITEMHEIGHT
        super().move(x, y, w, (h or 34) + 240)

    def on_message(self, msg, wparam, lparam):
        if msg == w32.WM_ERASEBKGND:
            return 1
        if msg == w32.WM_PAINT:
            ps = PAINTSTRUCT()
            hdc = user32.BeginPaint(self.hwnd, ctypes.byref(ps))
            g = w32.Gdi(hdc)
            rc = RECT()
            user32.GetClientRect(self.hwnd, ctypes.byref(rc))
            w32.fill(g, (0, 0, rc.right, rc.bottom), getattr(self.parent, "bg", BG_APP))
            focused = user32.GetFocus() == self.hwnd
            w32.round_fill(g, (0, 0, rc.right, rc.bottom), s(5), FIELD_BG,
                           0x454545 if focused else None)
            w32.text(g, self.text(), (s(10), 0, rc.right - s(28), rc.bottom),
                     FONTS.get(self.font_px), TEXT if user32.IsWindowEnabled(self.hwnd) else HINT)
            cx, cy = rc.right - s(14), rc.bottom // 2
            w32.polygon(g, [(cx - s(3), cy - s(1)), (cx + s(3), cy - s(1)),
                            (cx, cy + s(3))], TEXT)
            g.free()
            user32.EndPaint(self.hwnd, ctypes.byref(ps))
            return 0
        result = super().on_message(msg, wparam, lparam)
        if msg in (w32.WM_SETFOCUS, w32.WM_KILLFOCUS, w32.CB_SETCURSEL):
            self.invalidate()
        return result

    def set_index(self, index):
        self._silent = True
        user32.SendMessageW(self.hwnd, w32.CB_SETCURSEL, w32.WPARAM(index), 0)
        self._silent = False

    def index(self):
        return user32.SendMessageW(self.hwnd, w32.CB_GETCURSEL, 0, 0)

    def data(self):
        i = self.index()
        return self.items[i][1] if 0 <= i < len(self.items) else None

    def text(self):
        i = self.index()
        return self.items[i][0] if 0 <= i < len(self.items) else ""

    def set_by_data(self, value):
        for i, (_text, data) in enumerate(self.items):
            if data == value:
                self.set_index(i)
                return

    def set_by_text(self, value):
        for i, (text, _data) in enumerate(self.items):
            if text == value:
                self.set_index(i)
                return

    def on_command(self, code):
        if code == w32.CBN_SELCHANGE and self.on_change and not self._silent:
            self.on_change(self.data())

    def draw_item(self, di):
        g = w32.Gdi(di.hDC)
        idx = di.itemID
        if idx == -1:
            value = self.text()
        elif 0 <= idx < len(self.items):
            value = self.items[idx][0]
        else:
            value = ""
        l, t, r, b = di.rcItem.left, di.rcItem.top, di.rcItem.right, di.rcItem.bottom
        w32.fill(g, (l, t, r, b), 0xE7E7E7 if (di.itemState & ODS_SELECTED) else 0xFFFFFF)
        w32.text(g, value, (l + s(9), t, r - s(4), b), FONTS.get(12), TEXT,
                 w32.DT_LEFT | w32.DT_VCENTER | w32.DT_SINGLELINE | w32.DT_NOPREFIX)
        g.free()


class Stepper(Panel):
    """数字输入：自绘圆角底 + 右侧上下箭头（不用 comctl32 的 updown）。"""

    def __init__(self, parent, rect=(0, 0, 0, 0), low=0, high=100, value=0, suffix="",
                 on_change=None, px=12):
        self.low, self.high = low, high
        self.suffix = suffix
        self.on_change = on_change
        self._silent = False
        self.hover_zone = 0
        super().__init__(parent, rect, bg=FIELD_BG)
        self.edit = Edit(self, "", (8, 0, max(20, rect[2] - 30), rect[3]),
                         style=w32.ES_RIGHT, px=px)
        self.edit.on_message_extra = self._edit_message
        self.set_value(value)

    def move(self, x, y, w=None, h=None):
        super().move(x, y, w, h)
        width, height = self.base[2] / SCALE, self.base[3] / SCALE
        self.edit.move(12, max(0, (height - 22) / 2), max(20, width - 48), 22)

    # ---- 数值 ----
    def set_value(self, value):
        self._silent = True
        value = max(self.low, min(self.high, int(value)))
        self.edit.set_text(f"{value}{self.suffix}")
        self._silent = False

    def value(self):
        raw = self.edit.get_text().replace(self.suffix, "").strip()
        try:
            return max(self.low, min(self.high, int(raw)))
        except ValueError:
            return self.low

    def _edit_message(self, msg, wparam, lparam):
        if msg == w32.WM_KILLFOCUS:
            self.set_value(self.value())
            if self.on_change:
                self.on_change(self.value())
        elif msg == w32.WM_CHAR and wparam == 13:
            self.set_value(self.value())
            if self.on_change:
                self.on_change(self.value())
            return 0
        return None

    def _step(self, delta):
        value = max(self.low, min(self.high, self.value() + delta))
        self.set_value(value)
        if self.on_change:
            self.on_change(value)

    # ---- 交互 ----
    def on_message(self, msg, wparam, lparam):
        if msg == w32.WM_LBUTTONDOWN:
            x, y = w32.loword(lparam), w32.signed_hiword(lparam)
            width = self.base[2]
            if x >= width - s(26):
                self._step(1 if y < self.base[3] // 2 else -1)
            else:
                user32.SetFocus(self.edit.hwnd)
            return 0
        if msg == w32.WM_MOUSEMOVE:
            x, y = w32.loword(lparam), w32.signed_hiword(lparam)
            zone = 0
            if x >= self.base[2] - s(26):
                zone = 1 if y < self.base[3] // 2 else 2
            if zone != self.hover_zone:
                self.hover_zone = zone
                self.invalidate()
            user32.SetCursor(user32.LoadCursorW(None, wt.LPCWSTR(
                w32.IDC_HAND if zone else w32.IDC_IBEAM)))
            return 0
        if msg == w32.WM_MOUSELEAVE:
            self.hover_zone = 0
            self.invalidate()
            return 0
        if msg == w32.WM_SETCURSOR:
            return 1
        return super().on_message(msg, wparam, lparam)

    def paint(self, g, width, height):
        ui_round = s(5)
        w32.fill(g, (0, 0, width, height), getattr(self.parent, "bg", BG_APP))
        w32.round_fill(g, (0, 0, width, height), ui_round, FIELD_BG)
        mid = height // 2
        for index, (top, bottom) in enumerate(((0, mid), (mid, height))):
            zone = index + 1
            w32.round_fill(g, (width - s(29), top + s(2), width - s(3), bottom - s(1)),
                           s(3), 0xCCCCCC if self.hover_zone == zone else 0xDEDEDE)
            cx = width - s(14)
            cy = (top + bottom) // 2
            size = s(4)
            if index == 0:
                pts = [(cx - size, cy + s(2)), (cx + size, cy + s(2)), (cx, cy - s(2))]
            else:
                pts = [(cx - size, cy - s(2)), (cx + size, cy - s(2)), (cx, cy + s(2))]
            w32.polygon(g, pts, 0x6B6B6B)


class ListView(Widget):
    cls = "SysListView32"

    def __init__(self, parent, columns=(), rect=(0, 0, 0, 0), on_select=None,
                 on_activate=None, px=13):
        self.columns = list(columns)
        self.on_select = on_select
        self.on_activate = on_activate
        self.rows = []
        style = (w32.LVS_REPORT | w32.LVS_SINGLESEL | w32.LVS_SHOWSELALWAYS |
                 w32.LVS_NOSORTHEADER | w32.WS_TABSTOP)
        super().__init__(parent, "", rect, style=style, font_px=px)
        user32.SendMessageW(self.hwnd, w32.LVM_SETEXTENDEDLISTVIEWSTYLE,
                            w32.WPARAM(w32.LVS_EX_FULLROWSELECT | w32.LVS_EX_DOUBLEBUFFER),
                            w32.LPARAM(w32.LVS_EX_FULLROWSELECT | w32.LVS_EX_DOUBLEBUFFER))
        for index, (title, width) in enumerate(self.columns):
            col = w32.LVCOLUMNW()
            col.mask = w32.LVCF_TEXT | w32.LVCF_WIDTH | w32.LVCF_SUBITEM
            col.iSubItem = index
            col.cx = s(width)
            buf = ctypes.create_unicode_buffer(title)
            col.pszText = ctypes.cast(buf, wt.LPWSTR)
            user32.SendMessageW(self.hwnd, w32.LVM_INSERTCOLUMNW, w32.WPARAM(index),
                                w32.LPARAM(ctypes.addressof(col)))
            _KEEP.append(buf)

    def set_rows(self, rows):
        self.rows = [list(r) for r in rows]
        user32.SendMessageW(self.hwnd, w32.WM_SETREDRAW, w32.WPARAM(0), 0)
        user32.SendMessageW(self.hwnd, w32.LVM_DELETEALLITEMS, 0, 0)
        for r, row in enumerate(self.rows):
            item = w32.LVITEMW()
            item.mask = w32.LVIF_TEXT
            item.iItem = r
            item.iSubItem = 0
            buf = ctypes.create_unicode_buffer(str(row[0]) if row else "")
            item.pszText = ctypes.cast(buf, wt.LPWSTR)
            user32.SendMessageW(self.hwnd, w32.LVM_INSERTITEMW, 0,
                                w32.LPARAM(ctypes.addressof(item)))
            _KEEP.append(buf)
            for c in range(1, len(self.columns)):
                sub = w32.LVITEMW()
                sub.iSubItem = c
                text = ctypes.create_unicode_buffer(str(row[c]) if c < len(row) else "")
                sub.pszText = ctypes.cast(text, wt.LPWSTR)
                user32.SendMessageW(self.hwnd, w32.LVM_SETITEMTEXTW, w32.WPARAM(r),
                                    w32.LPARAM(ctypes.addressof(sub)))
                _KEEP.append(text)
        user32.SendMessageW(self.hwnd, w32.WM_SETREDRAW, w32.WPARAM(1), 0)
        self.invalidate()
        if self.rows:
            self.select(0)

    def resize_columns(self, widths):
        for index, width in enumerate(widths):
            user32.SendMessageW(self.hwnd, w32.LVM_SETCOLUMNWIDTH, w32.WPARAM(index),
                                w32.LPARAM(s(width)))

    def select(self, index):
        item = w32.LVITEMW()
        item.mask = w32.LVIF_STATE
        item.state = w32.LVIS_SELECTED | w32.LVIS_FOCUSED
        item.stateMask = w32.LVIS_SELECTED | w32.LVIS_FOCUSED
        user32.SendMessageW(self.hwnd, w32.LVM_SETITEMSTATE, w32.WPARAM(index),
                            w32.LPARAM(ctypes.addressof(item)))

    def selected(self):
        return user32.SendMessageW(self.hwnd, w32.LVM_GETNEXTITEM,
                                   w32.WPARAM(-1), w32.LPARAM(w32.LVNI_SELECTED))

    def on_notify(self, code, lparam):
        if code == w32.LVN_ITEMCHANGED and self.on_select:
            self.on_select(self.selected())
        elif code == w32.NM_DBLCLK and self.on_activate:
            self.on_activate(self.selected())
        return False


def message(parent, text, title="青石五笔", kind="info"):
    flags = w32.MB_OK | w32.MB_TOPMOST
    flags |= {"info": w32.MB_ICONINFORMATION, "warn": w32.MB_ICONWARNING,
              "error": w32.MB_ICONERROR, "question": w32.MB_ICONQUESTION}.get(kind, 0)
    owner = parent.hwnd if parent is not None and getattr(parent, "hwnd", None) else None
    return user32.MessageBoxW(owner, text, title, flags)


def confirm(parent, text, title="青石五笔"):
    owner = parent.hwnd if parent is not None and getattr(parent, "hwnd", None) else None
    return user32.MessageBoxW(owner, text, title,
                              w32.MB_YESNO | w32.MB_ICONQUESTION | w32.MB_TOPMOST) == w32.IDYES


def _ofn(parent, title, filter_text, buf, save):
    ofn = w32.OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(w32.OPENFILENAMEW)
    ofn.hwndOwner = parent.hwnd if parent is not None and getattr(parent, "hwnd", None) else None
    ofn.lpstrFilter = filter_text
    ofn.lpstrFile = ctypes.cast(buf, wt.LPWSTR)
    ofn.nMaxFile = len(buf)
    ofn.lpstrTitle = title
    ofn.Flags = (w32.OFN_OVERWRITEPROMPT if save else w32.OFN_FILEMUSTEXIST) | \
        w32.OFN_PATHMUSTEXIST | w32.OFN_NOCHANGEDIR | w32.OFN_EXPLORER
    fn = w32.comdlg32.GetSaveFileNameW if save else w32.comdlg32.GetOpenFileNameW
    return buf.value if fn(ctypes.byref(ofn)) else ""


def open_file(parent, title, filter_text):
    return _ofn(parent, title, filter_text, ctypes.create_unicode_buffer(1024), False)


def save_file(parent, title, default_name, filter_text):
    return _ofn(parent, title, filter_text,
                ctypes.create_unicode_buffer(default_name, 1024), True)
