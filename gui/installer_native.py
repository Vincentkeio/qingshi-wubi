# -*- coding: utf-8 -*-
"""安装包入口（原生 Win32）：安装 / 卸载 / 后台 worker 三合一。"""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def detached_uninstaller(action="--uninstall"):
    """把自己复制到临时目录再运行，这样 Program Files 里的 exe 才能被删掉。"""
    temporary = Path(tempfile.mkdtemp(prefix="qingshi-uninstall-"))
    executable = temporary / "QingshiRemove.exe"
    shutil.copy2(sys.executable, executable)
    helper = Path(__file__).with_name("cleanup.ps1")
    if helper.is_file():
        shutil.copy2(helper, temporary / "cleanup.ps1")
    environment = os.environ.copy()
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    process = subprocess.Popen([str(executable), action, "--detached"], env=environment)
    cleanup = temporary / "cleanup.ps1"
    if cleanup.is_file():
        subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                          "-File", str(cleanup), "-WaitProcessId", str(process.pid),
                          "-TargetDirectory", str(temporary)],
                         creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)


def main():
    from native import w32, ui

    argv = sys.argv
    frozen = getattr(sys, "frozen", False)

    if "--worker" in argv:
        from installer_backend import run_worker
        return run_worker(argv[argv.index("--worker") + 1])

    if "--check-update" in argv:
        from native_startup import background_update
        return background_update()

    if "--settings" in argv or "--wizard" in argv or (
            frozen and Path(sys.executable).stem.lower() == "qingshi"
            and not any(flag in argv for flag in ("--setup", "--uninstall", "--preview"))):
        from native_startup import open_installed_settings
        return open_installed_settings("--wizard" in argv)

    uninstall = "--uninstall" in argv
    preview = "--preview" in argv

    if frozen and uninstall and "--detached" not in argv and not preview:
        detached_uninstaller("--uninstall")
        return 0

    w32.set_dpi_aware()
    w32.init_common_controls()
    ui.SCALE = w32.dpi_scale()

    from native.installer import InstallerWindow
    app = InstallerWindow(uninstall, preview)
    w32.user32.ShowWindow(app.hwnd, w32.SW_SHOWNORMAL)
    w32.user32.SetForegroundWindow(app.hwnd)

    msg = w32.MSG()
    while True:
        result = w32.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if result <= 0:
            break
        w32.user32.TranslateMessage(ctypes.byref(msg))
        w32.user32.DispatchMessageW(ctypes.byref(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
