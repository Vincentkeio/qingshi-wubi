# -*- coding: utf-8 -*-
"""八个设置页面：全部用原生控件手写布局。"""
import ctypes
import ctypes.wintypes as wt
import datetime
import os
import shutil

from . import ui, w32
from .ui import Panel, Label, Button, Check, Combo, Stepper, ListView
from .app import run_with_busy

from rime_config import SCHEMAS, APP_VER

PAD = 28
SCROLLBAR = 18


def s(v):
    return ui.s(v)


# ---------------------------------------------------------------- 通用小组件
class SchemaCard(Panel):
    """默认方案卡片：自绘背景 + 标题 + 说明，点哪都算选中。"""

    def __init__(self, parent, sid, name, desc, on_click):
        super().__init__(parent, rect=(0, 0, 10, 104), bg=ui.BG_APP)
        self.sid, self.name, self.desc = sid, name, desc
        self.on_click = on_click
        self.checked = False
        self.hover = False
        self._track = ui.TRACKMOUSEEVENT(ctypes.sizeof(ui.TRACKMOUSEEVENT), ui.TME_LEAVE, None, 0)

    def set_checked(self, value):
        self.checked = value
        self.invalidate()

    def on_message(self, msg, wparam, lparam):
        if msg == w32.WM_MOUSEMOVE:
            if not self.hover:
                self.hover = True
                self._track.hwndTrack = self.hwnd
                user32.TrackMouseEvent(ctypes.byref(self._track))
                self.invalidate()
            user32.SetCursor(user32.LoadCursorW(None, wt.LPCWSTR(w32.IDC_HAND)))
            return 0
        if msg == w32.WM_MOUSELEAVE:
            self.hover = False
            self.invalidate()
            return 0
        if msg == w32.WM_LBUTTONDOWN:
            if self.on_click:
                self.on_click(self.sid)
            return 0
        return super().on_message(msg, wparam, lparam)

    def paint(self, g, width, height):
        bg = 0xE2E2E2 if self.checked else (0xE9E9E9 if self.hover else 0xF0F0F0)
        ui.w32.round_fill(g, (0, 0, width, height), s(8), bg)
        r = s(9)
        cx, cy = s(15), s(13)
        ui.w32.round_fill(g, (cx, cy, cx + 2 * r, cy + 2 * r), r, 0xFFFFFF)
        ui.w32.round_stroke(g, (cx, cy, cx + 2 * r, cy + 2 * r), r,
                            0x252525 if self.checked else 0xBABABA)
        if self.checked:
            ui.w32.round_fill(g, (cx + s(4), cy + s(4), cx + 2 * r - s(4), cy + 2 * r - s(4)),
                              r - s(4), 0x252525)
            ui.w32.text(g, "当前默认", (width - s(84), s(14), width - s(16), s(32)),
                        ui.FONTS.get(11), ui.TEXT,
                        w32.DT_RIGHT | w32.DT_VCENTER | w32.DT_SINGLELINE)
        ui.w32.text(g, self.name, (s(15), s(46), width - s(14), s(68)),
                    ui.FONTS.get(14, w32.FW_SEMIBOLD), ui.TEXT)
        ui.w32.text(g, self.desc, (s(15), s(77), width - s(12), s(97)),
                    ui.FONTS.get(12), ui.MUTED)


class MetricCard(Panel):
    def __init__(self, parent, title):
        super().__init__(parent, rect=(0, 0, 10, 108), bg=ui.BG_APP)
        self.title = title
        self.value = "读取中…"

    def set_value(self, value):
        self.value = value
        self.invalidate()

    def paint(self, g, width, height):
        ui.w32.text(g, self.title, (s(16), s(14), width - s(16), s(32)), ui.FONTS.get(12), ui.MUTED)
        ui.w32.text(g, self.value, (s(16), s(34), width - s(16), s(72)),
                    ui.FONTS.get(24, w32.FW_SEMIBOLD), ui.TEXT)
        ui.w32.text(g, "词条", (s(16), s(72), width - s(16), s(92)), ui.FONTS.get(12), ui.MUTED)


class CandidatePreview(Panel):
    """候选窗效果预览：圆角、配色、高亮项都按真实皮肤画。"""

    def __init__(self, parent):
        super().__init__(parent, rect=(0, 0, 10, 108), bg=ui.BG_APP)
        self.set_skin(0xFFFFFF, 0x263750, 0xDCE5F1, 0x2868D7, 0xFFFFFF, 0x718198, 6)

    def set_skin(self, bg, fg, border, hl_bg, hl_fg, comment, radius):
        self.skin = (bg, fg, border, hl_bg, hl_fg, comment, radius)
        self.invalidate()

    def paint(self, g, width, height):
        bg, fg, border, hl_bg, hl_fg, comment, radius = self.skin
        ui.w32.round_fill(g, (0, 0, width, height), s(max(2, radius)), bg, border)
        ui.w32.text(g, "青石五笔　五笔 86", (s(14), s(10), width - s(14), s(28)),
                    ui.FONTS.get(11), comment)
        y = s(34)
        items = [("1  文字", hl_bg, hl_fg), ("2  输入", None, fg), ("3  编码", None, fg)]
        x = s(14)
        for text, chip_bg, chip_fg in items:
            w = ui.w32.text_width(g.hdc, text, ui.FONTS.get(11)) + s(18)
            if chip_bg is not None:
                ui.w32.round_fill(g, (x, y, x + w, y + s(24)), s(max(2, radius - 2)), chip_bg)
            ui.w32.text(g, text, (x, y, x + w, y + s(24)), ui.FONTS.get(11), chip_fg,
                        w32.DT_CENTER | w32.DT_VCENTER | w32.DT_SINGLELINE)
            x += w + s(6)


