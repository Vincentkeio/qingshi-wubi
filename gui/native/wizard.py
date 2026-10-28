# -*- coding: utf-8 -*-
"""首次配置向导（原生实现）：选方案 → 选候选窗样式 → 完成。"""
import ctypes
import ctypes.wintypes as wt

from . import ui, w32
from .ui import Panel, Label, Button, Combo, Stepper
from .app import run_with_busy

user32 = w32.user32

SCHEMA_TEXT = {
    "wubi86": ("五笔 86", "王码86版原表 · 极点官方词库"),
    "wubi98": ("五笔 98", "98版码元体系"),
    "wubi06": ("新世纪五笔", "2008 新世纪版"),
}


class Wizard(Panel):
    cls = "QSWizard"
    popup = True

    def __init__(self, parent, cfg):
        self.children = []
        self.bg = ui.BG_APP
        self.scroll = False
        self.offset = 0
        self.content_h = 0
        self.combo_item_h = 26
        self._brush = None
        self.parent_app = parent
        self.cfg = cfg
        self.step = 0
        self.schema = cfg.current_schema()
        self.style = cfg.weasel_style()
        ui.register_class("QSWizard")
        ui.Widget.__init__(self, parent, "青石五笔 · 首次配置",
                           (0, 0, 660, 480),
                           style=w32.WS_POPUP | w32.WS_CAPTION | w32.WS_SYSMENU |
                           w32.WS_CLIPCHILDREN)
        self.btn_back = Button(self, "上一步", (0, 0, 90, 36), on_click=self.back)
        self.btn_next = Button(self, "下一步", (0, 0, 90, 36), kind="primary", on_click=self.next)
        self.cards = {}
        for sid, (name, desc) in SCHEMA_TEXT.items():
            self.cards[sid] = self._card(sid, name, desc)
        self.combo_theme = Combo(self, [(skin["name"], key) for key, skin in cfg.SKINS.items()],
                                 on_change=self._theme_changed)
        self.spin_page = Stepper(self, (0, 0, 112, 32), low=3, high=10,
                                 value=cfg.page_size(), suffix=" 个")
        self.preview = None
        self.layout_all()
        self._sync()

    def _card(self, sid, name, desc):
        from .pages import SchemaCard
        return SchemaCard(self, sid, name, desc, self.pick)

    def pick(self, sid):
        self.schema = sid
        for key, card in self.cards.items():
            card.set_checked(key == sid)
        self.invalidate()

    def _theme_changed(self, _data):
        self.invalidate()

    def layout_all(self):
        height = int(self.base[3] / (ui.SCALE or 1))
        for index, sid in enumerate(("wubi86", "wubi98", "wubi06")):
            self.cards[sid].move(36 + index * 196, 150, 186, 100)
        self.combo_theme.move(36, 182, 240, 32)
        self.spin_page.move(320, 182, 112, 32)
        self.btn_back.move(660 - 36 - 90 - 10 - 90, height - 56, 90, 36)
        self.btn_next.move(660 - 36 - 90, height - 56, 90, 36)

    def _sync(self):
        for key, card in self.cards.items():
            card.set_checked(key == self.schema)
        self.combo_theme.set_by_data(self.style["color_scheme"])
        self.spin_page.set_value(self.cfg.page_size())
        for card in self.cards.values():
            card.show(self.step == 0)
        self.combo_theme.show(self.step == 1)
        self.spin_page.show(self.step == 1)
        self.btn_back.show(self.step > 0)
        self.btn_next.set_text("开始使用" if self.step == 1 else "下一步")
        self.invalidate()

    def show_modal(self):
        owner = self.parent_app.hwnd if self.parent_app else None
        rect = w32.RECT()
        w, h = ui.s(660), ui.s(480)
        if owner:
            user32.GetWindowRect(owner, ctypes.byref(rect))
            x = rect.left + (rect.right - rect.left - w) // 2
            y = rect.top + (rect.bottom - rect.top - h) // 2
            user32.SetWindowPos(self.hwnd, None, x, y, w, h, w32.SWP_NOZORDER)
            user32.EnableWindow(owner, False)
        user32.ShowWindow(self.hwnd, w32.SW_SHOW)
        self.invalidate()
        msg = w32.MSG()
        while user32.IsWindow(self.hwnd):
            if not user32.GetMessageW(ctypes.byref(msg), None, 0, 0):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if owner:
            user32.EnableWindow(owner, True)

    def close(self):
        user32.DestroyWindow(self.hwnd)

    def back(self):
        self.step = max(0, self.step - 1)
        self._sync()

    def next(self):
        if self.step == 0:
            self.step = 1
            self._sync()
            return
        self.finish()

    def finish(self):
        cfg = self.cfg
        style = dict(self.style)
        style["color_scheme"] = self.combo_theme.data() or style["color_scheme"]
        page_size = self.spin_page.value()
        try:
            cfg.write_default(self.schema, page_size)
            cfg.write_weasel(style)
        except Exception as error:      # noqa: BLE001
            ui.message(self, str(error), "保存失败", "warn")
            return
        ok = run_with_busy(self, "正在应用设置", "正在重新部署输入法配置…",
                           "首次配置需要重建索引，通常几秒到十几秒。",
                           lambda: cfg.deploy(wait=True) and cfg.restart_server())
        self.close()
        ui.message(self.parent_app, "设置已保存并重新部署。" if ok else
                   "设置已保存，部署未完成。请在设置中心点「应用」重试。",
                   "首次配置", "info" if ok else "warn")
        if self.parent_app:
            self.parent_app.load()

    def on_message(self, msg, wparam, lparam):
        if msg == w32.WM_CLOSE:
            self.close()
            return 0
        return super().on_message(msg, wparam, lparam)

    def paint(self, g, width, height):
        step = self.step
        ui.w32.text(g, f"第 {step + 1} 步 / 共 2 步", (ui.s(36), ui.s(24), width - ui.s(72),
                                                      ui.s(44)),
                    ui.FONTS.get(11, w32.FW_SEMIBOLD), ui.MUTED)
        if step == 0:
            ui.w32.text(g, "选择默认输入方案", (ui.s(36), ui.s(52), width - ui.s(72), ui.s(84)),
                        ui.FONTS.get(21, w32.FW_SEMIBOLD), ui.TEXT_STRONG)
            ui.w32.text(g, "三套码表都内置，之后随时可以在设置中心切换。",
                        (ui.s(36), ui.s(88), width - ui.s(72), ui.s(112)),
                        ui.FONTS.get(12), ui.MUTED)
        else:
            ui.w32.text(g, "选择候选窗样式", (ui.s(36), ui.s(52), width - ui.s(72), ui.s(84)),
                        ui.FONTS.get(21, w32.FW_SEMIBOLD), ui.TEXT_STRONG)
            ui.w32.text(g, "左边选配色，右边设每页候选数量；之后可在「外观」页细调。",
                        (ui.s(36), ui.s(88), width - ui.s(72), ui.s(112)),
                        ui.FONTS.get(12), ui.MUTED)
            ui.w32.text(g, "候选窗主题", (ui.s(36), ui.s(150), ui.s(240), ui.s(172)),
                        ui.FONTS.get(12, w32.FW_SEMIBOLD), ui.TEXT)
            ui.w32.text(g, "每页数量", (ui.s(320), ui.s(150), ui.s(240), ui.s(172)),
                        ui.FONTS.get(12, w32.FW_SEMIBOLD), ui.TEXT)
        ui.w32.line(g, ui.s(36), height - ui.s(76), width - ui.s(36), height - ui.s(76),
                    ui.BORDER)


def open_wizard(app, cfg):
    dialog = Wizard(app, cfg)
    dialog.show_modal()
    return dialog
