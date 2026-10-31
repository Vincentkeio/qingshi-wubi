# -*- coding: utf-8 -*-
"""青石五笔配置层：只读写 Rime / Weasel 的配置文件与注册表，不依赖任何 GUI 框架。

设置中心（Qt 版与原生版）都从这里取逻辑，保证两边行为一致。
"""
import os
import sys
import shutil
import subprocess
import datetime
import time

try:
    import yaml
except ImportError:
    yaml = None

APP_NAME = "青石五笔输入法"
APP_VER = "2.0.1"
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
        updates = {}
        for key, idx in self.SWITCH_INDEX.items():
            updates[f"switches/@{idx}/reset"] = 1 if values.get(key) else 0
        commit = bool(values.get("shift_commit", True))
        toggle = bool(values.get("shift_toggle", True))
        # Rime 的 commit_code 本身就会连带切换中英模式（内核行为），
        # 所以「只上屏不切换」没有对应取值，勾了上屏就按 commit_code 处理。
        if commit and toggle:
            style = "commit_code"
        elif toggle:
            style = "inline_ascii"
        else:
            style = "noop"
        updates['ascii_composer/switch_key/Shift_L'] = style
        updates['ascii_composer/switch_key/Shift_R'] = style
        for key in ('enable_user_dict','enable_sentence','enable_encoder','encode_commit_history'):
            updates['translator/' + key] = False
        self.merge_patch(f'{sid}.custom.yaml', updates)

    def merge_patch(self, name, updates):
        from pathlib import Path
        from fixed_order import atomic_write
        path = Path(self.path(name))
        content = yaml.safe_load(path.read_text(encoding='utf-8')) if path.is_file() else {}
        content = content or {}
        if not isinstance(content, dict) or not isinstance(content.get('patch', {}), dict):
            raise ValueError(name + '不是有效的配置文件')
        content.setdefault('patch', {}).update(updates)
        atomic_write(path, yaml.safe_dump(content, allow_unicode=True, sort_keys=False).encode('utf-8'))

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

    def symbols_direct(self):
        patch = self.read_yaml('wubi86.custom.yaml').get('patch') or {}
        return patch.get('punctuator/import_preset', 'symbols_direct') != 'symbols'

    def set_symbols_direct(self, enabled):
        preset = 'symbols_direct' if enabled else 'symbols'
        for sid, _, _ in SCHEMAS:
            self.merge_patch(sid + '.custom.yaml', {'punctuator/import_preset': preset})

    def symbols_need_deploy(self, enabled):
        expected = 'symbols_direct' if enabled else 'symbols'
        for sid, _, _ in SCHEMAS:
            schema = self.read_yaml('build/' + sid + '.schema.yaml')
            if (schema.get('punctuator') or {}).get('import_preset') != expected:
                return True
        return False

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
        order = [schema_id] + [sid for sid, _, _ in SCHEMAS if sid != schema_id]
        menu = dict((self.read_yaml('default.custom.yaml').get('patch') or {}).get('menu') or {})
        menu['page_size'] = page_size
        self.merge_patch('default.custom.yaml', {'schema_list':[{'schema':sid} for sid in order], 'menu':menu})

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
                proc = subprocess.Popen([exe, "/reload"], creationflags=subprocess.CREATE_NO_WINDOW)
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
                proc = subprocess.Popen([exe, "/deploy"], creationflags=subprocess.CREATE_NO_WINDOW)
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