class HotkeyField(Panel):
    """快捷键录入框：点击后按下组合键即可录入。"""

    VK_NAMES = {
        0x20: "space", 0x08: "BackSpace", 0x09: "Tab", 0x0D: "Return", 0x1B: "Escape",
        0x2D: "Insert", 0x2E: "Delete", 0x24: "Home", 0x23: "End", 0x25: "Left",
        0x26: "Up", 0x27: "Right", 0x28: "Down", 0x14: "Caps_Lock",
        0x21: "Page_Up", 0x22: "Page_Down",
        0xBA: "semicolon", 0xBB: "equal", 0xBC: "comma", 0xBD: "minus", 0xBE: "period",
        0xBF: "slash", 0xC0: "grave", 0xDB: "bracketleft", 0xDC: "backslash",
        0xDD: "bracketright", 0xDE: "apostrophe",
    }

    def __init__(self, parent, action, slot, allow_shift_only=False, on_change=None):
        super().__init__(parent, rect=(0, 0, 10, 34), bg=ui.BG_APP)
        self.action = action
        self.slot = slot
        self.allow_shift_only = allow_shift_only
        self.on_change = on_change
        self.value = ""
        self.recording = False
        self.hover = False
        self.got_key = False
        self._track = ui.TRACKMOUSEEVENT(ctypes.sizeof(ui.TRACKMOUSEEVENT), ui.TME_LEAVE, None, 0)

    def set_value(self, value):
        self.value = value or ""
        self.recording = False
        self.invalidate()

    def label(self):
        return ui_display(self.value) if self.value else "未设置"

    def on_message(self, msg, wparam, lparam):
        if msg == w32.WM_LBUTTONDOWN:
            user32.SetFocus(self.hwnd)
            self.begin()
            return 0
        if msg == w32.WM_MOUSEMOVE:
            if not self.hover:
                self.hover = True
                self._track.hwndTrack = self.hwnd
                user32.TrackMouseEvent(ctypes.byref(self._track))
                self.invalidate()
            user32.SetCursor(user32.LoadCursorW(None, wt.LPCWSTR(w32.IDC_HAND)))
            return 0
        if msg == w32.WM_MOUSELEAVE:
            self.hover = False
            self.invalidate()
            return 0
        if msg == w32.WM_SETFOCUS or msg == w32.WM_KILLFOCUS:
            if msg == w32.WM_KILLFOCUS:
                self.recording = False
            self.invalidate()
            return 0
        if msg in (w32.WM_KEYDOWN, w32.WM_SYSKEYDOWN):
            return self.on_keydown(wparam, lparam)
        if msg in (w32.WM_KEYUP, w32.WM_SYSKEYUP):
            return self.on_keyup(wparam, lparam)
        if msg == w32.WM_CHAR:
            return 0
        if msg == w32.WM_GETDLGCODE:
            return 0x0001  # DLGC_WANTARROWS，方向键也交给我们
        return super().on_message(msg, wparam, lparam)

    def begin(self):
        self.recording = True
        self.got_key = False
        self.invalidate()

    def on_keydown(self, vk, lparam):
        if not self.recording:
            if vk in (0x20, 0x0D):
                self.begin()
                return 0
            return 0
        if lparam & (1 << 30):      # 自动重复
            return 0
        if vk == 0x1B:              # Esc 取消
            self.recording = False
            self.invalidate()
            return 0
        if vk in (0x10, 0x11, 0x12):    # 只按了修饰键
            return 0
        if vk in (0x08, 0x2E) and not self.modifiers():
            self.set_value("")
            self.commit()
            return 0
        name = self.vk_name(vk)
        if not name:
            return 0
        mods = self.modifiers()
        text = "+".join(mods + [name])
        try:
            import hotkeys
            value = hotkeys.canonical(text)
        except ValueError as error:
            self.recording = False
            self.invalidate()
            if self.on_change:
                self.on_change(self.action, self.slot, None, str(error))
            return 0
        self.got_key = True
        self.set_value(value)
        self.commit()
        return 0

    def on_keyup(self, vk, lparam):
        if self.recording and vk == 0x10 and not self.got_key and self.allow_shift_only:
            self.set_value("Shift")
            self.commit()
        return 0

    def modifiers(self):
        mods = []
        if user32.GetKeyState(0x11) & 0x8000:
            mods.append("Control")
        if user32.GetKeyState(0x12) & 0x8000:
            mods.append("Alt")
        if user32.GetKeyState(0x10) & 0x8000:
            mods.append("Shift")
        return mods

    def vk_name(self, vk):
        if 0x41 <= vk <= 0x5A:
            return chr(vk)
        if 0x30 <= vk <= 0x39:
            return chr(vk)
        if 0x70 <= vk <= 0x87:
            return "F%d" % (vk - 0x70 + 1)
        return self.VK_NAMES.get(vk)

    def commit(self):
        if self.on_change:
            self.on_change(self.action, self.slot, self.value, None)

    def paint(self, g, width, height):
        bg = 0xFFFFFF if self.recording else (0xE8E8E8 if self.hover else ui.FIELD_BG)
        border = ui.TEXT if self.recording else None
        ui.w32.round_fill(g, (0, 0, width, height), s(5), bg, border)
        text = "请按快捷键…" if self.recording else self.label()
        color = ui.MUTED if (not self.value and not self.recording) else ui.TEXT
        ui.w32.text(g, text, (s(10), 0, width - s(6), height), ui.FONTS.get(12), color,
                    w32.DT_LEFT | w32.DT_VCENTER | w32.DT_SINGLELINE | w32.DT_END_ELLIPSIS)


def ui_display(value):
    from hotkeys import display
    return display(value)


user32 = w32.user32


# ---------------------------------------------------------------- 页面基类
class Page(Panel):
    title = ""
    desc = ""

    def __init__(self, app):
        super().__init__(app, rect=(0, 0, 0, 0), bg=ui.BG_APP, scroll=True)
        self.app = app
        self.cfg = app.cfg
        self.content_height = 600
        self.build()

    def build(self):
        self.lbl_title = Label(self, self.title, (PAD, 20, 640, 34), px=23,
                               weight=w32.FW_SEMIBOLD, color=ui.TEXT_STRONG)
        self.lbl_desc = Label(self, self.desc, (PAD, 56, 780, 22), px=12, color=ui.MUTED)

    def layout(self, width):
        # width 已经是设计像素
        self.content_width = width - PAD * 2
        self.lbl_desc.move(PAD, 68, self.cw, 22)

    @property
    def cw(self):
        return max(320, int(self.content_width))

    def section(self, text, x, y, width=400):
        label = Label(self, text, (x, y, width, 22), px=14, weight=w32.FW_SEMIBOLD)
        return label

    def hint(self, text, x, y, width, height=20):
        return Label(self, text, (x, y, width, height), px=12, color=ui.MUTED)

    def load(self):
        pass

    def collect(self):
        return {}

    def on_show(self):
        pass


