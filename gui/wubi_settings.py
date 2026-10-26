# -*- coding: utf-8 -*-
"""
五笔输入法 · 设置中心
基于 Weasel(librime) 二次开发的图形配置界面
"""
import os
import sys
import shutil
import subprocess
import datetime

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QPixmap, QColor, QPainter, QPalette
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QRadioButton, QButtonGroup, QSpinBox, QCheckBox,
    QComboBox, QLineEdit, QListWidget, QListWidgetItem, QStackedWidget,
    QGroupBox, QFrame, QMessageBox, QFileDialog, QScrollArea, QSlider,
    QSizePolicy, QSpacerItem, QTextEdit, QDialog, QDialogButtonBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QInputDialog, QAbstractItemView
)

try:
    import yaml
except ImportError:
    yaml = None

APP_NAME = "青石五笔输入法"
APP_VER = "1.0.6"
from app_paths import user_directory, runtime_directories
RIME_DIR = user_directory()
WEASEL_CANDIDATES = runtime_directories()

SCHEMAS = [
    ("wubi86", "五笔 86", "王码86版原表 · 极点官方词库"),
    ("wubi98", "五笔 98", "98版码元体系"),
    ("wubi06", "新世纪五笔", "2008 新世纪版"),
]

# ---------------- 样式 ----------------
from ui_theme import QSS, apply_theme
from navigation import Navigation


