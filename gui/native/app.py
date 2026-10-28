# -*- coding: utf-8 -*-
"""原生设置中心主窗口：顶部品牌栏 + 左侧分类导航 + 页面容器 + 底部按钮。"""
import ctypes
import ctypes.wintypes as wt
import threading
import time

from . import ui, w32
from .ui import Panel, Label, Button

user32 = w32.user32
gdi32 = w32.gdi32

NAV_W = 204
TOP_H = 74
FOOTER_H = 70
MIN_W = 900
MIN_H = 620

NAV_ITEMS = ["常用设置", "外观", "词库", "自定义词条", "自定义词序",
             "快捷键", "备份与更新", "关于"]

PM_REMOVE = 0x0001
user32.PeekMessageW.argtypes = [ctypes.POINTER(w32.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(w32.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(w32.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.GetMessageW.argtypes = [ctypes.POINTER(w32.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.FindWindowW.restype = wt.HWND
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(w32.RECT)]
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
user32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]


class TopBar(Panel):
    """品牌栏：左 logo + 名称，右版本号。"""

    def __init__(self, parent, rect, version):
        self.version = version
        super().__init__(parent, rect, bg=ui.BG_APP)

    def paint(self, g, width, height):
        ui.brand_mark(g, 30, 20, 42)
        ui.w32.text(g, "青石五笔输入法", (ui.s(84), ui.s(20), ui.s(360), ui.s(42)),
                    ui.FONTS.get(16, w32.FW_SEMIBOLD), ui.TEXT_STRONG)
        ui.w32.text(g, "五笔输入与外观设置", (ui.s(84), ui.s(44), ui.s(360), ui.s(62)),
                    ui.FONTS.get(12), ui.MUTED)
        ui.w32.text(g, f"设置中心　v{self.version}", (width - ui.s(220), ui.s(26),
                                                    width - ui.s(32), ui.s(56)),
                    ui.FONTS.get(12), ui.MUTED, w32.DT_RIGHT | w32.DT_VCENTER | w32.DT_SINGLELINE)


class Nav(Panel):
    """左侧分类导航：白色卡片条目，底部带首次配置入口。"""

    ITEM_H = 34
    GAP = 12

    def __init__(self, parent, rect, on_select, on_wizard):
        self.items = list(NAV_ITEMS)
        self.selected = 0
        self.hover = -1
        self.on_select = on_select
        self.on_wizard = on_wizard
        self.top = 51
        self._track = ui.TRACKMOUSEEVENT(ctypes.sizeof(ui.TRACKMOUSEEVENT), ui.TME_LEAVE, None, 0)
        super().__init__(parent, rect, bg=ui.BG_APP)

    def item_rect(self, index):
        y = self.top + index * (self.ITEM_H + self.GAP)
        return (ui.s(29), ui.s(y), ui.s(148), ui.s(self.ITEM_H))

    def hit(self, x, y):
        for i in range(len(self.items)):
            l, t, w, h = self.item_rect(i)
            if l <= x < l + w and t <= y < t + h:
                return i
        return -1

    def on_message(self, msg, wparam, lparam):
        if msg == w32.WM_MOUSEMOVE:
            x, y = w32.loword(lparam), w32.signed_hiword(lparam)
            idx = self.hit(x, y)
            if idx != self.hover:
                self.hover = idx
                self.invalidate()
            if self.hover >= 0:
                self._track.hwndTrack = self.hwnd
                user32.TrackMouseEvent(ctypes.byref(self._track))
                user32.SetCursor(user32.LoadCursorW(None, wt.LPCWSTR(w32.IDC_HAND)))
            return 0
        if msg == w32.WM_MOUSELEAVE:
            self.hover = -1
            self.invalidate()
            return 0
        if msg == w32.WM_LBUTTONDOWN:
            idx = self.hit(w32.loword(lparam), w32.signed_hiword(lparam))
            if idx >= 0 and idx != self.selected:
                self.select(idx)
            return 0
        return super().on_message(msg, wparam, lparam)

    def select(self, index):
        self.selected = index
        self.invalidate()
        if self.on_select:
            self.on_select(index)

    def paint(self, g, width, height):
        ui.w32.text(g, "设置分类", (ui.s(34), ui.s(22), width - ui.s(20), ui.s(40)),
                    ui.FONTS.get(11, w32.FW_SEMIBOLD), ui.MUTED)
        for i, name in enumerate(self.items):
            l, t, w, h = self.item_rect(i)
            if i == self.selected:
                ui.w32.round_fill(g, (l, t, l + w, t + h), ui.s(6), 0xE2E2E2)
            else:
                ui.w32.round_fill(g, (l, t + ui.s(2), l + w, t + h + ui.s(2)), ui.s(6), 0xE9E9E9)
                ui.w32.round_fill(g, (l, t, l + w, t + h), ui.s(6), 0xEDEDED if i == self.hover else 0xF7F7F7)
                ui.w32.line(g, l + ui.s(8), t + h - 1, l + w - ui.s(8), t + h - 1, 0xE4E4E4)
            ui.w32.text(g, name, (l + ui.s(17), t, l + w - ui.s(8), t + h),
                        ui.FONTS.get(13, w32.FW_SEMIBOLD if i == self.selected else w32.FW_NORMAL),
                        ui.TEXT, w32.DT_LEFT | w32.DT_VCENTER | w32.DT_SINGLELINE)
        y = height / ui.SCALE - 154
        ui.w32.text(g, "首次配置", (ui.s(36), ui.s(y), width - ui.s(24), ui.s(y + 22)),
                    ui.FONTS.get(14, w32.FW_SEMIBOLD), ui.TEXT)
        ui.w32.text(g, "按步骤选择方案与候选窗\n样式", (ui.s(36), ui.s(y + 27), width - ui.s(24), ui.s(y + 61)),
                    ui.FONTS.get(12), ui.MUTED, w32.DT_LEFT | w32.DT_WORDBREAK | w32.DT_NOPREFIX)
        ui.w32.text(g, "v" + ui.APP_VERSION, (ui.s(34), height - ui.s(34), width - ui.s(20),
                                              height - ui.s(12)), ui.FONTS.get(12), ui.MUTED)


class Footer(Panel):
    def __init__(self, parent, rect, on_ok, on_apply, on_cancel):
        super().__init__(parent, rect, bg=ui.BG_APP)
        self.status = Label(self, "", (28, 0, 420, FOOTER_H), px=12, color=ui.MUTED)
        self.btn_cancel = Button(self, "取消", (0, 0, 58, 36), kind="ghost", on_click=on_cancel)
        self.btn_apply = Button(self, "应用", (0, 0, 80, 36), kind="normal", on_click=on_apply)
        self.btn_ok = Button(self, "确定", (0, 0, 80, 36), kind="primary", on_click=on_ok)

    def layout(self, width):
        y = 14
        self.btn_ok.move(width - 32 - 58, y, 58, 36)
        self.btn_apply.move(width - 32 - 58 * 2 - 6, y, 58, 36)
        self.btn_cancel.move(width - 32 - 58 * 3 - 12, y, 58, 36)
        self.status.move(28, 0, max(120, width - 380), FOOTER_H)

    def set_status(self, text, kind="muted"):
        self.status.set_text(text)
        self.status.color = {"muted": ui.MUTED, "ok": 0x2C6B3F, "err": 0xA52626}.get(kind, ui.MUTED)
        self.status.invalidate()


class BusyWindow(Panel):
    """耗时操作时的等待窗口（自绘 + 动画进度条）。"""

    cls = "QSBusy"
    popup = True

    def __init__(self, parent, title, message, hint):
        ui.register_class("QSBusy")
        self.children = []
        self.bg = ui.BG_PANEL
        self.scroll = False
        self.offset = 0
        self.content_h = 0
        self.combo_item_h = 26
        self._brush = None
        self.title_text = title
        self.message = message
        self.hint = hint
        self.phase = 0
        self.parent_window = parent
        ui.Widget.__init__(self, parent, title, (0, 0, 420, 150),
                           style=w32.WS_POPUP | w32.WS_BORDER | w32.WS_CLIPCHILDREN)
        user32.SetTimer(self.hwnd, 1, 33, None)

    def show_centered(self):
        owner = self.parent_window.hwnd if self.parent_window else None
        rect = w32.RECT()
        w, h = ui.s(420), ui.s(150)
        if owner:
            user32.GetWindowRect(owner, ctypes.byref(rect))
            x = rect.left + (rect.right - rect.left - w) // 2
            y = rect.top + (rect.bottom - rect.top - h) // 2
            user32.SetWindowPos(self.hwnd, None, x, y, w, h, w32.SWP_NOZORDER)
        user32.ShowWindow(self.hwnd, w32.SW_SHOW)
        self.invalidate()
        if owner:
            user32.EnableWindow(owner, False)

    def close(self):
        user32.KillTimer(self.hwnd, 1)
        if self.parent_window:
            user32.EnableWindow(self.parent_window.hwnd, True)
        user32.DestroyWindow(self.hwnd)

    def on_message(self, msg, wparam, lparam):
        if msg == w32.WM_TIMER:
            self.phase = (self.phase + 1) % 40
            self.invalidate()
            return 0
        if msg == w32.WM_CLOSE:
            return 0
        return super().on_message(msg, wparam, lparam)

    def paint(self, g, width, height):
        ui.w32.text(g, self.message, (ui.s(24), ui.s(22), width - ui.s(24), ui.s(50)),
                    ui.FONTS.get(15, w32.FW_SEMIBOLD), ui.TEXT_STRONG)
        ui.w32.text(g, self.hint, (ui.s(24), ui.s(52), width - ui.s(24), ui.s(96)),
                    ui.FONTS.get(12), ui.MUTED, w32.DT_LEFT | w32.DT_WORDBREAK | w32.DT_NOPREFIX)
        bar = (ui.s(24), ui.s(112), width - ui.s(24), ui.s(118))
        ui.w32.round_fill(g, bar, ui.s(3), 0xE5E5E5)
        span = bar[2] - bar[0]
        seg = span // 4
        pos = (self.phase % 40) / 40.0 * (span + seg) - seg
        left = int(max(bar[0], bar[0] + pos))
        right = int(min(bar[2], bar[0] + pos + seg))
        if right > left:
            ui.w32.round_fill(g, (left, bar[1], right, bar[3]), ui.s(3), 0x202020)


def pump():
    msg = w32.MSG()
    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def run_with_busy(parent, title, message, hint, func):
    window = BusyWindow(parent, title, message, hint)
    window.show_centered()
    box = {}

    def worker():
        try:
            box["value"] = func()
        except Exception as error:      # noqa: BLE001
            box["error"] = error

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while thread.is_alive():
        pump()
        time.sleep(0.01)
    pump()
    window.close()
    if "error" in box:
        raise box["error"]
    return box.get("value")


class App:
    """主窗口。"""

    cls = "QSApp"

    def __init__(self, cfg):
        from .pages import PAGES
        from rime_config import APP_VER
        ui.register_class("QSApp")
        ui.APP_VERSION = APP_VER
        self.cfg = cfg
        self.children = []
        self.pages = []
        style = w32.WS_OVERLAPPEDWINDOW | w32.WS_CLIPCHILDREN
        window_w, window_h = ui.client_window_size(1060, 720, style)
        self.hwnd = user32.CreateWindowExW(
            0, self.cls, "青石五笔输入法 · 设置",
            style,
            w32.CW_USEDEFAULT, w32.CW_USEDEFAULT, window_w, window_h,
            None, None, w32.kernel32.GetModuleHandleW(None), None)
        ui.BY_HWND[self.hwnd] = self
        self.top = TopBar(self, (0, 0, 0, TOP_H), APP_VER)
        self.nav = Nav(self, (0, TOP_H, NAV_W, 0), self.switch, self.open_wizard)
        self.footer = Footer(self, (0, 0, 0, FOOTER_H), self.ok, self.apply, self.close)
        self.wizard = Button(self.nav, "打开设置向导", (0, 0, 194, 38), on_click=self.open_wizard)
        for factory in PAGES:
            page = factory(self)
            page.show(False)
            self.pages.append(page)
        self.current = -1
        self.phrase_snapshot = []
        self.switch(0)
        self.load()
        ui.center_on_monitor(self.hwnd, window_w, window_h, fit=True)

    # ---- 窗口消息 ----
    def on_message(self, msg, wparam, lparam):
        ready = bool(getattr(self, "pages", None))
        if msg == w32.WM_SIZE:
            if ready:
                self.relayout()
            return 0
        if msg == w32.WM_ERASEBKGND:
            return 1
        if msg == w32.WM_PAINT:
            if not ready:
                return user32.DefWindowProcW(self.hwnd, msg, wparam, lparam)
            ps = w32.PAINTSTRUCT()
            hdc = user32.BeginPaint(self.hwnd, ctypes.byref(ps))
            g = w32.Gdi(hdc)
            rc = w32.RECT()
            user32.GetClientRect(self.hwnd, ctypes.byref(rc))
            ui.w32.fill(g, (0, 0, rc.right, rc.bottom), ui.BG_APP)
            g.free()
            user32.EndPaint(self.hwnd, ctypes.byref(ps))
            return 0
        if msg in (w32.WM_CTLCOLORSTATIC, w32.WM_CTLCOLORBTN):
            hdc = w32.HDC(wparam)
            gdi32.SetBkMode(hdc, w32.TRANSPARENT)
            gdi32.SetTextColor(hdc, w32.rgb(ui.TEXT))
            return 1
        if msg == w32.WM_DRAWITEM:
            di = ctypes.cast(lparam, ctypes.POINTER(ui.DRAWITEMSTRUCT)).contents
            target = ui.BY_HWND.get(di.hwndItem)
            if target is not None and hasattr(target, "draw_item"):
                target.draw_item(di)
                return 1
            return 0
        if msg == w32.WM_COMMAND:
            target = ui.BY_HWND.get(lparam)
            if target is not None:
                target.on_command(w32.hiword(wparam))
                return 0
        if msg == w32.WM_GETMINMAXINFO:
            info = ctypes.cast(lparam, ctypes.POINTER(MINMAXINFO)).contents
            info.ptMinTrackSize.x = ui.s(MIN_W)
            info.ptMinTrackSize.y = ui.s(MIN_H)
            return 0
        if msg == w32.WM_CLOSE:
            user32.DestroyWindow(self.hwnd)
            return 0
        if msg == w32.WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(self.hwnd, msg, wparam, lparam)

    # ---- 布局 ----
    def relayout(self):
        rc = w32.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        w, h = rc.right, rc.bottom
        self.top.move(0, 0, w / (ui.SCALE or 1), TOP_H)
        self.nav.move(0, TOP_H, NAV_W, h / (ui.SCALE or 1) - TOP_H - FOOTER_H)
        self.footer.move(0, h / (ui.SCALE or 1) - FOOTER_H, w / (ui.SCALE or 1), FOOTER_H)
        self.footer.layout(int(w / (ui.SCALE or 1)))
        nav_h = self.nav.base[3] / (ui.SCALE or 1)
        self.nav.ITEM_H, self.nav.GAP = (28, 4) if nav_h < 550 else (34, 12)
        self.wizard.move(36, nav_h - 90, 142, 36)
        for page in self.pages:
            page.move(NAV_W, TOP_H, w / (ui.SCALE or 1) - NAV_W,
                      h / (ui.SCALE or 1) - TOP_H - FOOTER_H)
            page.layout(int(w / (ui.SCALE or 1) - NAV_W))
            page.set_content(page.content_height)
        # Resizing must also repaint the custom sidebar and brand strip.
        self.nav.invalidate()
        self.top.invalidate()

    def switch(self, index):
        if index == self.current:
            return
        if self.current >= 0:
            self.pages[self.current].show(False)
        self.current = index
        self.nav.selected = index
        self.nav.invalidate()
        page = self.pages[index]
        page.show(True)
        page.set_offset(0)
        rc = w32.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        page.layout(int(rc.right / (ui.SCALE or 1) - NAV_W))
        page.set_content(page.content_height)
        page.invalidate()
        page.on_show()

    def open_wizard(self):
        from .wizard import open_wizard
        open_wizard(self, self.cfg)
        self.load()

    def close(self):
        user32.PostMessageW(self.hwnd, w32.WM_CLOSE, 0, 0)

    # ---- 配置读写 ----
    def load(self):
        for page in self.pages:
            page.load()

    def ok(self):
        if self.apply(silent=True):
            self.close()

    def apply(self, silent=False):
        """点「应用」：写配置 → 按需部署 / 重启服务。"""
        import hotkeys
        from rime_config import apply_plan
        from fixed_order import ensure_fixed_order

        self.footer.set_status("正在保存…")
        pump()
        try:
            values = self.collect()
        except ValueError as error:
            ui.message(self, str(error), "无法保存", "warn")
            self.footer.set_status("保存失败：请检查填写内容", "err")
            return False
        cfg = self.cfg
        before = cfg.weasel_style()
        hot = values["hotkeys"]
        try:
            shortcut_values = hotkeys.validate(hot.values())
        except ValueError as error:
            self.switch(5)
            hot.show_error(str(error))
            ui.message(self, str(error), "快捷键未保存", "warn")
            return False
        shift_commit = values["shift_commit"] and "Shift" in shortcut_values["ascii_mode"]
        shortcuts_changed = (shortcut_values != hot.snapshot or
                             shift_commit != hot.shift_snapshot)
        try:
            cfg.write_default(values["schema"], values["page_size"])
            cfg.write_schema_switches(values["schema"], {
                "traditional": values["traditional"],
                "full_shape": values["full_shape"],
                "ascii_punct": values["ascii_punct"],
                "shift_commit": values["shift_commit"],
                "shift_toggle": "Shift" in shortcut_values["ascii_mode"],
            })
            cfg.set_shift_letter_direct(values["shift_direct"])
            cfg.set_no_candidate_beep(values["beep"])
            cfg.set_auto_commit_unique(values["auto_commit"])
            cfg.write_weasel(values["style"])
            ensure_fixed_order(cfg.dir)
            if shortcuts_changed or cfg.exists(hotkeys.FILE):
                hotkeys.apply(cfg.dir, shortcut_values, values["shift_commit"])
        except Exception as error:      # noqa: BLE001
            ui.message(self, str(error), "保存失败", "error")
            self.footer.set_status("保存失败", "err")
            return False

        appearance_changed = cfg.weasel_style() != before
        phrases_changed = values["phrases"] != self.phrase_snapshot
        needs_deploy = cfg.appearance_needs_deploy()
        plan = apply_plan(appearance_changed, phrases_changed, needs_deploy)

        if shortcuts_changed or hotkeys.needs_deploy(cfg.dir):
            ok = run_with_busy(self, "正在应用快捷键", "正在更新输入法配置…",
                               "完成后，三套五笔方案会使用新的快捷键。",
                               lambda: cfg.deploy(wait=True) and cfg.restart_server())
            if ok:
                hot.snapshot = shortcut_values
                hot.shift_snapshot = shift_commit
                self.phrase_snapshot = list(values["phrases"])
            text = ("快捷键已保存并生效。" if ok else
                    "快捷键已保存，但没有完成应用；请再次点击「应用」重试。")
        elif plan == "restart":
            ok = run_with_busy(self, "正在应用词条", "正在重启输入法服务…",
                               "自定义词条是稳定词典，服务重启后才会出现在候选里。",
                               lambda: cfg.restart_server())
            self.phrase_snapshot = list(values["phrases"])
            text = ("词条已保存，输入法服务已重启，新词条会出现在候选里。" if ok else
                    "词条已保存，但服务没能重启；重新切换一次输入法后新词条才生效。")
        elif appearance_changed:
            def refresh():
                if needs_deploy:
                    cfg.deploy(wait=True)
                return cfg.reload(wait=True)
            ok = run_with_busy(self, "正在应用外观", "正在刷新候选窗样式…",
                               "配色、字体和圆角会直接应用到已经打开的候选窗，不用重启。",
                               refresh)
            text = ("外观已保存并立即生效，继续打字就能看到新候选窗。" if ok else
                    "外观已保存；输入法服务当前没有运行，下次打字时会自动读取新外观。")
        elif needs_deploy:
            ok = run_with_busy(self, "正在应用外观", "正在更新候选窗外观…",
                               "完成后，现有输入会话会重新读取所选配色。",
                               lambda: cfg.deploy(wait=True))
            text = "配置已保存并立即生效。" if ok else "配置已保存，但部署没有完成。"
        else:
            ok = cfg.reload(wait=True)
            text = ("配置已保存并立即生效。" if ok else
                    "配置已保存，但输入法服务当前没有运行；下次打字时它会自动读取新设置。")

        self.footer.set_status(text, "ok" if ok else "err")
        if not silent:
            ui.message(self, text, "已应用", "info")
        self.load()
        return True

    def collect(self):
        data = {}
        for page in self.pages:
            data.update(page.collect())
        return data


class MINMAXINFO(ctypes.Structure):
    _fields_ = [("ptReserved", wt.POINT), ("ptMaxSize", wt.POINT), ("ptMaxPosition", wt.POINT),
                ("ptMinTrackSize", wt.POINT), ("ptMaxTrackSize", wt.POINT)]