# ---------------------------------------------------------------- 01 常用设置
class CommonPage(Page):
    title = "常用设置"
    desc = "选择常用码表，并调整候选显示方式"

    def build(self):
        super().build()
        self.schema = "wubi86"
        self.sec_scheme = self.section("默认方案", PAD, 96)
        self.hint_scheme = self.hint("设为默认，之后仍可随时切换", PAD, 122, 360)
        self.cards = {}
        for sid, name, desc in SCHEMAS:
            self.cards[sid] = SchemaCard(self, sid, name, desc, self.pick_schema)

        self.sec_habit = self.section("输入习惯", PAD, 262)
        self.hint_habit = self.hint("简繁、全半角与标点风格", PAD, 288, 320)
        self.lbl_trad = Label(self, "简繁输出", (0, 0, 10, 20), px=12, weight=w32.FW_SEMIBOLD)
        self.combo_trad = Combo(self, [("简体", 0), ("繁体", 1)])
        self.lbl_shape = Label(self, "字符宽度", (0, 0, 10, 20), px=12, weight=w32.FW_SEMIBOLD)
        self.combo_shape = Combo(self, [("半角", 0), ("全角", 1)])
        self.lbl_punct = Label(self, "标点符号", (0, 0, 10, 20), px=12, weight=w32.FW_SEMIBOLD)
        self.combo_punct = Combo(self, [("中文标点", 0), ("英文标点", 1)])
        self.lbl_shift = Label(self, "Shift 键", (0, 0, 10, 20), px=12, weight=w32.FW_SEMIBOLD)
        self.chk_shift_commit = Check(self, "Shift 切换时上屏编码")
        self.chk_shift_direct = Check(self, "Shift + 字母直接输出")

        self.sec_cand = self.section("候选设置", 0, 262)
        self.hint_cand = self.hint("设置每页数量与候选窗排布", 0, 288, 320)
        self.lbl_page = Label(self, "每页数量", (0, 0, 10, 20), px=12, weight=w32.FW_SEMIBOLD)
        self.spin_page = Stepper(self, (0, 0, 10, 30), low=3, high=10, value=9, suffix=" 个")
        self.chk_h = Check(self, "横排显示")
        self.chk_i = Check(self, "编码跟随光标")
        self.chk_beep = Check(self, "四码无候选时提示音")
        self.chk_auto = Check(self, "四码唯一时自动上屏")

    def pick_schema(self, sid):
        self.schema = sid
        for key, card in self.cards.items():
            card.set_checked(key == sid)
        self.load_habits(sid)

    def load_habits(self, sid):
        switches = self.cfg.schema_switches(sid)
        self.combo_trad.set_by_data(int(bool(switches.get("traditional"))))
        self.combo_shape.set_by_data(int(bool(switches.get("full_shape"))))
        self.combo_punct.set_by_data(int(bool(switches.get("ascii_punct"))))
        self.chk_shift_commit.set_checked(bool(switches.get("shift_commit")))
        self.chk_shift_direct.set_checked(self.cfg.shift_letter_direct())

    def layout(self, width):
        super().layout(width)
        cw = self.cw
        self.lbl_title.move(PAD, 20, cw, 34)
        self.sec_scheme.move(PAD, 98, cw, 22)
        self.hint_scheme.move(PAD, 120, cw, 20)
        gap = 12
        card_w = int((cw - gap * 2) / 3)
        for i, (sid, _n, _d) in enumerate(SCHEMAS):
            self.cards[sid].move(PAD + i * (card_w + gap), 156, card_w, 112)

        left_w = int(cw * 0.56)
        right_x = PAD + left_w + 52
        right_w = cw - left_w - 52
        self.sec_habit.move(PAD, 296, left_w, 22)
        self.hint_habit.move(PAD, 324, left_w, 20)
        self.sec_cand.move(right_x, 296, right_w, 22)
        self.hint_cand.move(right_x, 324, right_w, 20)

        y = 350
        for label, control, ctrl_w in ((self.lbl_trad, self.combo_trad, 118),
                                       (self.lbl_shape, self.combo_shape, 118),
                                       (self.lbl_punct, self.combo_punct, 122),
                                       (self.lbl_shift, self.chk_shift_commit, 150)):
            label.move(PAD, y + 8, left_w - ctrl_w - 12, 20)
            control.move(PAD + left_w - ctrl_w, y, ctrl_w, 36)
            y += 46 if control is not self.chk_shift_commit else 28
        self.chk_shift_direct.move(PAD, y, left_w, 24)

        y = 354
        self.lbl_page.move(right_x, y + 8, right_w - 112, 20)
        self.spin_page.move(right_x + right_w - 104, y, 104, 38)
        y += 48
        for chk in (self.chk_h, self.chk_i, self.chk_beep, self.chk_auto):
            chk.move(right_x, y, right_w, 24)
            y += 29
        self.content_height = 542

    def load(self):
        self.schema = self.cfg.current_schema()
        for sid, card in self.cards.items():
            card.set_checked(sid == self.schema)
        self.load_habits(self.schema)
        self.spin_page.set_value(self.cfg.page_size())
        style = self.cfg.weasel_style()
        self.chk_h.set_checked(style["horizontal"])
        self.chk_i.set_checked(style["inline_preedit"])
        self.chk_beep.set_checked(self.cfg.no_candidate_beep())
        self.chk_auto.set_checked(self.cfg.auto_commit_unique())

    def collect(self):
        return {
            "schema": self.schema,
            "page_size": self.spin_page.value(),
            "traditional": self.combo_trad.data() or 0,
            "full_shape": self.combo_shape.data() or 0,
            "ascii_punct": self.combo_punct.data() or 0,
            "shift_commit": self.chk_shift_commit.is_checked(),
            "shift_direct": self.chk_shift_direct.is_checked(),
            "beep": self.chk_beep.is_checked(),
            "auto_commit": self.chk_auto.is_checked(),
            "horizontal": self.chk_h.is_checked(),
            "inline_preedit": self.chk_i.is_checked(),
        }


