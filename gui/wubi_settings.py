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
import time

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QPixmap, QColor, QPainter, QPalette
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QRadioButton, QButtonGroup, QSpinBox, QCheckBox,
    QComboBox, QLineEdit, QListWidget, QListWidgetItem, QStackedWidget,
    QGroupBox, QFrame, QMessageBox, QFileDialog, QScrollArea, QSlider,
    QSizePolicy, QSpacerItem, QTextEdit, QDialog, QDialogButtonBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QInputDialog, QAbstractItemView,
    QProgressBar
)

try:
    import yaml
except ImportError:
    yaml = None

APP_NAME = "青石五笔输入法"
APP_VER = "1.0.10"
from app_paths import user_directory, runtime_directories
RIME_DIR = user_directory()
WEASEL_CANDIDATES = runtime_directories()

SCHEMAS = [
    ("wubi86", "五笔 86", "王码86版原表 · 极点官方词库"),
    ("wubi98", "五笔 98", "98版码元体系"),
    ("wubi06", "新世纪五笔", "2008 新世纪版"),
]


def apply_plan(appearance_changed, phrases_changed, needs_deploy):
    """点「应用」之后该走哪条路。

    - restart : 自定义词条是稳定词典，只在方案加载时读进引擎，必须重启服务；
    - reload  : 外观（配色/字体/圆角/横竖排）客户端会自己同步到已打开的候选窗，
                热加载即可，不重启、不打断输入；
    - deploy  : 只有配置还没进部署产物时才需要跑部署器。
    """
    if phrases_changed:
        return 'restart'
    if appearance_changed:
        return 'deploy+reload' if needs_deploy else 'reload'
    return 'deploy' if needs_deploy else 'reload'

# ---------------- 样式 ----------------
from ui_theme import QSS, apply_theme
from navigation import Navigation


