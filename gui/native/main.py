# -*- coding: utf-8 -*-
"""原生设置中心入口。"""
import ctypes
import sys

from . import w32, ui
from . import app as app_module

ERROR_ALREADY_EXISTS = 183


def shoot(window, directory):
    """自检模式：逐页截图后退出。"""
    import os
    import time
    from . import shot
    os.makedirs(directory, exist_ok=True)
    names = ["01-common", "02-appearance", "03-dict", "04-phrases",
             "05-shadow", "06-hotkey", "07-backup", "08-about"]
    for index, name in enumerate(names):
        window.switch(index)
        for _ in range(8):
            w32.user32.UpdateWindow(window.hwnd)
            app_module.pump()
            time.sleep(0.02)
        size = shot.capture(window.hwnd, os.path.join(directory, name + ".png"))
        print("shot", name, size)
    w32.user32.DestroyWindow(window.hwnd)
    return 0


def main():
    if "--check-update" in sys.argv:
        from native_startup import background_update
        return background_update()
    w32.set_dpi_aware()
    w32.init_common_controls()
    ui.SCALE = w32.dpi_scale()

    name = "QingshiWizardNative" if "--wizard" in sys.argv else "QingshiSettingsNative"
    mutex = w32.kernel32.CreateMutexW(None, False, name)
    if w32.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        hwnd = w32.user32.FindWindowW("QSApp", None)
        if hwnd:
            w32.user32.ShowWindow(hwnd, w32.SW_SHOWNORMAL)
            w32.user32.SetForegroundWindow(hwnd)
        return 0

    from rime_config import RimeConfig
    window = app_module.App(RimeConfig())
    w32.user32.ShowWindow(window.hwnd, w32.SW_SHOWNORMAL)
    w32.user32.SetForegroundWindow(window.hwnd)

    if "--shot" in sys.argv:
        return shoot(window, sys.argv[sys.argv.index("--shot") + 1])

    if "--wizard" in sys.argv:
        from .wizard import open_wizard
        open_wizard(window, window.cfg)
        w32.user32.DestroyWindow(window.hwnd)
        return 0

    msg = w32.MSG()
    while True:
        ret = w32.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if ret <= 0:
            break
        w32.user32.TranslateMessage(ctypes.byref(msg))
        w32.user32.DispatchMessageW(ctypes.byref(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