# ---------------------------------------------------------------- 02 外观
class AppearancePage(Page):
    title = "外观"
    desc = "候选窗配色、字体与圆角"

    def build(self):
        super().build()
        self.sec_theme = self.section("候选窗主题", PAD, 96)
        skins = list(self.cfg.SKINS.items())
        self.combo_scheme = Combo(self, [(skin["name"], key) for key, skin in skins],
                                  on_change=self.update_preview)
        self.hint_theme = self.hint("左边是预览；点「应用」后候选窗立即换成新配色，不用重启",
                                    PAD, 0, 300, 40)
        self.preview = CandidatePreview(self)
        self.sec_font = self.section("字体", PAD, 300)
        self.lbl_font = Label(self, "字体", (0, 0, 10, 20), px=12, weight=w32.FW_SEMIBOLD)
        self.combo_font = Combo(self, [(name, name) for name in
                                       ("Microsoft YaHei", "SimSun", "SimHei", "KaiTi", "Consolas")])
        self.lbl_size = Label(self, "字号", (0, 0, 10, 20), px=12, weight=w32.FW_SEMIBOLD)
        self.spin_font = Stepper(self, (0, 0, 10, 30), low=9, high=24, value=13, suffix=" pt")
        self.lbl_round = Label(self, "圆角", (0, 0, 10, 20), px=12, weight=w32.FW_SEMIBOLD)
        self.spin_round = Stepper(self, (0, 0, 10, 30), low=0, high=16, value=6, suffix=" px",
                                  on_change=lambda _v: self.update_preview(None))

    def layout(self, width):
        super().layout(width)
        cw = self.cw
        left_w = int(cw * 0.46)
        self.combo_scheme.move(PAD, 124, min(240, left_w), 30)
        self.hint_theme.move(PAD, 164, left_w, 40)
        self.preview.move(PAD + left_w + 28, 120, cw - left_w - 28, 112)

        self.sec_font.move(PAD, 300, cw, 22)
        y = 336
        self.lbl_font.move(PAD, y + 7, 60, 20)
        self.combo_font.move(PAD + 68, y, 220, 30)
        self.lbl_size.move(PAD + 320, y + 7, 40, 20)
        self.spin_font.move(PAD + 368, y, 100, 30)
        y += 44
        self.lbl_round.move(PAD, y + 7, 60, 20)
        self.spin_round.move(PAD + 68, y, 100, 30)
        self.content_height = y + 80

    def update_preview(self, _data):
        key = self.combo_scheme.data() or "qingshi_blue"
        skin = self.cfg.SKINS.get(key) or self.cfg.SKINS["qingshi_blue"]

        def rgb(value):
            return int(str(value).replace("0x", ""), 16) & 0xFFFFFF

        self.preview.set_skin(rgb(skin["back_color"]), rgb(skin["candidate_text_color"]),
                              rgb(skin["border_color"]), rgb(skin["hilited_candidate_back_color"]),
                              rgb(skin["hilited_candidate_text_color"]),
                              rgb(skin["comment_text_color"]), self.spin_round.value())

    def load(self):
        style = self.cfg.weasel_style()
        self.combo_scheme.set_by_data(style["color_scheme"])
        if style["font_face"]:
            self.combo_font.set_by_text(style["font_face"])
        self.spin_font.set_value(style["font_point"])
        self.spin_round.set_value(style["round_corner"])
        self.update_preview(None)

    def collect(self):
        common = None
        for page in self.app.pages:
            if isinstance(page, CommonPage):
                common = page.collect()
        return {"style": {
            "color_scheme": self.combo_scheme.data(),
            "font_face": self.combo_font.text(),
            "font_point": self.spin_font.value(),
            "horizontal": bool(common and common["horizontal"]),
            "inline_preedit": bool(common and common["inline_preedit"]),
            "round_corner": self.spin_round.value(),
        }}