class BusyDialog(QDialog):
    """耗时操作（重新部署 / 重启服务）期间的等待窗口。

    以前这些操作是在 UI 线程里同步跑的，窗口整个白掉、系统标"无响应"，
    用户以为卡死。现在至少给一个明确的"正在做什么"。
    默认保存只走热重载（毫秒级），不会弹这个。
    """

    def __init__(self, parent, title='正在应用', message='正在重新编译词库…',
                 hint='这一步通常需要几秒到十几秒，期间输入法暂时不可用。'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(400)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(10)

        head = QLabel(message)
        head.setObjectName('sectionH1')
        lay.addWidget(head)

        sub = QLabel(hint)
        sub.setObjectName('hint')
        sub.setWordWrap(True)
        lay.addWidget(sub)

        bar = QProgressBar()
        bar.setRange(0, 0)          # 不确定进度：来回滚动
        bar.setFixedHeight(6)
        bar.setTextVisible(False)
        lay.addWidget(bar)

    def finish(self):
        self.accept()


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
                     layout.get("round_corner"))),
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
        lines.extend(["  translator/enable_user_dict: false",
                      "  translator/enable_sentence: false",
                      "  translator/enable_encoder: false",
                      "  translator/encode_commit_history: false"])
        with open(self.path(f"{sid}.custom.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")

    # ---- Shift+字母直出（全局开关，存在注册表） ----
    REG_PATH = r"Software\Rime\Weasel"
    REG_NAME = "QingshiShiftLetterDirect"
    REG_BEEP = "QingshiBeepOnNoCandidate"
    REG_AUTO_COMMIT = "QingshiAutoCommitUnique"

    def _reg_flag(self, name, default=True):
        """读注册表里的开关。值不存在就按默认值算（这两个功能默认都是开）。"""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH) as k:
                return bool(winreg.QueryValueEx(k, name)[0])
        except Exception:
            return default

    def _set_reg_flag(self, name, enabled):
        try:
            import winreg
            with winreg.CreateKeyEx(
                    winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_WRITE) as k:
                winreg.SetValueEx(k, name, 0, winreg.REG_DWORD,
                                  1 if enabled else 0)
            return True
        except Exception:
            return False

    def no_candidate_beep(self):
        """四码无候选提示音。默认开启。"""
        return self._reg_flag(self.REG_BEEP)

    def set_no_candidate_beep(self, enabled):
        return self._set_reg_flag(self.REG_BEEP, enabled)

    def auto_commit_unique(self):
        """四码唯一自动上屏。**默认关闭** —— 会改变输入节奏，要显式打开。"""
        return self._reg_flag(self.REG_AUTO_COMMIT, default=False)

    def set_auto_commit_unique(self, enabled):
        return self._set_reg_flag(self.REG_AUTO_COMMIT, enabled)

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
            lines.append(f"      hilited_label_color: {skin['hilited_candidate_label_color']}")
        with open(self.path("weasel.custom.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")

    def appearance_needs_deploy(self):
        patch = self.read_yaml('weasel.custom.yaml').get('patch') or {}
        compiled = self.read_yaml('build/weasel.yaml')
        def contains(actual, expected):
            if isinstance(expected, dict):
                return isinstance(actual, dict) and all(
                    key in actual and contains(actual[key], value) for key, value in expected.items())
            return actual == expected
        return not contains(compiled, patch)

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

    # ---- 候选调序（shadow 层）----
    # 文件在用户数据目录根部：shadow_<方案>.yaml
    #     version: 1
    #     rules:
    #       "wqiy":
    #         - "你"
    #         - "仰泳"
    # 含义：打 wqiy 时「你」第一、「仰泳」第二，其余候选保持原相对顺序。
    # 删掉某个编码，那个编码就回到词库默认顺序；删掉整个文件 = 全部恢复默认。
    # 注意：这里**不动词库、不触发部署**，改完调 reload() 让服务重读即可。
    def shadow_path(self, schema):
        return self.path(f"shadow_{schema}.yaml")

    @staticmethod
    def _yaml_quote(s):
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

    def read_shadow(self, schema):
        """返回 {编码: [词1, 词2, ...]}，按文件里的顺序。"""
        p = self.shadow_path(schema)
        rules = {}
        if not os.path.isfile(p):
            return rules
        # 自己逐行解析，和 C++ 端 _LoadShadow 的规则完全对齐；
        # 走 yaml.safe_load 会因为缩进/引号写法差异出现读不到的情况。
        current = None
        try:
            with open(p, encoding="utf-8") as f:
                for raw in f:
                    line = raw.rstrip("\r\n")
                    s = line.lstrip(" \t")
                    if not s or s.startswith("#"):
                        continue
                    if s.startswith("- "):
                        word = s[2:].strip()
                        if len(word) >= 2 and word[0] == '"' and word[-1] == '"':
                            word = word[1:-1].replace('\\"', '"').replace("\\\\", "\\")
                        if current and word:
                            rules[current].append(word)
                        continue
                    if ":" not in s:
                        continue
                    key = s.split(":", 1)[0].strip()
                    if len(key) >= 2 and key[0] == '"' and key[-1] == '"':
                        key = key[1:-1].replace('\\"', '"').replace("\\\\", "\\")
                    if not key or key in ("rules", "version"):
                        continue
                    current = key
                    rules.setdefault(current, [])
        except Exception:
            return {}
        return {k: v for k, v in rules.items() if v}

    def write_shadow(self, schema, rules):
        """整表写回。rules 为空时直接删文件 —— 这就是「恢复默认词序」。"""
        p = self.shadow_path(schema)
        live = {k: list(v) for k, v in rules.items() if v}
        if not live:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                return False
            return True
        lines = [
            "# 青石五笔 候选调序",
            "# 由输入法在候选上「置顶」时自动写入；删掉对应编码即恢复默认顺序。",
            "version: 1",
            "rules:",
        ]
        for code, words in live.items():
            lines.append(f"  {self._yaml_quote(code)}:")
            for w in words:
                lines.append(f"    - {self._yaml_quote(w)}")
        try:
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            return False
        return True

    def reload(self, wait=True):
        """让正在运行的服务重读配置 —— 不部署、不重启引擎。

        外观、按键、候选数、标点、主题、候选调序表走这条，实测 150–300ms。
        只有码表/词库/自造词这类要重新编译的东西才需要 deploy()。
        """
        for d in WEASEL_CANDIDATES:
            exe = os.path.join(d, "WeaselDeployer.exe")
            if os.path.isfile(exe):
                proc = subprocess.Popen([exe, "/reload"])
                if wait:
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        return False
                    return proc.returncode == 0
                return True
        return False

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

    def runtime_dir(self):
        """找到真正装着 WeaselServer.exe 的运行时目录。"""
        for d in WEASEL_CANDIDATES:
            if os.path.isfile(os.path.join(d, "WeaselServer.exe")):
                return d
        return None

    def server_pipe(self):
        # Weasel 的 IPC 管道名：\\.\pipe\<用户名>\WeaselNamedPipe
        return "\\\\.\\pipe\\%s\\WeaselNamedPipe" % os.environ.get("USERNAME", "")

    @staticmethod
    def _server_pids():
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            TH32CS_SNAPPROCESS = 0x00000002

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
                return []
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            pids = []
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                if entry.szExeFile.lower() == "weaselserver.exe":
                    pids.append(entry.th32ProcessID)
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
            kernel32.CloseHandle(snap)
            return pids
        except Exception:
            return []

    def _terminate_servers(self):
        try:
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            PROCESS_TERMINATE = 0x0001
            killed = False
            for pid in self._server_pids():
                handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
                if handle:
                    kernel32.TerminateProcess(handle, 0)
                    kernel32.CloseHandle(handle)
                    killed = True
            return killed
        except Exception:
            return False

    def restart_server(self, wait=True):
        """结束 WeaselServer 并**立刻拉起新实例**。

        为什么外观改动非要走这一步：候选窗是宿主进程里长期复用的同一个窗口，
        改配色后旧窗口不一定会自己重绘（客户端 DLL 未同步样式的版本更是如此）。
        让服务重启、宿主重连并重建会话，是唯一 100% 能换掉旧框外观的办法。

        注意不能只杀不拉：TSF 客户端连不上管道会一直 WaitNamedPipe 死等，
        输入法直接失去响应。所以这里杀完必须自己把新实例拉起来并等它就绪。
        """
        self._terminate_servers()
        # 等旧进程真正退出，否则新实例会和它对撞（管道名是单实例的）。
        for _ in range(50):
            if not self._server_pids():
                break
            time.sleep(0.1)
        runtime = self.runtime_dir()
        if not runtime:
            return False
        try:
            subprocess.Popen(
                [os.path.join(runtime, "WeaselServer.exe")], cwd=runtime,
                creationflags=0x00000008)          # DETACHED_PROCESS
        except Exception:
            return False
        if not wait:
            return True
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
            kernel32.WaitNamedPipeW.restype = wintypes.BOOL
            pipe = self.server_pipe()
            for _ in range(80):
                if kernel32.WaitNamedPipeW(pipe, 150):
                    return True
                time.sleep(0.1)
        except Exception:
            pass
        return bool(self._server_pids())

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

        self.nav_list = Navigation(["常用设置", "外观", "词库", "自定义词条",
                                    "自定义词序", "快捷键", "备份与更新", "关于"])
        self.nav_list.setObjectName("navList")
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self.switch_page)
        nav_scroll = QScrollArea()
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_scroll.setWidget(self.nav_list)
        self.nav_scroll = nav_scroll
        self.nav_list.setMinimumHeight(self.nav_list.layout().minimumSize().height())
        nv.addWidget(nav_scroll, 1)

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
        # 以前这里是 objectName("link") —— 主题里 #link 是「透明底、无边框」的
        # 纯文字链接样式，放在灰底面板上看起来就像没上样式。
        # 统一用默认按钮样式（灰底、圆角、36px 高），和其它按钮保持一致。
        setup_button.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self.stack.addWidget(self.page_shadow_order())
        self.stack.addWidget(self.page_hotkey())
        from backup_page import BackupPage
        self.backup_page = BackupPage(self, APP_VER)
        self.stack.addWidget(self.wrap_scroll(self.backup_page))
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

    def closeEvent(self, event):
        if self.backup_page.worker and self.backup_page.worker.isRunning():
            self.backup_page.pending_close = True
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)

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
        self.chk_beep = QCheckBox("四码无候选时提示音")
        self.chk_beep.setAccessibleName("四码没有候选时播放提示音")
        self.chk_beep.setToolTip(
            "打满 4 码却一个候选都没有时响一声，提醒编码打错了；默认开启")
        candidate_layout.addWidget(self.chk_beep)
        self.chk_auto_commit = QCheckBox("四码唯一时自动上屏")
        self.chk_auto_commit.setAccessibleName("四码只剩一个候选时自动上屏")
        self.chk_auto_commit.setToolTip(
            "打满 4 码只剩一个候选时直接上屏，省掉一次空格；默认关闭")
        candidate_layout.addWidget(self.chk_auto_commit)
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
        theme_hint = QLabel("左边是预览；点「应用」后候选窗立即换成新配色，不用重启")
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
            "改完点「应用」，新词条会立刻进入候选。")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addStretch(1)
        return self.wrap_scroll(w)

    # ---- 自定义词条操作 ----
    def load_phrases(self):
        self.phrases = self.cfg.read_phrases()
        # 记下加载时的词条，保存时用来判断「这次改的到底是外观还是词条」。
        self._phrase_snapshot = list(self.phrases)
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

    def page_shadow_order(self):
        """自定义词序 —— 管理候选调序（shadow 层）规则。

        这些规则来自候选框右键「置顶」/ Ctrl+数字，也可以在这里直接删掉。
        改动只写 shadow_<方案>.yaml + 热重载，不碰词库、不部署。
        """
        self.shadow_rules = {}
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(14)
        h = QLabel("自定义词序")
        h.setObjectName("h1")
        lay.addWidget(h)
        s = QLabel("在候选框上右键「置顶」、或按 Ctrl+数字 做的调整都会记录在这里。"
                   "删掉某条规则，该编码就回到词库原本的顺序。")
        s.setObjectName("desc")
        s.setWordWrap(True)
        lay.addWidget(s)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        lbl = QLabel("方案")
        lbl.setObjectName("fieldLabel")
        bar.addWidget(lbl)
        self.combo_shadow = QComboBox()
        for sid, name, _desc in SCHEMAS:
            self.combo_shadow.addItem(name, sid)
        self.combo_shadow.setFixedWidth(190)
        self.combo_shadow.currentIndexChanged.connect(lambda _i: self.load_shadow())
        bar.addWidget(self.combo_shadow)
        bar.addStretch(1)
        lay.addLayout(bar)

        panel = QFrame()
        panel.setObjectName("candidatePanel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(16, 16, 16, 14)
        pl.setSpacing(10)

        self.shadow_table = QTableWidget(0, 3)
        self.shadow_table.setHorizontalHeaderLabels(["编码", "词条", "位次"])
        self.shadow_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed)
        self.shadow_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.shadow_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed)
        self.shadow_table.setColumnWidth(0, 130)
        self.shadow_table.setColumnWidth(2, 70)
        self.shadow_table.verticalHeader().setVisible(False)
        self.shadow_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.shadow_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.shadow_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.shadow_table.setMinimumHeight(280)
        self.shadow_table.setAccessibleName("自定义词序规则列表")
        pl.addWidget(self.shadow_table)

        row = QHBoxLayout()
        row.setSpacing(8)
        b_del = QPushButton("删除选中")
        b_del.setToolTip("只删这一条规则，同编码的其它词条保留")
        b_del.clicked.connect(self.shadow_del)
        b_code = QPushButton("删除该编码")
        b_code.setToolTip("把这个编码下的全部调序规则删掉")
        b_code.clicked.connect(self.shadow_del_code)
        b_refresh = QPushButton("刷新")
        b_refresh.clicked.connect(self.load_shadow)
        b_reset = QPushButton("恢复默认词序")
        b_reset.setObjectName("primary")
        b_reset.setToolTip("清空当前方案的全部调序规则")
        b_reset.clicked.connect(self.shadow_reset)
        for b in (b_del, b_code, b_refresh):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(b_reset)
        pl.addLayout(row)
        lay.addWidget(panel)

        self.shadow_empty = QLabel("当前方案还没有任何调序规则。")
        self.shadow_empty.setObjectName("hint")
        self.shadow_empty.setWordWrap(True)
        lay.addWidget(self.shadow_empty)

        tip = QLabel(
            "提示：调序规则按「编码」独立生效 —— 改 wqiy 不影响其它编码。"
            "规则存放在用户目录的 shadow_<方案>.yaml，删掉整个文件等于全部恢复默认。"
            "这里改完立刻生效，不需要重新部署。")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addStretch(1)
        return self.wrap_scroll(w)

    # ---- 自定义词序操作 ----
    def current_shadow_schema(self):
        sid = self.combo_shadow.currentData() if hasattr(self, "combo_shadow") else None
        return sid or getattr(self, "cur_schema", "wubi86")

    def load_shadow(self):
        self.shadow_rules = self.cfg.read_shadow(self.current_shadow_schema())
        self.refresh_shadow()

    def refresh_shadow(self):
        t = self.shadow_table
        rows = []
        for code, words in self.shadow_rules.items():
            for i, word in enumerate(words):
                rows.append((code, word, i + 1))
        t.setRowCount(len(rows))
        for r, (code, word, pos) in enumerate(rows):
            t.setItem(r, 0, QTableWidgetItem(code))
            t.setItem(r, 1, QTableWidgetItem(word))
            cell = QTableWidgetItem(str(pos))
            cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setItem(r, 2, cell)
        if rows:
            t.selectRow(0)
        if hasattr(self, "shadow_empty"):
            self.shadow_empty.setVisible(not rows)

    def _shadow_save_and_reload(self):
        sid = self.current_shadow_schema()
        if not self.cfg.write_shadow(sid, self.shadow_rules):
            QMessageBox.warning(self, "保存失败",
                                "调序文件写入失败，请检查用户数据目录是否可写。")
            return
        # 热重载：服务端会清掉 shadow 缓存并重读，毫秒级，不部署
        self.cfg.reload()
        self.load_shadow()

    def shadow_del(self):
        row = self.shadow_table.currentRow()
        if row < 0:
            return
        code = self.shadow_table.item(row, 0).text()
        word = self.shadow_table.item(row, 1).text()
        words = self.shadow_rules.get(code, [])
        if word in words:
            words.remove(word)
        if not words:
            self.shadow_rules.pop(code, None)
        self._shadow_save_and_reload()

    def shadow_del_code(self):
        row = self.shadow_table.currentRow()
        if row < 0:
            return
        code = self.shadow_table.item(row, 0).text()
        self.shadow_rules.pop(code, None)
        self._shadow_save_and_reload()

    def shadow_reset(self):
        if not self.shadow_rules:
            QMessageBox.information(self, "已经是默认词序",
                                    "当前方案没有任何调序规则。")
            return
        name = self.combo_shadow.currentText()
        ret = QMessageBox.question(
            self, "恢复默认词序",
            f"确定清空「{name}」的全部调序规则吗？\n"
            "清空后所有编码都回到词库原本的顺序。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        self.shadow_rules = {}
        self._shadow_save_and_reload()

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
            "· 三套方案保留原表顺序，并关闭自动学习和词频调序。\n"
            "  自定义词条和手动词序规则按你设置的顺序优先。\n"
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
        self.nav_scroll.ensureWidgetVisible(self.nav_list.buttons[i], 0, 8)

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
        self.chk_beep.setChecked(self.cfg.no_candidate_beep())
        self.chk_auto_commit.setChecked(self.cfg.auto_commit_unique())
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

        # 自定义词序：默认跟着当前方案走
        idx = self.combo_shadow.findData(self.cur_schema)
        if idx >= 0 and idx != self.combo_shadow.currentIndex():
            self.combo_shadow.blockSignals(True)
            self.combo_shadow.setCurrentIndex(idx)
            self.combo_shadow.blockSignals(False)
        self.load_shadow()

    def save(self, deploy=True):
        before = self.cfg.weasel_style()
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
            self.cfg.set_no_candidate_beep(self.chk_beep.isChecked())
            self.cfg.set_auto_commit_unique(self.chk_auto_commit.isChecked())
            self.cfg.write_weasel({
                "color_scheme": self.combo_scheme.currentData(),
                "font_face": self.combo_font.currentText(),
                "font_point": self.spin_font.value(),
                "horizontal": self.chk_h.isChecked(),
                "inline_preedit": self.chk_i.isChecked(),
                "round_corner": self.spin_round.value(),
            })
            from fixed_order import ensure_fixed_order
            ensure_fixed_order(self.cfg.dir)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return False
        if deploy:
            appearance_changed = self.cfg.weasel_style() != before
            phrases_changed = list(self.phrases) != list(self._phrase_snapshot)
            needs_deploy = self.cfg.appearance_needs_deploy()
            plan = apply_plan(appearance_changed, phrases_changed, needs_deploy)
            if plan == 'restart':
                # 自定义词条是稳定词典，只在方案加载时读进引擎 —— 不重启服务，
                # 新词条不会进候选。这一条是硬性的，跟外观不是一回事。
                dialog = BusyDialog(
                    self, '正在应用词条', '正在重启输入法服务…',
                    '自定义词条是稳定词典，服务重启后才会出现在候选里。')
                dialog.show()
                QApplication.processEvents()
                try:
                    ok = self.cfg.restart_server()
                finally:
                    dialog.finish()
                self._phrase_snapshot = list(self.phrases)
                message = ("词条已保存，输入法服务已重启，新词条会出现在候选里。" if ok else
                           "词条已保存，但服务没能重启；重新切换一次输入法后新词条才生效。")
            elif appearance_changed:
                # 候选窗现在会在每次应答时同步最新样式（WeaselPanel::Refresh 检测到
                # 样式变化就重建布局重绘），热加载即可，不必重启服务、不打断输入。
                dialog = BusyDialog(
                    self, '正在应用外观', '正在刷新候选窗样式…',
                    '配色、字体和圆角会直接应用到已经打开的候选窗，不用重启。')
                dialog.show()
                QApplication.processEvents()
                try:
                    if needs_deploy:
                        self.cfg.deploy(wait=True)
                    ok = self.cfg.reload(wait=True)
                finally:
                    dialog.finish()
                message = ("外观已保存并立即生效，继续打字就能看到新候选窗。" if ok else
                           "外观已保存；输入法服务当前没有运行，下次打字时会自动读取新外观。")
            elif needs_deploy:
                dialog = BusyDialog(self, '正在应用外观', '正在更新候选窗外观…',
                                    '完成后，现有输入会话会重新读取所选配色。')
                dialog.show()
                QApplication.processEvents()
                try:
                    ok = self.cfg.deploy(wait=True)
                finally:
                    dialog.finish()
                message = "配置已保存并立即生效。" if ok else "配置已保存，但部署没有完成。"
            else:
                ok = self.cfg.reload(wait=True)
                message = ("配置已保存并立即生效。" if ok else
                           "配置已保存，但输入法服务当前没有运行；\n"
                           "下次打字时它会自动启动并读取新设置。")
            QMessageBox.information(self, "已应用", message)
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
        dlg = BusyDialog(self, '正在重新部署', '正在把新词条编译进码表…')
        dlg.show()
        QApplication.processEvents()
        try:
            self.cfg.deploy(wait=True)
            self.cfg.restart_server()
        finally:
            dlg.finish()
        self.load()

    def open_userdir(self):
        os.startfile(self.cfg.dir)

    def redeploy(self):
        # 真部署（重新编译码表/词库）是重活，给一个明确的等待窗口，
        # 免得界面白屏、系统标"无响应"被当成卡死。
        dlg = BusyDialog(self, '正在重新部署', '正在重新编译码表与词库…')
        dlg.show()
        QApplication.processEvents()
        try:
            ok = self.cfg.deploy(wait=True)
            restarted = self.cfg.restart_server() if ok else False
        finally:
            dlg.finish()
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