# ---------------- 配置读写 ----------------
class RimeConfig:
    def __init__(self, rime_dir=RIME_DIR):
        self.dir = rime_dir
        os.makedirs(self.dir, exist_ok=True)

    def path(self, name):
        return os.path.join(self.dir, name)

    def read_yaml(self, name):
        p = self.path(name)
        if not os.path.isfile(p) or yaml is None:
            return {}
        try:
            with open(p, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def exists(self, name):
        return os.path.isfile(self.path(name))

    # 读当前状态
    def current_schema(self):
        d = self.read_yaml("default.custom.yaml")
        lst = (d.get("patch") or {}).get("schema_list") or []
        if lst and isinstance(lst[0], dict):
            return lst[0].get("schema", "wubi86")
        return "wubi86"

    def page_size(self):
        d = self.read_yaml("default.custom.yaml")
        m = (d.get("patch") or {}).get("menu") or {}
        return int(m.get("page_size", 9) or 9)

    def weasel_style(self):
        d = self.read_yaml("weasel.custom.yaml")
        p = d.get("patch") or {}
        # 新版写的是嵌套结构（style: / layout:），旧版是扁平 key，两种都要认
        style = p.get("style") or {}
        layout = style.get("layout") or {}

        def pick(name, flat, default, nested=None):
            value = nested if nested is not None else style.get(name)
            if value is None:
                value = p.get(flat)
            return default if value is None else value

        return {
            "color_scheme": pick("color_scheme", "style/color_scheme", "qingshi_blue"),
            "font_face": pick("font_face", "style/font_face", "Microsoft YaHei"),
            "font_point": int(pick("font_point", "style/font_point", 13) or 13),
            "horizontal": bool(pick("horizontal", "style/horizontal", True)),
            "inline_preedit": bool(pick("inline_preedit", "style/inline_preedit", True)),
            "round_corner": int(
                pick("round_corner", "style/layout/round_corner", 6,
                     layout.get("round_corner")) or 6),
        }

    # 输入习惯：对应 schema switches 的下标（顺序固定，见 pkg/*.schema.yaml）
    SWITCH_INDEX = {"full_shape": 1, "traditional": 3, "ascii_punct": 4}
    # Shift 键行为
    SHIFT_STYLES = [
        ("上屏编码", "commit_code"),
        ("切换中英文", "inline_ascii"),
        ("无操作", "noop"),
    ]

    def schema_switches(self, sid):
        """读取某方案的输入习惯默认值"""
        d = self.read_yaml(f"{sid}.custom.yaml")
        p = d.get("patch") or {}
        out = {}
        for key, idx in self.SWITCH_INDEX.items():
            try:
                out[key] = int(p.get(f"switches/@{idx}/reset", 0) or 0)
            except (TypeError, ValueError):
                out[key] = 0
        out["shift_style"] = p.get("ascii_composer/switch_key/Shift_L", "commit_code")
        if out["shift_style"] not in [v for _, v in self.SHIFT_STYLES]:
            out["shift_style"] = "commit_code"
        # 拆成两个独立开关：上屏编码 / 切换中英文
        out["shift_commit"] = out["shift_style"] == "commit_code"
        out["shift_toggle"] = out["shift_style"] in ("commit_code", "inline_ascii")
        return out

    def write_schema_switches(self, sid, values):
        """写入某方案的输入习惯默认值"""
        lines = [
            f"# 青石五笔 · {sid} 输入习惯",
            "# 由设置中心生成；输入时仍可用快捷键临时切换",
            "patch:",
        ]
        for key, idx in self.SWITCH_INDEX.items():
            lines.append(f"  switches/@{idx}/reset: {1 if values.get(key) else 0}")
        commit = bool(values.get("shift_commit", True))
        toggle = bool(values.get("shift_toggle", True))
        # Rime 的 commit_code 本身就会连带切换中英模式（内核行为），
        # 所以「只上屏不切换」没有对应取值，勾了上屏就按 commit_code 处理。
        if commit:
            style = "commit_code"
        elif toggle:
            style = "inline_ascii"
        else:
            style = "noop"
        lines.append(f"  ascii_composer/switch_key/Shift_L: {style}")
        lines.append(f"  ascii_composer/switch_key/Shift_R: {style}")
        with open(self.path(f"{sid}.custom.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")

    # ---- Shift+字母直出（全局开关，存在注册表） ----
    REG_PATH = r"Software\Rime\Weasel"
    REG_NAME = "QingshiShiftLetterDirect"

    def shift_letter_direct(self):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH) as k:
                value, _ = winreg.QueryValueEx(k, self.REG_NAME)
                return bool(value)
        except Exception:
            return True

    def set_shift_letter_direct(self, enabled):
        try:
            import winreg
            with winreg.CreateKeyEx(
                    winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_WRITE) as k:
                winreg.SetValueEx(k, self.REG_NAME, 0, winreg.REG_DWORD,
                                  1 if enabled else 0)
            return True
        except Exception:
            return False

    # 写配置
    def write_default(self, schema_id, page_size):
        lines = ["# 五笔输入法 · 方案与候选设置", "patch:", "  schema_list:"]
        order = [schema_id] + [sid for sid, _, _ in SCHEMAS if sid != schema_id]
        for sid in order:
            lines.append(f"    - schema: {sid}")
        lines.append("  menu:")
        lines.append(f"    page_size: {page_size}")
        with open(self.path("default.custom.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")

    # 皮肤预设：字段与 Weasel 的 preset_color_schemes 一一对应
    SKINS = {
        "qingshi_blue": {
            "name": "青石蓝白",
            "back_color": "0xFFFFFF",
            "border_color": "0xDCE5F1",
            "text_color": "0x263750",
            "hilited_text_color": "0x263750",
            "hilited_back_color": "0xFFFFFF",
            "hilited_candidate_text_color": "0xFFFFFF",
            "hilited_candidate_back_color": "0x2868D7",
            "candidate_text_color": "0x263750",
            "candidate_back_color": "0xFFFFFF",
            "comment_text_color": "0x718198",
            "label_color": "0x718198",
            "hilited_candidate_label_color": "0xFFFFFF",
        },
        "qingshi_ink": {
            "name": "水墨灰",
            "back_color": "0xF7F7F5",
            "border_color": "0xDDDDD8",
            "text_color": "0x3A3A38",
            "hilited_text_color": "0x3A3A38",
            "hilited_back_color": "0xF7F7F5",
            "hilited_candidate_text_color": "0xFFFFFF",
            "hilited_candidate_back_color": "0x4A4A46",
            "candidate_text_color": "0x3A3A38",
            "candidate_back_color": "0xF7F7F5",
            "comment_text_color": "0x8A8A84",
            "label_color": "0x8A8A84",
            "hilited_candidate_label_color": "0xFFFFFF",
        },
        "qingshi_green": {
            "name": "护眼豆绿",
            "back_color": "0xCCE8CF",
            "border_color": "0xB5D6BA",
            "text_color": "0x2E4A34",
            "hilited_text_color": "0x2E4A34",
            "hilited_back_color": "0xCCE8CF",
            "hilited_candidate_text_color": "0xFFFFFF",
            "hilited_candidate_back_color": "0x3E7B4F",
            "candidate_text_color": "0x2E4A34",
            "candidate_back_color": "0xCCE8CF",
            "comment_text_color": "0x5E7A64",
            "label_color": "0x5E7A64",
            "hilited_candidate_label_color": "0xFFFFFF",
        },
        "qingshi_orange": {
            "name": "暖阳橙",
            "back_color": "0xFFF8EF",
            "border_color": "0xF2D7B8",
            "text_color": "0x4A3524",
            "hilited_text_color": "0x4A3524",
            "hilited_back_color": "0xFFF8EF",
            "hilited_candidate_text_color": "0xFFFFFF",
            "hilited_candidate_back_color": "0xE87924",
            "candidate_text_color": "0x4A3524",
            "candidate_back_color": "0xFFF8EF",
            "comment_text_color": "0x9A7656",
            "label_color": "0x9A7656",
            "hilited_candidate_label_color": "0xFFFFFF",
        },
        "qingshi_red": {
            "name": "莓果红",
            "back_color": "0xFFF5F5",
            "border_color": "0xF0D0D2",
            "text_color": "0x482B30",
            "hilited_text_color": "0x482B30",
            "hilited_back_color": "0xFFF5F5",
            "hilited_candidate_text_color": "0xFFFFFF",
            "hilited_candidate_back_color": "0xC83E4D",
            "candidate_text_color": "0x482B30",
            "candidate_back_color": "0xFFF5F5",
            "comment_text_color": "0x9A6B71",
            "label_color": "0x9A6B71",
            "hilited_candidate_label_color": "0xFFFFFF",
        },
        "qingshi_black": {
            "name": "纯黑白",
            "back_color": "0x101010",
            "border_color": "0x383838",
            "text_color": "0xE6E6E6",
            "hilited_text_color": "0xFFFFFF",
            "hilited_back_color": "0x101010",
            "hilited_candidate_text_color": "0x111111",
            "hilited_candidate_back_color": "0xFFFFFF",
            "candidate_text_color": "0xE6E6E6",
            "candidate_back_color": "0x101010",
            "comment_text_color": "0xA0A0A0",
            "label_color": "0xA0A0A0",
            "hilited_candidate_label_color": "0x111111",
        },
        "qingshi_dark": {
            "name": "墨夜深色",
            "back_color": "0x2B2D31",
            "border_color": "0x3A3D42",
            "text_color": "0xE6E6E6",
            "hilited_text_color": "0xF2F2F2",
            "hilited_back_color": "0x2B2D31",
            "hilited_candidate_text_color": "0xFFFFFF",
            "hilited_candidate_back_color": "0x2F7CF6",
            "candidate_text_color": "0xE6E6E6",
            "candidate_back_color": "0x2B2D31",
            "comment_text_color": "0x8A8F99",
            "label_color": "0x8A8F99",
            "hilited_candidate_label_color": "0xFFFFFF",
        },
        "qingshi_sakura": {
            "name": "樱粉浅",
            "back_color": "0xFFF7F8",
            "border_color": "0xF2DDE1",
            "text_color": "0x4A2E34",
            "hilited_text_color": "0x4A2E34",
            "hilited_back_color": "0xFFF7F8",
            "hilited_candidate_text_color": "0xFFFFFF",
            "hilited_candidate_back_color": "0xD46A85",
            "candidate_text_color": "0x4A2E34",
            "candidate_back_color": "0xFFF7F8",
            "comment_text_color": "0xA8808A",
            "label_color": "0xA8808A",
            "hilited_candidate_label_color": "0xFFFFFF",
        },
        "qingshi_paper": {
            "name": "暖纸米黄",
            "back_color": "0xFBF6EA",
            "border_color": "0xE8DFC8",
            "text_color": "0x3D3527",
            "hilited_text_color": "0x3D3527",
            "hilited_back_color": "0xFBF6EA",
            "hilited_candidate_text_color": "0xFFFFFF",
            "hilited_candidate_back_color": "0xB07A3C",
            "candidate_text_color": "0x3D3527",
            "candidate_back_color": "0xFBF6EA",
            "comment_text_color": "0x8C8271",
            "label_color": "0x8C8271",
            "hilited_candidate_label_color": "0xFFFFFF",
        },
    }

    def write_weasel(self, st):
        lines = [
            "# 青石五笔 · 外观设置",
            "# 由设置中心生成，手工修改会在下次保存时被覆盖",
            "patch:",
            "  style:",
            f"    color_scheme: {st['color_scheme']}",
            f"    color_scheme_dark: {st['color_scheme']}",
            f'    font_face: "{st["font_face"]}"',
            f'    label_font_face: "{st["font_face"]}"',
            f'    comment_font_face: "{st["font_face"]}"',
            f"    font_point: {st['font_point']}",
            f"    horizontal: {'true' if st['horizontal'] else 'false'}",
            f"    inline_preedit: {'true' if st['inline_preedit'] else 'false'}",
            "    layout:",
            f"      round_corner: {st['round_corner']}",
            f"      corner_radius: {st['round_corner']}",
            "      border_width: 1",
            "      margin_x: 10",
            "      margin_y: 8",
            "      spacing: 8",
            "      candidate_spacing: 4",
            "      hilite_spacing: 3",
            "      hilite_padding: 2",
            "      shadow_radius: 6",
            "  preset_color_schemes:",
        ]
        fields = ["back_color", "border_color", "text_color", "hilited_text_color",
                  "hilited_back_color", "hilited_candidate_text_color",
                  "hilited_candidate_back_color", "candidate_text_color",
                  "candidate_back_color", "comment_text_color", "label_color",
                  "hilited_candidate_label_color"]
        for key, skin in self.SKINS.items():
            lines.append(f"    {key}:")
            lines.append(f'      name: "{skin["name"]}"')
            lines.append('      author: "青石五笔"')
            lines.append("      color_format: argb")
            for field in fields:
                lines.append(f"      {field}: {skin[field]}")
        with open(self.path("weasel.custom.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")

    # ---- 自定义词条 / 固顶词条 ----
    def read_phrases(self):
        """读取 custom_phrase.txt 里的词条，返回 [(词条, 编码), ...]"""
        p = self.path("custom_phrase.txt")
        out = []
        if not os.path.isfile(p):
            return out
        with open(p, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                if line.strip() in ("---", "...") or ":" in line.split("\t")[0]:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0] and parts[1]:
                    out.append((parts[0], parts[1]))
        return out

    def write_phrases(self, items):
        """按列表顺序重排权重写回：越靠前权重越高。Rime 的稳定词典只要纯 TSV。"""
        lines = [
            "# 青石五笔 · 自定义词条 / 固顶词条",
            "# 每行：词条<TAB>编码<TAB>权重",
            "# 权重越大越靠前；固顶词条用 9999。",
        ]
        for i, (word, code) in enumerate(items):
            lines.append(f"{word}\t{code}\t{max(1, 9999 - i)}")
        with open(self.path("custom_phrase.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")

    def deploy(self, wait=False):
        for d in WEASEL_CANDIDATES:
            exe = os.path.join(d, "WeaselDeployer.exe")
            if os.path.isfile(exe):
                proc = subprocess.Popen([exe, "/deploy"])
                if wait:
                    try:
                        proc.wait(timeout=25)
                    except subprocess.TimeoutExpired:
                        return False
                    if proc.returncode != 0:
                        return False
                return True
        return False

    def restart_server(self):
        """结束 WeaselServer；TSF 下次输入时自动拉起新实例并重读词表。
        custom_phrase 是稳定词典，只在方案加载时读，不重启就不会生效。"""
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            TH32CS_SNAPPROCESS = 0x00000002
            PROCESS_TERMINATE = 0x0001

            class PROCESSENTRY32W(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260),
                ]

            snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if snap == -1 or snap == 0xFFFFFFFFFFFFFFFF:
                return False
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            killed = False
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                if entry.szExeFile.lower() == "weaselserver.exe":
                    handle = kernel32.OpenProcess(
                        PROCESS_TERMINATE, False, entry.th32ProcessID)
                    if handle:
                        kernel32.TerminateProcess(handle, 0)
                        kernel32.CloseHandle(handle)
                        killed = True
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
            kernel32.CloseHandle(snap)
            return killed
        except Exception:
            return False

    def stats(self):
        """统计当前词库"""
        info = {}
        for sid, name, _ in SCHEMAS:
            p = self.path(f"{sid}.dict.yaml")
            if not os.path.isfile(p):
                continue
            n = 0
            with open(p, encoding="utf-8", errors="ignore") as f:
                started = False
                for line in f:
                    if line.strip() == "...":
                        started = True
                        continue
                    if started and line.strip():
                        n += 1
            info[sid] = n
        return info


# ---------------- 组件 ----------------
def hline():
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet("background:#eef0f3;")
    return f


class SchemaCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, sid, title, desc, checked=False):
        super().__init__()
        self.sid = sid
        self.setObjectName("schemaCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"{title}，默认输入方案")
        self.setProperty("checked", "true" if checked else "false")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        self.radio = QRadioButton()
        self.radio.setChecked(checked)
        self.radio.clicked.connect(lambda: self.clicked.emit(self.sid))
        heading = QHBoxLayout()
        heading.addWidget(self.radio)
        heading.addStretch()

        txt = QVBoxLayout()
        txt.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("schemaName")
        d = QLabel(desc)
        d.setObjectName("desc")
        d.setWordWrap(True)
        txt.addWidget(t)
        txt.addWidget(d)
        lay.addLayout(heading)
        lay.addLayout(txt, 1)

        self.badge = QLabel("")
        self.badge.setObjectName("badge")
        heading.addWidget(self.badge)

    def mousePressEvent(self, e):
        self.clicked.emit(self.sid)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.sid)
            e.accept()
            return
        super().keyPressEvent(e)

    def set_checked(self, on):
        self.radio.setChecked(on)
        self.setProperty("checked", "true" if on else "false")
        self.badge.setText("当前默认" if on else "")
        self.badge.setVisible(on)
        self.style().unpolish(self)
        self.style().polish(self)


class MainWindow(QMainWindow):
    def __init__(self, cfg=None):
        super().__init__()
        self.cfg = cfg or RimeConfig()
        self.setWindowTitle(f"{APP_NAME} · 设置")
        self.resize(1060, 720)
        self.setMinimumSize(900, 620)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        topbar = QWidget()
        topbar.setObjectName("topbar")
        th = QHBoxLayout(topbar)
        th.setContentsMargins(30, 20, 32, 12)
        th.setSpacing(12)
        mark = QLabel()
        mark.setObjectName("brandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(42, 42)
        logo = QIcon(os.path.join(os.path.dirname(__file__), "qingshi-mark.png"))
        self.setWindowIcon(logo)
        mark.setPixmap(logo.pixmap(QSize(42, 42)))
        th.addWidget(mark)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        brand = QLabel(APP_NAME)
        brand.setObjectName("brandTitle")
        subbrand = QLabel("五笔输入与外观设置")
        subbrand.setObjectName("brandSub")
        title_col.addWidget(brand)
        title_col.addWidget(subbrand)
        th.addLayout(title_col)
        th.addStretch(1)
        version = QLabel(f"设置中心  ·  v{APP_VER}")
        version.setObjectName("muted")
        th.addWidget(version)
        outer.addWidget(topbar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # ---- 左侧导航 ----
        nav = QWidget()
        nav.setObjectName("nav")
        nav.setFixedWidth(204)
        nv = QVBoxLayout(nav)
        nv.setContentsMargins(24, 22, 14, 18)
        nv.setSpacing(0)

        nav_label = QLabel("设置分类")
        nav_label.setObjectName("navSection")
        nav_label.setContentsMargins(10, 0, 0, 8)
        nv.addWidget(nav_label)

        self.nav_list = Navigation(["常用设置", "外观", "词库", "自定义词条", "快捷键", "关于"])
        self.nav_list.setObjectName("navList")
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self.switch_page)
        nv.addWidget(self.nav_list, 1)

        setup_panel = QFrame()
        setup_panel.setObjectName("statusPanel")
        setup_layout = QVBoxLayout(setup_panel)
        setup_layout.setContentsMargins(12, 12, 12, 12)
        setup_layout.setSpacing(7)
        setup_title = QLabel("首次配置")
        setup_title.setObjectName("sectionTitle")
        setup_hint = QLabel("按步骤选择方案与候选窗样式")
        setup_hint.setObjectName("hint")
        setup_hint.setWordWrap(True)
        setup_button = QPushButton("打开设置向导")
        setup_button.setObjectName("link")
        setup_button.clicked.connect(self.open_wizard)
        setup_layout.addWidget(setup_title)
        setup_layout.addWidget(setup_hint)
        setup_layout.addWidget(setup_button)
        nv.addWidget(setup_panel)

        ver = QLabel(f"v{APP_VER}")
        ver.setObjectName("muted")
        ver.setContentsMargins(10, 12, 0, 0)
        nv.addWidget(ver)

        body.addWidget(nav)

        # ---- 右侧内容 ----
        self.stack = QStackedWidget()
        self.stack.addWidget(self.page_common())
        self.stack.addWidget(self.page_appearance())
        self.stack.addWidget(self.page_dict())
        self.stack.addWidget(self.page_phrases())
        self.stack.addWidget(self.page_hotkey())
        self.stack.addWidget(self.page_about())
        body.addWidget(self.stack, 1)

        outer.addLayout(body, 1)

        # ---- 底部按钮 ----
        footer = QFrame()
        footer.setObjectName("footer")
        footer.setFixedHeight(70)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(28, 12, 32, 18)
        fl.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("ghost")
        btn_cancel.clicked.connect(self.close)
        btn_apply = QPushButton("应用")
        btn_apply.clicked.connect(lambda: self.save(True))
        btn_ok = QPushButton("确定")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.save_and_close)
        fl.addWidget(btn_cancel)
        fl.addWidget(btn_apply)
        fl.addWidget(btn_ok)
        outer.addWidget(footer)

        self.load()

    def open_wizard(self):
        from setup_wizard import SetupWizard
        wizard = SetupWizard(self.cfg, self)
        if wizard.exec():
            self.load()

    def save_and_close(self):
        if self.save(True):
            self.close()

    # ---------- 页面 ----------
    def wrap_scroll(self, w):
        # 内容页强制跟随视口宽度，避免长文本把页面撑出横向滚动条
        w.setMinimumWidth(0)
        w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setWidget(w)
        return sa

    def page_common(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 22, 28, 20)
        lay.setSpacing(16)
        h = QLabel("常用设置")
        h.setObjectName("h1")
        lay.addWidget(h)
        s = QLabel("选择常用码表，并调整候选显示方式")
        s.setObjectName("desc")
        lay.addWidget(s)

        columns = QVBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(16)

        scheme_column = QWidget()
        scheme_column.setObjectName("settingsColumn")
        scheme_layout = QVBoxLayout(scheme_column)
        scheme_layout.setContentsMargins(0, 0, 0, 0)
        scheme_layout.setSpacing(12)
        scheme_header = QFrame()
        scheme_header.setObjectName("sectionHeader")
        scheme_header_layout = QHBoxLayout(scheme_header)
        scheme_header_layout.setContentsMargins(0, 0, 0, 8)
        scheme_header_layout.setSpacing(10)
        scheme_number = QLabel("01")
        scheme_number.setObjectName("sectionNumber")
        scheme_number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scheme_number.setFixedSize(34, 30)
        scheme_title_col = QVBoxLayout()
        scheme_title_col.setSpacing(2)
        scheme_head = QLabel("默认方案")
        scheme_head.setObjectName("sectionTitle")
        scheme_hint = QLabel("设为默认，之后仍可随时切换")
        scheme_hint.setObjectName("hint")
        scheme_title_col.addWidget(scheme_head)
        scheme_title_col.addWidget(scheme_hint)
        scheme_header_layout.addWidget(scheme_number)
        scheme_header_layout.addLayout(scheme_title_col, 1)
        scheme_number.hide()
        scheme_layout.addWidget(scheme_header)

        self.cards = {}
        self.schema_group = QButtonGroup(self)
        schema_row = QHBoxLayout()
        schema_row.setSpacing(12)
        for sid, name, desc in SCHEMAS:
            c = SchemaCard(sid, name, desc)
            c.setMinimumHeight(112)
            c.clicked.connect(self.pick_schema)
            schema_row.addWidget(c, 1)
            self.cards[sid] = c
        scheme_layout.addLayout(schema_row)
        columns.addWidget(scheme_column)

        habit_panel = QFrame()
        habit_panel.setObjectName("candidatePanel")
        habit_panel.setMinimumWidth(240)
        habit_layout = QVBoxLayout(habit_panel)
        habit_layout.setContentsMargins(0, 12, 20, 0)
        habit_layout.setSpacing(10)
        habit_header = QHBoxLayout()
        habit_header.setSpacing(9)
        habit_number = QLabel("02")
        habit_number.setObjectName("sectionNumber")
        habit_number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        habit_number.setFixedSize(30, 28)
        habit_head = QLabel("输入习惯")
        habit_head.setObjectName("sectionTitle")
        habit_number.hide()
        habit_header.addWidget(habit_head, 1)
        habit_layout.addLayout(habit_header)
        habit_intro = QLabel("简繁、全半角与标点风格")
        habit_intro.setObjectName("hint")
        habit_layout.addWidget(habit_intro)

        def habit_row(text, combo):
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(text)
            label.setObjectName("fieldLabel")
            row.addWidget(label, 1)
            combo.setMinimumWidth(118)
            row.addWidget(combo)
            habit_layout.addLayout(row)

        self.combo_trad = QComboBox()
        self.combo_trad.addItem("简体", 0)
        self.combo_trad.addItem("繁体", 1)
        self.combo_trad.setAccessibleName("简繁输出方式")
        habit_row("简繁输出", self.combo_trad)

        self.combo_shape = QComboBox()
        self.combo_shape.addItem("半角", 0)
        self.combo_shape.addItem("全角", 1)
        self.combo_shape.setAccessibleName("字符宽度")
        habit_row("字符宽度", self.combo_shape)

        self.combo_punct = QComboBox()
        self.combo_punct.addItem("中文标点", 0)
        self.combo_punct.addItem("英文标点", 1)
        self.combo_punct.setAccessibleName("标点符号风格")
        habit_row("标点符号", self.combo_punct)

        self.chk_shift_commit = QCheckBox("按 Shift 上屏编码并切换中英文")
        self.chk_shift_commit.setToolTip(
            "按 Shift 时把已输入的编码上屏为字母，同时切到英文模式（Rime 内核把两者绑在一起）")
        self.chk_shift_commit.setAccessibleName("Shift 上屏编码并切换中英文")
        habit_row("Shift 键", self.chk_shift_commit)

        self.chk_shift_direct = QCheckBox("Shift + 字母直接输出")
        self.chk_shift_direct.setToolTip(
            "按住 Shift 敲字母时直接输出该字母，不进入五笔编码")
        self.chk_shift_direct.setAccessibleName("Shift 加字母直接输出")
        habit_layout.addWidget(self.chk_shift_direct)

        habit_tip = QLabel("「按 Shift 上屏编码」会把已输入的编码上屏；Rime 内核在上屏时会顺带切换中英文，两者不可分。")
        habit_tip.setObjectName("hint")
        habit_tip.setWordWrap(True)
        habit_layout.addWidget(habit_tip)
        habit_layout.addStretch(1)

        candidate_panel = QFrame()
        candidate_panel.setObjectName("candidatePanel")
        candidate_panel.setMinimumWidth(220)
        candidate_layout = QVBoxLayout(candidate_panel)
        candidate_layout.setContentsMargins(8, 12, 0, 0)
        candidate_layout.setSpacing(12)
        candidate_header = QHBoxLayout()
        candidate_header.setSpacing(9)
        candidate_number = QLabel("03")
        candidate_number.setObjectName("sectionNumber")
        candidate_number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        candidate_number.setFixedSize(30, 28)
        candidate_head = QLabel("候选设置")
        candidate_head.setObjectName("sectionTitle")
        candidate_intro = QLabel("设置每页数量与候选窗排布")
        candidate_intro.setObjectName("hint")
        candidate_intro.setWordWrap(True)
        candidate_number.hide()
        candidate_header.addWidget(candidate_head, 1)
        candidate_layout.addLayout(candidate_header)
        candidate_layout.addWidget(candidate_intro)

        count_row = QHBoxLayout()
        count_row.setSpacing(8)
        count_label = QLabel("每页数量")
        count_label.setObjectName("fieldLabel")
        self.spin_page = QSpinBox()
        self.spin_page.setRange(3, 10)
        self.spin_page.setFixedWidth(104)
        self.spin_page.setSuffix(" 个")
        self.spin_page.setAccessibleName("每页候选词数量，范围 3 到 10")
        count_row.addWidget(count_label, 1)
        count_row.addWidget(self.spin_page)
        candidate_layout.addLayout(count_row)

        divider = hline()
        divider.setObjectName("settingsDivider")
        divider.hide()

        self.chk_h = QCheckBox("横排显示")
        self.chk_h.setAccessibleName("横排显示候选词")
        self.chk_h.setToolTip("候选词从左向右排列")
        self.chk_i = QCheckBox("编码跟随光标")
        self.chk_i.setAccessibleName("编码内嵌在光标处")
        self.chk_i.setToolTip("输入编码显示在当前光标位置")
        candidate_layout.addWidget(self.chk_h)
        candidate_layout.addWidget(self.chk_i)
        candidate_layout.addStretch(1)
        preferences = QHBoxLayout()
        preferences.setSpacing(28)
        preferences.addWidget(habit_panel, 3)
        preferences.addWidget(candidate_panel, 2)
        columns.addLayout(preferences)

        lay.addLayout(columns)
        lay.addStretch(1)

        return self.wrap_scroll(w)

    def page_appearance(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(14)
        h = QLabel("外观")
        h.setObjectName("h1")
        lay.addWidget(h)
        s = QLabel("候选窗配色、字体与圆角")
        s.setObjectName("desc")
        lay.addWidget(s)

        theme_row = QHBoxLayout()
        theme_row.setSpacing(14)
        theme_panel = QFrame()
        theme_panel.setObjectName("candidatePanel")
        theme_layout = QVBoxLayout(theme_panel)
        theme_layout.setContentsMargins(18, 16, 18, 16)
        theme_layout.setSpacing(10)
        theme_title = QLabel("候选窗主题")
        theme_title.setObjectName("sectionTitle")
        theme_layout.addWidget(theme_title)
        self.combo_scheme = QComboBox()
        for key, skin in self.cfg.SKINS.items():
            self.combo_scheme.addItem(skin["name"], key)
        self.combo_scheme.setMinimumWidth(220)
        self.combo_scheme.currentIndexChanged.connect(self.update_candidate_preview)
        theme_layout.addWidget(self.combo_scheme)
        theme_hint = QLabel("预览使用与候选窗相同的配色，切换后即时刷新")
        theme_hint.setObjectName("hint")
        theme_layout.addWidget(theme_hint)
        theme_layout.addStretch(1)
        theme_row.addWidget(theme_panel, 1)

        preview_panel = QFrame()
        preview_panel.setObjectName("candidatePreview")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(16, 14, 16, 14)
        preview_layout.setSpacing(10)
        preview_heading = QLabel("效果预览")
        preview_heading.setObjectName("hint")
        self.preview_title = QLabel("青石五笔　五笔 86")
        self.preview_title.setObjectName("previewTitle")
        candidate_row = QHBoxLayout()
        candidate_row.setSpacing(7)
        # 预览只放真实的候选形态：第一个是高亮态，其余普通态
        candidate_one = QLabel("1  文字")
        candidate_two = QLabel("2  输入")
        self.preview_candidates = [candidate_one, candidate_two]
        candidate_row.addWidget(candidate_one)
        candidate_row.addWidget(candidate_two)
        candidate_row.addStretch(1)
        preview_layout.addWidget(preview_heading)
        preview_layout.addWidget(self.preview_title)
        preview_layout.addLayout(candidate_row)
        theme_row.addWidget(preview_panel, 1)
        lay.addLayout(theme_row)

        gb2 = QGroupBox("字体")
        g2 = QGridLayout(gb2)
        g2.setContentsMargins(20, 20, 20, 18)
        g2.setHorizontalSpacing(18)
        g2.setVerticalSpacing(16)
        g2.addWidget(QLabel("字体"), 0, 0)
        self.combo_font = QComboBox()
        self.combo_font.addItems(["Microsoft YaHei", "SimSun", "SimHei", "KaiTi", "Consolas"])
        self.combo_font.setMinimumWidth(220)
        g2.addWidget(self.combo_font, 0, 1)
        g2.addWidget(QLabel("字号"), 0, 2)
        self.spin_font = QSpinBox()
        self.spin_font.setRange(9, 24)
        self.spin_font.setSuffix(" pt")
        self.spin_font.setFixedWidth(96)
        g2.addWidget(self.spin_font, 0, 3)
        g2.addWidget(QLabel("圆角"), 1, 0)
        self.spin_round = QSpinBox()
        self.spin_round.setRange(0, 16)
        self.spin_round.setSuffix(" px")
        self.spin_round.setFixedWidth(96)
        self.spin_round.valueChanged.connect(self.update_candidate_preview)
        g2.addWidget(self.spin_round, 1, 1)
        g2.setColumnStretch(4, 1)
        lay.addWidget(gb2)

        lay.addStretch(1)
        return self.wrap_scroll(w)

    def update_candidate_preview(self):
        key = self.combo_scheme.currentData() or "qingshi_blue"
        skin = self.cfg.SKINS.get(key, self.cfg.SKINS["qingshi_blue"])

        def rgb(value):
            return "#" + str(value).replace("0x", "")[-6:]

        bg = rgb(skin["back_color"])
        fg = rgb(skin["candidate_text_color"])
        border = rgb(skin["border_color"])
        hl_bg = rgb(skin["hilited_candidate_back_color"])
        hl_fg = rgb(skin["hilited_candidate_text_color"])
        comment = rgb(skin["comment_text_color"])
        radius = self.spin_round.value()

        self.preview_title.setStyleSheet(f"color:{comment};font-size:11px;")
        for i, label in enumerate(self.preview_candidates):
            if i == 0:
                label.setStyleSheet(
                    f"color:{hl_fg};background:{hl_bg};"
                    f"border-radius:{max(2, radius - 2)}px;padding:2px 8px;font-size:11px;")
            else:
                label.setStyleSheet(f"color:{fg};padding:2px 8px;font-size:11px;")
        preview_panel = self.findChild(QFrame, "candidatePreview")
        if preview_panel:
            preview_panel.setStyleSheet(
                f"QFrame#candidatePreview {{ background:{bg}; border:1px solid {border};"
                f" border-radius:{radius}px; }}")

    def page_dict(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(14)
        h = QLabel("词库")
        h.setObjectName("h1")
        lay.addWidget(h)
        s = QLabel("查看码表规模，导入自定义码表")
        s.setObjectName("desc")
        lay.addWidget(s)

        section_title = QLabel("词库规模")
        section_title.setObjectName("sectionTitle")
        lay.addWidget(section_title)
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.dict_stat_labels = {}
        for sid, name, _ in SCHEMAS:
            card = QFrame()
            card.setObjectName("metricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 14, 15, 14)
            card_layout.setSpacing(5)
            title = QLabel(name)
            title.setObjectName("hint")
            amount = QLabel("读取中…")
            amount.setObjectName("metricValue")
            unit = QLabel("词条")
            unit.setObjectName("hint")
            card_layout.addWidget(title)
            card_layout.addWidget(amount)
            card_layout.addWidget(unit)
            stats_row.addWidget(card, 1)
            self.dict_stat_labels[sid] = amount
        lay.addLayout(stats_row)

        action_panel = QFrame()
        action_panel.setObjectName("candidatePanel")
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(18, 16, 18, 16)
        action_layout.setSpacing(10)
        action_title = QLabel("管理自定义码表")
        action_title.setObjectName("sectionTitle")
        d = QLabel("导入 TXT 码表，每行一条“编码 词条”。导入前会自动备份当前词库。")
        d.setObjectName("hint")
        d.setWordWrap(True)
        action_layout.addWidget(action_title)
        action_layout.addWidget(d)
        row = QHBoxLayout()
        b1 = QPushButton("导入码表…")
        b1.clicked.connect(self.import_dict)
        b2 = QPushButton("打开用户目录")
        b2.clicked.connect(self.open_userdir)
        b3 = QPushButton("重新部署")
        b3.setObjectName("primary")
        b3.clicked.connect(self.redeploy)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addWidget(b3)
        row.addStretch(1)
        action_layout.addLayout(row)
        lay.addWidget(action_panel)

        lay.addStretch(1)
        return self.wrap_scroll(w)

    def page_phrases(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(14)
        h = QLabel("自定义词条")
        h.setObjectName("h1")
        lay.addWidget(h)
        s = QLabel("自定义词条会排在候选最前面；列表顺序就是候选顺序")
        s.setObjectName("desc")
        lay.addWidget(s)

        panel = QFrame()
        panel.setObjectName("candidatePanel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(16, 16, 16, 14)
        pl.setSpacing(10)

        self.phrase_table = QTableWidget(0, 2)
        self.phrase_table.setHorizontalHeaderLabels(["词条", "编码"])
        self.phrase_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.phrase_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed)
        self.phrase_table.setColumnWidth(1, 130)
        self.phrase_table.verticalHeader().setVisible(False)
        self.phrase_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.phrase_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.phrase_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.phrase_table.setMinimumHeight(280)
        self.phrase_table.setAccessibleName("自定义词条列表")
        pl.addWidget(self.phrase_table)

        row = QHBoxLayout()
        row.setSpacing(8)
        b_add = QPushButton("添加…")
        b_add.clicked.connect(self.phrase_add)
        b_edit = QPushButton("编辑…")
        b_edit.setToolTip("修改选中词条的内容或编码")
        b_edit.clicked.connect(self.phrase_edit)
        b_del = QPushButton("删除")
        b_del.clicked.connect(self.phrase_del)
        b_up = QPushButton("上移")
        b_up.clicked.connect(lambda: self.phrase_move(-1))
        b_down = QPushButton("下移")
        b_down.clicked.connect(lambda: self.phrase_move(1))
        b_pin = QPushButton("固顶")
        b_pin.setObjectName("primary")
        b_pin.setToolTip("把选中词条移到第一位，候选里最先出现")
        b_pin.clicked.connect(self.phrase_pin)
        for b in (b_add, b_edit, b_del, b_up, b_down):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(b_pin)
        pl.addLayout(row)
        lay.addWidget(panel)

        self.phrase_table.doubleClicked.connect(lambda _idx: self.phrase_edit())

        tip = QLabel(
            "提示：输入时也可在候选窗上点右键，直接把当前词固顶或加入自定义词条。"
            "修改后点「应用」重新部署生效。")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addStretch(1)
        return self.wrap_scroll(w)

    # ---- 自定义词条操作 ----
    def load_phrases(self):
        self.phrases = self.cfg.read_phrases()
        self.refresh_phrases()

    def refresh_phrases(self):
        t = self.phrase_table
        t.setRowCount(len(self.phrases))
        for i, (word, code) in enumerate(self.phrases):
            t.setItem(i, 0, QTableWidgetItem(word))
            t.setItem(i, 1, QTableWidgetItem(code))
        if self.phrases and t.currentRow() < 0:
            t.selectRow(0)

    def phrase_add(self):
        word, ok = QInputDialog.getText(self, "添加词条", "词条内容：")
        if not ok or not word.strip():
            return
        word = word.strip()
        code, ok = QInputDialog.getText(
            self, "添加词条", f"「{word}」的五笔编码（1-4 位字母）：")
        if not ok:
            return
        code = code.strip().lower()
        if not (1 <= len(code) <= 4 and all("a" <= ch <= "y" for ch in code)):
            QMessageBox.warning(self, "编码无效", "五笔编码只能是 a-y 之间的 1-4 位字母。")
            return
        self.phrases.append((word, code))
        self.refresh_phrases()
        self.phrase_table.selectRow(len(self.phrases) - 1)
        self.cfg.write_phrases(self.phrases)

    def phrase_edit(self):
        row = self.phrase_table.currentRow()
        if row < 0 or row >= len(self.phrases):
            return
        old_word, old_code = self.phrases[row]
        word, ok = QInputDialog.getText(self, "编辑词条", "词条内容：", text=old_word)
        if not ok or not word.strip():
            return
        word = word.strip()
        code, ok = QInputDialog.getText(
            self, "编辑词条", f"「{word}」的五笔编码（1-4 位字母）：", text=old_code)
        if not ok:
            return
        code = code.strip().lower()
        if not (1 <= len(code) <= 4 and all("a" <= ch <= "y" for ch in code)):
            QMessageBox.warning(self, "编码无效", "五笔编码只能是 a-y 之间的 1-4 位字母。")
            return
        self.phrases[row] = (word, code)
        self.refresh_phrases()
        self.phrase_table.selectRow(row)
        self.cfg.write_phrases(self.phrases)

    def phrase_del(self):
        row = self.phrase_table.currentRow()
        if row < 0 or row >= len(self.phrases):
            return
        del self.phrases[row]
        self.refresh_phrases()
        self.cfg.write_phrases(self.phrases)

    def phrase_move(self, delta):
        row = self.phrase_table.currentRow()
        if row < 0 or row >= len(self.phrases):
            return
        target = row + delta
        if not (0 <= target < len(self.phrases)):
            return
        self.phrases[row], self.phrases[target] = self.phrases[target], self.phrases[row]
        self.refresh_phrases()
        self.phrase_table.selectRow(target)
        self.cfg.write_phrases(self.phrases)

    def phrase_pin(self):
        row = self.phrase_table.currentRow()
        if row <= 0 or row >= len(self.phrases):
            return
        item = self.phrases.pop(row)
        self.phrases.insert(0, item)
        self.refresh_phrases()
        self.phrase_table.selectRow(0)
        self.cfg.write_phrases(self.phrases)

    def page_hotkey(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(14)
        h = QLabel("快捷键")
        h.setObjectName("h1")
        lay.addWidget(h)
        s = QLabel("输入状态类快捷键可在输入时随时切换，改动立即生效")
        s.setObjectName("desc")
        lay.addWidget(s)
        gb = QFrame()
        gb.setObjectName("candidatePanel")
        g = QVBoxLayout(gb)
        g.setContentsMargins(16, 16, 16, 16)
        g.setSpacing(9)
        gb_title = QLabel("默认快捷键")
        gb_title.setObjectName("sectionTitle")
        g.addWidget(gb_title)
        rows = [
            ("中英文切换", "Shift"),
            ("简繁转换", "Ctrl + Shift + F"),
            ("简繁转换（备用）", "Ctrl + Shift + T"),
            ("全角 / 半角", "Shift + 空格"),
            ("中英标点", "Ctrl + ."),
            ("增广字集", "Ctrl + Shift + 5"),
            ("切换方案", "F4 或 Ctrl + `"),
            ("候选翻页", "- / = 或 , / ."),
            ("选词", "数字键 1-9 / 空格选第一"),
            ("清空编码", "Esc"),
            ("切换输入法", "Win + 空格"),
            ("重新部署", "托盘图标右键 → 重新部署"),
        ]
        for k, v in rows:
            row = QFrame()
            row.setObjectName("shortcutRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 7, 12, 7)
            row_layout.setSpacing(12)
            label = QLabel(k)
            value = QLabel(v)
            value.setObjectName("shortcutChip")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(label, 1)
            row_layout.addWidget(value)
            g.addWidget(row)
        lay.addWidget(gb)

        tip = QLabel("提示：简繁转换会按 OpenCC 规则把候选词输出为繁体，码表与候选顺序不变。")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addStretch(1)
        return self.wrap_scroll(w)

    def page_about(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(6)
        lay.addSpacing(10)

        gb = QGroupBox(APP_NAME)
        g = QVBoxLayout(gb)
        info = QLabel(
            f"版本：{APP_VER}\n"
            "内核：librime + Weasel（自行编译 x64）\n"
            "码表：极点五笔官方原版（极爽 4.3 for 极点 Unicode，2011-12-27）\n"
            "　　　+ 98 版 + 新世纪版\n"
            "许可：Weasel 遵循 GPL-3.0，librime 遵循 BSD-3-Clause"
        )
        info.setStyleSheet("font-size:13px;color:#3c4149;line-height:2;")
        g.addWidget(info)
        lay.addWidget(gb)

        gb2 = QGroupBox("码表说明")
        g2 = QVBoxLayout(gb2)
        t = QLabel(
            "· 三套方案均保持原表物理顺序（Rime 中通过 sort: original 实现），\n"
            "  不按词频重排，保证与极点/王码原版一致。\n"
            "· 86 版单字 26,584 个，GBK 20,902 字全覆盖。\n"
            "· 已过滤非法编码（英文单词、超过 4 码的条目）。"
        )
        t.setObjectName("desc")
        g2.addWidget(t)
        lay.addWidget(gb2)

        lay.addStretch(1)
        return self.wrap_scroll(w)

    # ---------- 逻辑 ----------
    def switch_page(self, i):
        self.stack.setCurrentIndex(i)

    def pick_schema(self, sid):
        self.cur_schema = sid
        for k, c in self.cards.items():
            c.set_checked(k == sid)
        self.load_habits(sid)

    def load_habits(self, sid):
        sw = self.cfg.schema_switches(sid)
        self.combo_trad.setCurrentIndex(1 if sw.get("traditional") else 0)
        self.combo_shape.setCurrentIndex(1 if sw.get("full_shape") else 0)
        self.combo_punct.setCurrentIndex(1 if sw.get("ascii_punct") else 0)
        self.chk_shift_commit.setChecked(sw.get("shift_commit", True))
        self.chk_shift_direct.setChecked(self.cfg.shift_letter_direct())

    def load(self):
        self.cur_schema = self.cfg.current_schema()
        for k, c in self.cards.items():
            c.set_checked(k == self.cur_schema)
        self.spin_page.setValue(self.cfg.page_size())
        self.load_habits(self.cur_schema)

        st = self.cfg.weasel_style()
        self.chk_h.setChecked(st["horizontal"])
        self.chk_i.setChecked(st["inline_preedit"])
        idx = self.combo_scheme.findData(st["color_scheme"])
        if idx < 0:
            idx = 0
        self.combo_scheme.setCurrentIndex(idx)
        if st["font_face"] in [self.combo_font.itemText(i) for i in range(self.combo_font.count())]:
            self.combo_font.setCurrentText(st["font_face"])
        self.spin_font.setValue(st["font_point"])
        self.spin_round.setValue(st["round_corner"])

        # 词库统计
        st2 = self.cfg.stats()
        for sid, name, _ in SCHEMAS:
            n = st2.get(sid)
            self.dict_stat_labels[sid].setText(f"{n:,}" if n else "未安装")
        self.load_phrases()

    def save(self, deploy=True):
        try:
            self.cfg.write_default(self.cur_schema, self.spin_page.value())
            self.cfg.write_schema_switches(self.cur_schema, {
                "traditional": self.combo_trad.currentData(),
                "full_shape": self.combo_shape.currentData(),
                "ascii_punct": self.combo_punct.currentData(),
                "shift_commit": self.chk_shift_commit.isChecked(),
                "shift_toggle": self.chk_shift_commit.isChecked(),
            })
            self.cfg.set_shift_letter_direct(self.chk_shift_direct.isChecked())
            self.cfg.write_weasel({
                "color_scheme": self.combo_scheme.currentData(),
                "font_face": self.combo_font.currentText(),
                "font_point": self.spin_font.value(),
                "horizontal": self.chk_h.isChecked(),
                "inline_preedit": self.chk_i.isChecked(),
                "round_corner": self.spin_round.value(),
            })
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return False
        if deploy:
            ok = self.cfg.deploy(wait=True)
            restarted = False
            if ok:
                # custom_phrase 只在方案加载时读，必须重启服务才生效
                restarted = self.cfg.restart_server()
            QMessageBox.information(
                self, "已应用",
                "配置已保存" +
                ("，输入法服务已重启，新设置立即生效。" if restarted else
                 "，正在重新部署…" if ok else
                 "。\n未找到 WeaselDeployer，请手动在托盘菜单里重新部署。")
            )
        return True

    def import_dict(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择码表", "", "文本文件 (*.txt);;所有文件 (*)")
        if not p:
            return
        sid = self.cur_schema
        dst = self.cfg.path(f"{sid}.dict.yaml")
        # 备份
        if os.path.isfile(dst):
            bak = dst + ".bak"
            shutil.copy2(dst, bak)
        # 转换 txt -> dict.yaml
        n = 0
        out = [f"---\nname: {sid}\nversion: \"1.0\"\nsort: original\ncolumns:\n  - text\n  - code\n  - weight\n...\n"]
        with open(p, encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                parts = s.split()
                if len(parts) < 2:
                    continue
                code, word = parts[0].lower(), parts[1]
                if not (1 <= len(code) <= 4) or not all("a" <= ch <= "y" for ch in code):
                    continue
                out.append(f"{word}\t{code}\t0")
                n += 1
        with open(dst, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out) + "\n")
        QMessageBox.information(self, "导入完成", f"已导入 {n:,} 条到「{sid}」，正在重新部署…")
        self.cfg.deploy(wait=True)
        self.cfg.restart_server()
        self.load()

    def open_userdir(self):
        os.startfile(self.cfg.dir)

    def redeploy(self):
        ok = self.cfg.deploy(wait=True)
        restarted = self.cfg.restart_server() if ok else False
        QMessageBox.information(
            self, "重新部署",
            "已重新部署并重启输入法服务" if restarted
            else ("已触发部署" if ok else "未找到 WeaselDeployer"))


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    if "--wizard" in sys.argv[1:]:
        from setup_wizard import SetupWizard
        w = SetupWizard()
    else:
        w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
