# -*- coding: utf-8 -*-
"""把三套码表转成 Rime dict.yaml，用 sort: original 保持原版顺序"""
import io, os, re
from pathlib import Path

BASE = str(Path(__file__).resolve().parent / "sources")
OUT = str(Path(__file__).resolve().parent / "pkg")
os.makedirs(OUT, exist_ok=True)

HEADER = """# Rime dictionary: {name}
# 由极点/五笔原版码表转换，保持原始顺序（sort: original）
# 生成时间: 2026-10-26
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
    """rows: [(word, code)] 保持顺序"""
    seen = set()
    lines = []
    for w, c in rows:
        key = (c, w)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{w}\t{c}\t0")
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER.format(name=name))
        f.write("\n".join(lines))
        f.write("\n")
    print(f"  -> {os.path.basename(path)}  {len(lines):,} 条  {os.path.getsize(path):,}B")
    return len(lines)

# ---------- 86：极点官方原版 ----------
def load_jidian(path):
    rows = []
    code_re = re.compile(r"^([a-z]{1,5})\s+(.+)$")
    for line in io.open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if not line or line.startswith("["):
            continue
        m = code_re.match(line)
        if not m:
            continue
        code, rest = m.group(1), m.group(2)
        for w in rest.split():
            w = w.lstrip("~^!")
            if w:
                rows.append((w, code))
    return rows

# ---------- 98 / 06：已是 rime 格式，按物理顺序重排 ----------
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

print("生成 Rime 词典：")
n86 = write_dict("wubi86", load_jidian(os.path.join(BASE, "wubi86", "jidian_2011.txt")),
                 os.path.join(OUT, "wubi86.dict.yaml"))
n98 = write_dict("wubi98", load_rime(os.path.join(BASE, "wubi_other", "wubi98.dict.yaml")),
                 os.path.join(OUT, "wubi98.dict.yaml"))
n06 = write_dict("wubi06", load_rime(os.path.join(BASE, "wubi_other", "wubi06.dict.yaml")),
                 os.path.join(OUT, "wubi06.dict.yaml"))

# 抽查顺序
print("\n=== 抽查（保序验证）===")
import collections
for f, name in [(os.path.join(OUT, "wubi86.dict.yaml"), "86")]:
    g = collections.defaultdict(list)
    started = False
    for line in io.open(f, encoding="utf-8"):
        if line.strip() == "...":
            started = True; continue
        if not started or not line.strip(): continue
        p = line.split("\t")
        if len(p) >= 2:
            g[p[1]].append(p[0])
    for code in ("fcu", "fjfc", "a", "g", "dddd"):
        print(f"  {name} {code}: {g[code][:5]}")
