# -*- coding: utf-8 -*-
"""重新生成三套 Rime 词典（过滤非法编码）+ 生成三套 schema"""
import io, os, re
from pathlib import Path

BASE = str(Path(__file__).resolve().parent / "sources")
OUT = str(Path(__file__).resolve().parent / "pkg")
os.makedirs(OUT, exist_ok=True)

CODE_RE = re.compile(r"^[a-y]{1,4}$")   # 五笔只用 a-y，1-4 码；z 是学习键

DICT_HEADER = """# Rime dictionary: {name}
# 由极点/五笔原版码表转换，sort: original 保持原始顺序
---
name: {name}
version: "1.0"
sort: original
use_preset_vocabulary: false
columns:
  - text
  - code
  - weight
encoder:
  exclude_patterns:
    - '^z.*$'
  rules:
    - length_equal: 2
      formula: "AaAbBaBb"
    - length_equal: 3
      formula: "AaBaCaCb"
    - length_in_range: [4, 10]
      formula: "AaBaCaZa"
...
"""

def write_dict(name, rows, path):
    seen = set()
    lines = []
    dropped = 0
    for w, c in rows:
        if not CODE_RE.match(c):
            dropped += 1
            continue
        key = (c, w)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{w}\t{c}\t0")
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(DICT_HEADER.format(name=name))
        f.write("\n".join(lines) + "\n")
    print(f"  {name}: {len(lines):,} 条（丢弃非法编码 {dropped}）")
    return len(lines)

def load_jidian(path):
    rows = []
    r = re.compile(r"^([a-z]{1,5})\s+(.+)$")
    for line in io.open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if not line or line.startswith("["):
            continue
        m = r.match(line)
        if not m:
            continue
        for w in m.group(2).split():
            w = w.lstrip("~^!")
            if w:
                rows.append((w, m.group(1)))
    return rows

def load_rime(path):
    rows = []
    started = False
    for line in io.open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if line.strip() == "...":
            started = True
            continue
        if not started or not line.strip() or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) >= 2 and p[0] and p[1]:
            rows.append((p[0], p[1]))
    return rows

print("生成词典：")
write_dict("wubi86", load_jidian(os.path.join(BASE, "wubi86", "jidian_2011.txt")),
           os.path.join(OUT, "wubi86.dict.yaml"))
write_dict("wubi98", load_rime(os.path.join(BASE, "wubi_other", "wubi98.dict.yaml")),
           os.path.join(OUT, "wubi98.dict.yaml"))
write_dict("wubi06", load_rime(os.path.join(BASE, "wubi_other", "wubi06.dict.yaml")),
           os.path.join(OUT, "wubi06.dict.yaml"))

# ---------------- schema ----------------
SCHEMA = """# Rime schema: {sid}
# 五笔字型{label}，纯码表模式（不造句、不自动造词，严格保持码表顺序）
schema:
  schema_id: {sid}
  name: "{label}"
  version: "1.0"
  author:
    - 發明人 王永民先生
  description: |
    五笔字型{label}
    码表：{src}
    纯码表模式：enable_sentence=false, enable_encoder=false

switches:
  - name: ascii_mode
    reset: 0
    states: [ 中文, 西文 ]
  - name: full_shape
    states: [ 半角, 全角 ]
  - name: extended_charset
    reset: 0
    states: [ 常用, 增廣 ]

engine:
  processors:
    - ascii_composer
    - recognizer
    - key_binder
    - speller
    - punctuator
    - selector
    - navigator
    - express_editor
  segmentors:
    - ascii_segmentor
    - matcher
    - abc_segmentor
    - punct_segmentor
    - fallback_segmentor
  translators:
    - punct_translator
    - table_translator

speller:
  alphabet: zyxwvutsrqponmlkjihgfedcba
  delimiter: " ;'"
  max_code_length: 4

translator:
  dictionary: {sid}
  enable_charset_filter: true
  enable_sentence: false
  enable_encoder: false
  encode_commit_history: false
  max_phrase_length: 4
  disable_user_dict_for_patterns:
    - "^z.*$"

punctuator:
  import_preset: symbols

key_binder:
  import_preset: default

recognizer:
  import_preset: default
  patterns:
    punct: '^/([0-9]0?|[A-Za-z]+)$'
"""

specs = [
    ("wubi86", "五笔86", "极点官方原版（极爽4.3 for 极点Unicode，2011）"),
    ("wubi98", "五笔98", "98版原表"),
    ("wubi06", "新世纪五笔", "新世纪版原表"),
]
for sid, label, src in specs:
    p = os.path.join(OUT, f"{sid}.schema.yaml")
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(SCHEMA.format(sid=sid, label=label, src=src))
    print(f"  -> {sid}.schema.yaml")

# ---------------- 方案列表 ----------------
defcustom = """# 五笔三版本方案切换
patch:
  schema_list:
    - schema: wubi86
    - schema: wubi98
    - schema: wubi06
  menu:
    page_size: 9
"""
p = os.path.join(OUT, "default.custom.yaml")
with io.open(p, "w", encoding="utf-8", newline="\n") as f:
    f.write(defcustom)
print("  -> default.custom.yaml")

# ---------------- 候选窗主题 ----------------
weasel = """# 青石五笔蓝白候选窗
patch:
  "style/color_scheme": qingshi_blue
  "style/font_face": "Microsoft YaHei"
  "style/font_point": 13
  "style/horizontal": true
  "style/inline_preedit": true
  "style/layout/border": 1
  "style/layout/round_corner": 6
  "style/layout/shadow_radius": 8
  "style/layout/margin_x": 10
  "style/layout/margin_y": 8
  "style/layout/spacing": 10
  "style/layout/candidate_spacing": 12
  "style/layout/hilite_padding": 4
  "style/layout/hilite_spacing": 6
  "preset_color_schemes/qingshi_blue":
    name: "青石蓝白"
    author: "Qingshi Wubi"
    back_color: 0xFFFFFF
    border_color: 0xDCE5F1
    text_color: 0x263750
    hilited_text_color: 0x17243A
    hilited_back_color: 0xFFFFFF
    hilited_candidate_text_color: 0xFFFFFF
    hilited_candidate_back_color: 0x2868D7
    candidate_text_color: 0x263750
    comment_text_color: 0x718198
  "preset_color_schemes/qingshi_light":
    name: "清透浅色"
    author: "weasel-custom"
    back_color: 0xFFFFFF
    border_color: 0xE0E2E6
    text_color: 0x333333
    hilited_text_color: 0x333333
    hilited_back_color: 0xFFFFFF
    hilited_candidate_text_color: 0xFFFFFF
    hilited_candidate_back_color: 0x2F7CF6
    candidate_text_color: 0x333333
    comment_text_color: 0x9AA0A8
"""
p = os.path.join(OUT, "weasel.custom.yaml")
with io.open(p, "w", encoding="utf-8", newline="\n") as f:
    f.write(weasel)
print("  -> weasel.custom.yaml")

# ---------------- 验证 ----------------
print("\n=== 保序验证 ===")
import collections
g = collections.defaultdict(list)
started = False
for line in io.open(os.path.join(OUT, "wubi86.dict.yaml"), encoding="utf-8"):
    if line.strip() == "...":
        started = True; continue
    if not started or not line.strip(): continue
    p = line.split("\t")
    if len(p) >= 2:
        g[p[1]].append(p[0])
for code in ("fcu", "fjfc", "a", "g", "dddd", "s", "wwww"):
    print(f"  {code}: {g[code][:6]}")
