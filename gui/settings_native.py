# -*- coding: utf-8 -*-
"""设置中心（Win32 原生版）启动入口。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from native.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