# ---------------------------------------------------------------- 03 词库
class DictPage(Page):
    title = "词库"
    desc = "查看码表规模，导入自定义码表"

    def build(self):
        super().build()
        self.sec_stats = self.section("词库规模", PAD, 96)
        self.metrics = {}
        for sid, name, _desc in SCHEMAS:
            self.metrics[sid] = MetricCard(self, name)
        self.sec_action = self.section("管理自定义码表", PAD, 262)
        self.hint_action = Label(
            self, "导入 TXT 码表，每行一条「编码 词条」。导入前会自动备份当前词库。",
            (PAD, 288, 700, 20), px=12, color=ui.MUTED)
        self.btn_import = Button(self, "导入码表…", (0, 0, 110, 36), on_click=self.import_dict)
        self.btn_userdir = Button(self, "打开用户目录", (0, 0, 130, 36), on_click=self.open_userdir)
        self.btn_deploy = Button(self, "重新部署", (0, 0, 110, 36), kind="primary",
                                 on_click=self.redeploy)
        self._stats_dirty = True

    def layout(self, width):
        super().layout(width)
        cw = self.cw
        gap = 12
        card_w = int((cw - gap * 2) / 3)
        for i, (sid, _n, _d) in enumerate(SCHEMAS):
            self.metrics[sid].move(PAD + i * (card_w + gap), 126, card_w, 108)
        self.sec_action.move(PAD, 262, cw, 22)
        self.hint_action.move(PAD, 288, cw, 20)
        self.btn_import.move(PAD, 322, 110, 36)
        self.btn_userdir.move(PAD + 120, 322, 130, 36)
        self.btn_deploy.move(PAD + 260, 322, 110, 36)
        self.content_height = 420

    def on_show(self):
        if self._stats_dirty:
            self.refresh_stats()

    def refresh_stats(self):
        self._stats_dirty = False
        try:
            stats = self.cfg.stats()
        except Exception:
            stats = {}
        for sid, _name, _desc in SCHEMAS:
            value = stats.get(sid)
            self.metrics[sid].set_value(f"{value:,}" if isinstance(value, int) else "—")

    def import_dict(self):
        path = ui.open_file(self, "选择码表", "文本文件 (*.txt)\0*.txt\0所有文件 (*.*)\0*.*\0\0")
        if not path:
            return
        sid = self.app.pages[0].schema if hasattr(self.app.pages[0], "schema") else self.cfg.current_schema()
        dst = self.cfg.path(f"{sid}.dict.yaml")
        if os.path.isfile(dst):
            shutil.copy2(dst, dst + ".bak")
        count = 0
        out = ['---', f"name: {sid}", 'version: "1.0"', 'sort: original', 'columns:',
               '  - text', '  - code', '  - weight', '...', '']
        with open(path, encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                parts = line.strip().split()
                if len(parts) < 2:
                    continue
                code, word = parts[0].lower(), parts[1]
                if not (1 <= len(code) <= 4) or not all("a" <= ch <= "y" for ch in code):
                    continue
                out.append(f"{word}\t{code}\t0")
                count += 1
        with open(dst, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(out) + "\n")
        ui.message(self, f"已导入 {count:,} 条到「{sid}」，正在重新部署…", "导入完成")
        ok = run_with_busy(self, "正在重新部署", "正在把新词条编译进码表…",
                           "码表越大这一步越久，期间输入法暂时不可用。",
                           lambda: self.cfg.deploy(wait=True) and self.cfg.restart_server())
        ui.message(self, "已重新部署并重启输入法服务" if ok else "部署未完成，请稍后重试",
                   "重新部署", "info" if ok else "warn")
        self._stats_dirty = True
        self.refresh_stats()

    def open_userdir(self):
        os.startfile(self.cfg.dir)

    def redeploy(self):
        ok = run_with_busy(self, "正在重新部署", "正在重新编译码表与词库…",
                           "这一步通常需要几秒到十几秒，期间输入法暂时不可用。",
                           lambda: self.cfg.deploy(wait=True) and self.cfg.restart_server())
        ui.message(self, "已重新部署并重启输入法服务" if ok else "未找到输入法配置工具或部署失败",
                   "重新部署", "info" if ok else "warn")


# ---------------------------------------------------------------- 04 自定义词条
class PhrasePage(Page):
    title = "自定义词条"
    desc = "自定义词条会排在候选最前面；列表顺序就是候选顺序"

    def build(self):
        super().build()
        self.phrases = []
        self.table = ListView(self, [("词条", 520), ("编码", 130)],
                              on_activate=lambda _i: self.edit())
        self.btn_add = Button(self, "添加…", (0, 0, 80, 34), on_click=self.add)
        self.btn_edit = Button(self, "编辑…", (0, 0, 80, 34), on_click=self.edit)
        self.btn_del = Button(self, "删除", (0, 0, 80, 34), on_click=self.delete)
        self.btn_up = Button(self, "上移", (0, 0, 80, 34), on_click=lambda: self.move_item(-1))
        self.btn_down = Button(self, "下移", (0, 0, 80, 34), on_click=lambda: self.move_item(1))
        self.btn_pin = Button(self, "固顶", (0, 0, 80, 34), kind="primary", on_click=self.pin)
        self.hint_tip = Label(
            self, "提示：输入时也可在候选窗上点右键，直接把当前词固顶或加入自定义词条。"
                  "改完点「应用」，新词条会立刻进入候选。",
            (PAD, 0, 700, 40), px=12, color=ui.MUTED, multiline=True)

    def layout(self, width):
        super().layout(width)
        cw = self.cw
        table_h = 320
        self.table.move(PAD, 96, cw, table_h)
        self.table.resize_columns([cw - 140, 130])
        y = 96 + table_h + 14
        x = PAD
        for button in (self.btn_add, self.btn_edit, self.btn_del, self.btn_up, self.btn_down):
            button.move(x, y, 80, 34)
            x += 88
        self.btn_pin.move(PAD + cw - 80, y, 80, 34)
        self.hint_tip.move(PAD, y + 48, cw, 40)
        self.content_height = y + 48 + 44

    def load(self):
        self.phrases = self.cfg.read_phrases()
        self.refresh()

    def refresh(self):
        self.table.set_rows([(word, code) for word, code in self.phrases])

    def collect(self):
        return {"phrases": list(self.phrases)}

    def _ask(self, title, prompt, default=""):
        return AskDialog.ask(self, title, prompt, default)

    def add(self):
        word = self._ask("添加词条", "词条内容：")
        if not word or not word.strip():
            return
        word = word.strip()
        code = self._ask("添加词条", f"「{word}」的五笔编码（1-4 位字母）：")
        if code is None:
            return
        code = code.strip().lower()
        if not (1 <= len(code) <= 4 and all("a" <= ch <= "y" for ch in code)):
            ui.message(self, "五笔编码只能是 a-y 之间的 1-4 位字母。", "编码无效", "warn")
            return
        self.phrases.append((word, code))
        self.refresh()
        self.cfg.write_phrases(self.phrases)
        self.table.select(len(self.phrases) - 1)

    def edit(self):
        row = self.table.selected()
        if row < 0 or row >= len(self.phrases):
            return
        old_word, old_code = self.phrases[row]
        word = self._ask("编辑词条", "词条内容：", old_word)
        if word is None or not word.strip():
            return
        word = word.strip()
        code = self._ask("编辑词条", f"「{word}」的五笔编码（1-4 位字母）：", old_code)
        if code is None:
            return
        code = code.strip().lower()
        if not (1 <= len(code) <= 4 and all("a" <= ch <= "y" for ch in code)):
            ui.message(self, "五笔编码只能是 a-y 之间的 1-4 位字母。", "编码无效", "warn")
            return
        self.phrases[row] = (word, code)
        self.refresh()
        self.table.select(row)
        self.cfg.write_phrases(self.phrases)

    def delete(self):
        row = self.table.selected()
        if row < 0 or row >= len(self.phrases):
            return
        del self.phrases[row]
        self.refresh()
        if self.phrases:
            self.table.select(min(row, len(self.phrases) - 1))
        self.cfg.write_phrases(self.phrases)

    def move_item(self, delta):
        row = self.table.selected()
        target = row + delta
        if row < 0 or not (0 <= target < len(self.phrases)):
            return
        self.phrases[row], self.phrases[target] = self.phrases[target], self.phrases[row]
        self.refresh()
        self.table.select(target)
        self.cfg.write_phrases(self.phrases)

    def pin(self):
        row = self.table.selected()
        if row <= 0 or row >= len(self.phrases):
            return
        item = self.phrases.pop(row)
        self.phrases.insert(0, item)
        self.refresh()
        self.table.select(0)
        self.cfg.write_phrases(self.phrases)


# ---------------------------------------------------------------- 05 自定义词序
class ShadowPage(Page):
    title = "自定义词序"
    desc = ("在候选框上右键「置顶」、或按 Ctrl+数字 做的调整都会记录在这里。"
            "删掉某条规则，该编码就回到词库原本的顺序。")

    def build(self):
        super().build()
        self.lbl_desc.multiline = True
        self.rules = {}
        self.lbl_schema = Label(self, "方案", (0, 0, 10, 20), px=12, weight=w32.FW_SEMIBOLD)
        self.combo_schema = Combo(self, [(name, sid) for sid, name, _d in SCHEMAS],
                                  on_change=lambda _d: self.load_rules())
        self.table = ListView(self, [("编码", 130), ("词条", 420), ("位次", 70)])
        self.btn_del = Button(self, "删除选中", (0, 0, 96, 34), on_click=self.delete_one)
        self.btn_code = Button(self, "删除该编码", (0, 0, 110, 34), on_click=self.delete_code)
        self.btn_refresh = Button(self, "刷新", (0, 0, 80, 34), on_click=self.load_rules)
        self.btn_reset = Button(self, "恢复默认词序", (0, 0, 124, 34), kind="primary",
                                on_click=self.reset)
        self.lbl_empty = Label(self, "当前方案还没有任何调序规则。", (0, 0, 600, 20),
                               px=12, color=ui.MUTED)
        self.hint_tip = Label(
            self, "提示：调序规则按「编码」独立生效 —— 改 wqiy 不影响其它编码。"
                  "规则存放在用户目录的 shadow_<方案>.yaml，删掉整个文件等于全部恢复默认。"
                  "这里改完立刻生效，不需要重新部署。",
            (PAD, 0, 700, 60), px=12, color=ui.MUTED, multiline=True)

    def layout(self, width):
        super().layout(width)
        cw = self.cw
        self.lbl_desc.move(PAD, 56, cw, 40)
        y = 104
        self.lbl_schema.move(PAD, y + 7, 40, 20)
        self.combo_schema.move(PAD + 44, y, 190, 30)
        table_y = y + 46
        table_h = 300
        self.table.move(PAD, table_y, cw, table_h)
        self.table.resize_columns([130, cw - 210, 70])
        by = table_y + table_h + 14
        x = PAD
        for button, w in ((self.btn_del, 96), (self.btn_code, 110), (self.btn_refresh, 80)):
            button.move(x, by, w, 34)
            x += w + 8
        self.btn_reset.move(PAD + cw - 124, by, 124, 34)
        self.lbl_empty.move(PAD, by + 44, cw, 20)
        self.hint_tip.move(PAD, by + 70, cw, 60)
        self.content_height = by + 70 + 64

    def load(self):
        index = self.combo_schema.data()
        if index is None:
            self.combo_schema.set_by_data(self.cfg.current_schema())
        self.load_rules()

    def schema(self):
        return self.combo_schema.data() or self.cfg.current_schema()

    def load_rules(self):
        self.rules = self.cfg.read_shadow(self.schema())
        rows = []
        for code, words in self.rules.items():
            for i, word in enumerate(words):
                rows.append((code, word, i + 1))
        self.table.set_rows(rows)
        self.lbl_empty.show(not rows)

    def _save(self):
        if not self.cfg.write_shadow(self.schema(), self.rules):
            ui.message(self, "调序文件写入失败，请检查用户数据目录是否可写。", "保存失败", "warn")
            return
        self.cfg.reload()
        self.load_rules()

    def delete_one(self):
        row = self.table.selected()
        if row < 0 or row >= len(self.table.rows):
            return
        code, word, _pos = self.table.rows[row]
        words = self.rules.get(code, [])
        if word in words:
            words.remove(word)
        if not words:
            self.rules.pop(code, None)
        self._save()

    def delete_code(self):
        row = self.table.selected()
        if row < 0 or row >= len(self.table.rows):
            return
        self.rules.pop(self.table.rows[row][0], None)
        self._save()

    def reset(self):
        if not self.rules:
            ui.message(self, "当前方案没有任何调序规则。", "已经是默认词序")
            return
        if not ui.confirm(self, f"确定清空「{self.combo_schema.text()}」的全部调序规则吗？\n"
                                "清空后所有编码都回到词库原本的顺序。", "恢复默认词序"):
            return
        self.rules = {}
        self._save()


# ---------------------------------------------------------------- 06 快捷键
class HotkeyPage(Page):
    title = "快捷键"
    desc = "三套方案共用。点击按键框后录入；点击「应用」保存。Esc 取消录入。"

    def build(self):
        super().build()
        import hotkeys
        self.module = hotkeys
        self.values_map = {}
        self.snapshot = None
        self.shift_snapshot = False
        self.fields = {}
        self.clears = {}
        self.groups = []
        self.secs = {}
        y_groups = {}
        for action, label, defaults, group in hotkeys.ACTIONS:
            if group not in y_groups:
                y_groups[group] = True
                self.groups.append(group)
                self.secs[group] = self.section(group, PAD, 0)
            for slot in range(2):
                field = HotkeyField(self, action, slot,
                                    allow_shift_only=(action == "ascii_mode"),
                                    on_change=self.on_field)
                self.fields[action, slot] = field
                self.clears[action, slot] = Button(
                    self, "清除", (0, 0, 44, 26), kind="ghost",
                    on_click=lambda a=action, k=slot: self.clear_field(a, k))
                self.values_map[action, slot] = ""
        self.labels = {}
        for action, label, defaults, group in hotkeys.ACTIONS:
            self.labels[action] = Label(self, label, (0, 0, 10, 20), px=12)
        self.msg = Label(self, "", (PAD, 0, 700, 36), px=12, color=0xA52626, multiline=True)
        self.hint_tip = Label(
            self, "数字键选词、空格上屏、Esc 清空与 PgUp / PgDn 保留为基础输入键。"
                  "Win＋空格切换输入法由 Windows 管理。Ctrl＋数字用于候选置顶。"
                  "切换方案不占用快捷键（F4 容易误触），请到「方案」页切换。",
            (PAD, 0, 700, 60), px=12, color=ui.MUTED, multiline=True)

    def layout(self, width):
        super().layout(width)
        cw = self.cw
        self.hint_tip.move(PAD, 88, cw, 36)
        y = 138
        field_w = 150
        clear_w = 42
        for group in self.groups:
            self.secs[group].move(PAD, y, cw, 22)
            y += 30
            for action, label, defaults, category in self.module.ACTIONS:
                if category != group:
                    continue
                self.labels[action].move(PAD, y + 8, 120, 20)
                x = PAD + 130
                for slot in range(2):
                    self.fields[action, slot].move(x, y, field_w, 34)
                    self.clears[action, slot].move(x + field_w + 4, y + 4, 44, 26)
                    x += field_w + 4 + clear_w + 16
                y += 44
            y += 10
        self.msg.move(PAD, y, cw, 36)
        self.content_height = y + 56

    def load(self):
        import hotkeys
        try:
            values = hotkeys.load(self.cfg.dir, self.cfg.current_schema())
            self.snapshot = values
        except ValueError as error:
            values = hotkeys.DEFAULTS
            self.snapshot = None
            self.show_error(str(error))
        for action, keys in values.items():
            for slot, value in enumerate(keys):
                field = self.fields.get((action, slot))
                if field:
                    field.set_value(value)
        self.shift_snapshot = self.app.pages[0].chk_shift_commit.is_checked() and \
            "Shift" in values.get("ascii_mode", [])

    def values(self):
        return {action: [self.fields[action, slot].value for slot in range(2)]
                for action in self.module.DEFAULTS}

    def clear_field(self, action, slot):
        self.fields[action, slot].set_value("")
        self.hide_error()

    def on_field(self, action, slot, value, error):
        if error:
            self.show_error(error)
        else:
            self.hide_error()

    def show_error(self, text):
        self.msg.set_text(text)
        self.msg.show()

    def hide_error(self):
        self.msg.set_text("")
        self.msg.show(False)

    def collect(self):
        return {"hotkeys": self}


# ---------------------------------------------------------------- 07 备份与更新
class BackupPage(Page):
    title = "备份与更新"
    desc = "导出或导入整套配置，检查是否有新版本"

    def build(self):
        super().build()
        from config_bundle import snapshot, restore
        from update_checker import UpdateChecker
        self.snapshot_fn = snapshot
        self.restore_fn = restore
        self.checker = UpdateChecker(self.cfg.dir)

        self.sec_backup = self.section("配置备份", PAD, 96)
        self.hint_backup = Label(
            self, "导出的文件包含方案、外观、词条、词序与快捷键；导入会覆盖当前配置。",
            (PAD, 122, 700, 20), px=12, color=ui.MUTED)
        self.btn_export = Button(self, "导出配置…", (0, 0, 110, 36), on_click=self.export)
        self.btn_import = Button(self, "导入配置…", (0, 0, 110, 36), on_click=self.import_config)

        self.sec_update = self.section("版本更新", PAD, 236)
        self.hint_version = Label(self, f"当前版本 v{APP_VER}", (PAD, 262, 400, 20),
                                  px=12, color=ui.MUTED)
        self.btn_check = Button(self, "检查新版本", (0, 0, 120, 36), kind="primary",
                                on_click=lambda: self.check(True))
        self.chk_auto = Check(self, "启动时自动检查更新", checked=True,
                              on_change=lambda v: self.checker.set_automatic(v))
        self.lbl_result = Label(self, "", (PAD, 0, 700, 24), px=12, color=ui.MUTED)

    def layout(self, width):
        super().layout(width)
        cw = self.cw
        self.btn_export.move(PAD, 154, 110, 36)
        self.btn_import.move(PAD + 120, 154, 110, 36)
        self.btn_check.move(PAD, 300, 120, 36)
        self.chk_auto.move(PAD + 140, 306, 260, 24)
        self.lbl_result.move(PAD, 352, cw, 24)
        self.content_height = 420

    def load(self):
        try:
            self.chk_auto.set_checked(self.checker.settings().get("automatic", True) is not False)
        except Exception:
            pass

    def export(self):
        name = "青石五笔配置-" + datetime.datetime.now().strftime("%Y%m%d") + ".qingshi.zip"
        path = ui.save_file(self, "导出青石配置", name,
                            "青石配置备份 (*.qingshi.zip)\0*.qingshi.zip\0ZIP 文件 (*.zip)\0*.zip\0\0")
        if not path:
            return
        from fixed_order import atomic_write
        try:
            data = self.snapshot_fn(self.cfg.dir, self.cfg.shift_letter_direct())
            atomic_write(path, data)
        except Exception as error:      # noqa: BLE001
            ui.message(self, str(error), "导出失败", "warn")
            return
        self.lbl_result.set_text("已导出：" + os.path.basename(path))
        ui.message(self, "配置已导出。", "导出完成")

    def import_config(self):
        path = ui.open_file(self, "导入青石配置",
                            "青石配置备份 (*.qingshi.zip)\0*.qingshi.zip\0ZIP 文件 (*.zip)\0*.zip\0\0")
        if not path:
            return
        if not ui.confirm(self, "导入会覆盖当前的方案、外观、词条与快捷键。\n确定继续吗？", "恢复配置"):
            return
        try:
            with open(path, "rb") as handle:
                data = handle.read()
            self.restore_fn(self.cfg.dir, data, self.cfg.shift_letter_direct())
        except Exception as error:      # noqa: BLE001
            ui.message(self, str(error), "导入失败", "warn")
            return
        self.lbl_result.set_text("已导入：" + os.path.basename(path))
        ui.message(self, "配置已恢复，正在重启输入法服务…", "导入完成")
        run_with_busy(self, "正在应用配置", "正在重启输入法服务…", "重启后新配置才会生效。",
                      lambda: self.cfg.restart_server())
        self.app.load()
        self.app.footer.set_status("配置已导入并生效。", "ok")

    def check(self, manual):
        def task():
            return self.checker.check(APP_VER, manual=manual)
        try:
            result = run_with_busy(self, "正在检查更新", "正在读取官方发布信息…",
                                   "只检查版本号，不会自动下载或运行任何文件。", task)
        except Exception as error:      # noqa: BLE001
            self.lbl_result.set_text("暂时无法检查更新")
            if manual:
                ui.message(self, f"暂时无法检查更新：{error}", "检查更新", "warn")
            return
        if not result or result.get("skipped"):
            return
        if result.get("newer"):
            self.lbl_result.set_text(f"发现新版本 v{result['version']}")
            if manual:
                ui.message(self, f"发现新版本 v{result['version']}。\n"
                                 f"请到官网下载：https://qingshi.funnyai.wiki/", "发现更新")
        else:
            self.lbl_result.set_text("已是最新版本")
            if manual:
                ui.message(self, "当前已经是最新版本。", "检查更新")


# ---------------------------------------------------------------- 08 关于
class AboutPage(Page):
    title = "关于"
    desc = ""

    def build(self):
        super().build()
        self.lbl_desc.show(False)
        self.lbl_name = Label(self, "青石五笔输入法", (PAD, 76, 400, 40), px=26,
                              weight=w32.FW_SEMIBOLD, color=ui.TEXT_STRONG)
        self.lbl_version = Label(self, f"v{APP_VER} · Windows 10 / 11 x64", (PAD, 120, 500, 22),
                                 px=12, color=ui.MUTED)
        self.lbl_body = Label(
            self,
            "基于 Rime 输入法引擎与 Weasel（小狼毫）二次开发。\n"
            "码表来自极点五笔及公开的五笔 86、98、新世纪版本。\n\n"
            "本项目采用 GPL-3.0 许可证发布。\n"
            "第三方组件的许可信息见安装目录中的 licenses 文件夹。",
            (PAD, 164, 640, 132), px=13, color=ui.TEXT, multiline=True)
        self.btn_dir = Button(self, "打开用户目录", (0, 0, 130, 36), on_click=self.open_dir)
        self.btn_site = Button(self, "访问官网", (0, 0, 110, 36), on_click=self.open_site)
        self.btn_licenses = Button(self, "查看许可", (0, 0, 110, 36), on_click=self.open_licenses)
        self.lbl_contact = Label(self, "https://qingshi.funnyai.wiki/", (PAD, 0, 400, 22),
                                 px=12, color=ui.MUTED)

    def layout(self, width):
        super().layout(width)
        self.lbl_body.move(PAD, 164, self.cw, 132)
        self.btn_dir.move(PAD, 320, 130, 36)
        self.btn_site.move(PAD + 140, 320, 110, 36)
        self.btn_licenses.move(PAD + 260, 320, 110, 36)
        self.lbl_contact.move(PAD, 372, self.cw, 22)
        self.content_height = 414

    def open_dir(self):
        os.startfile(self.cfg.dir)

    def open_site(self):
        w32.shell32.ShellExecuteW(None, "open", "https://qingshi.funnyai.wiki/", None, None, 1)

    def open_licenses(self):
        from rime_config import WEASEL_CANDIDATES
        for directory in WEASEL_CANDIDATES:
            path = os.path.join(directory, "licenses")
            if os.path.isdir(path):
                os.startfile(path)
                return
        ui.message(self, "未找到许可文件目录。", "查看许可", "warn")


class AskDialog(Panel):
    """单行文本输入对话框。"""

    cls = "QSAsk"
    popup = True

    @classmethod
    def ask(cls, parent, title, prompt, default=""):
        ui.register_class("QSAsk")
        dlg = cls.__new__(cls)
        dlg.children = []
        dlg.bg = ui.BG_PANEL
        dlg.scroll = False
        dlg.offset = 0
        dlg.content_h = 0
        dlg.combo_item_h = 26
        dlg._brush = None
        dlg.title = title
        dlg.prompt = prompt
        dlg.result = None
        ui.Widget.__init__(dlg, parent, "", (0, 0, 420, 168),
                           style=w32.WS_POPUP | w32.WS_BORDER | w32.WS_CLIPCHILDREN)
        dlg.label = Label(dlg, prompt, (20, 18, 380, 22), px=13)
        dlg.edit = ui.Edit(dlg, default, (20, 48, 380, 32), px=13)
        dlg.ok = Button(dlg, "确定", (0, 0, 88, 32), kind="primary",
                        on_click=lambda: dlg.finish(True))
        dlg.cancel = Button(dlg, "取消", (0, 0, 88, 32), on_click=lambda: dlg.finish(False))
        dlg.ok.move(420 - 20 - 88, 116, 88, 32)
        dlg.cancel.move(420 - 20 - 88 - 8 - 88, 116, 88, 32)
        dlg.show_modal()
        return dlg.result

    def show_modal(self):
        owner = self.parent.hwnd
        rect = w32.RECT()
        user32.GetWindowRect(owner, ctypes.byref(rect))
        w, h = s(420), s(168)
        x = rect.left + (rect.right - rect.left - w) // 2
        y = rect.top + (rect.bottom - rect.top - h) // 2
        user32.SetWindowPos(self.hwnd, w32.HWND_TOPMOST, x, y, w, h, w32.SWP_SHOWWINDOW)
        user32.EnableWindow(owner, False)
        user32.SetFocus(self.edit.hwnd)
        msg = w32.MSG()
        while user32.IsWindow(self.hwnd):
            if not user32.GetMessageW(ctypes.byref(msg), None, 0, 0):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def finish(self, ok):
        self.result = self.edit.get_text() if ok else None
        user32.EnableWindow(self.parent.hwnd, True)
        user32.DestroyWindow(self.hwnd)

    def paint(self, g, width, height):
        ui.w32.line(g, 0, 96, width, 96, ui.BORDER)


PAGES = [CommonPage, AppearancePage, DictPage, PhrasePage, ShadowPage,
         HotkeyPage, BackupPage, AboutPage]
