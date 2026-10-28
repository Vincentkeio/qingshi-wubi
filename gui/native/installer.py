# -*- coding: utf-8 -*-
"""安装 / 卸载界面（原生 Win32 实现，不依赖 Qt）。

后台安装动作仍由 installer_backend 的 worker 完成，这里只负责界面与进度轮询：
worker 每完成一步就把 {percent, message, finished, ...} 写进 status.json，
本界面用定时器读这个文件。
"""
import ctypes
import ctypes.wintypes as wt
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import ui, w32
from .ui import Panel, Label, Button, Check

from installer_backend import Installer, VERSION, atomic_json, read_json

user32 = w32.user32
kernel32 = w32.kernel32

W_DESIGN = 680
H_DESIGN = 590


class ProgressBar(Panel):
    def __init__(self, parent, rect):
        super().__init__(parent, rect, bg=ui.BG_APP)
        self.value = 0

    def set_value(self, value):
        self.value = max(0, min(100, int(value)))
        self.invalidate()

    def paint(self, g, width, height):
        ui.w32.round_fill(g, (0, 0, width, height), ui.s(3), 0xE2E2E2)
        right = int(width * self.value / 100)
        if right > 0:
            ui.w32.round_fill(g, (0, 0, right, height), ui.s(3), 0x202020)


class InstallerWindow(Panel):
    cls = "QSInstaller"
    popup = True

    def __init__(self, uninstall=False, preview=False):
        self.children = []
        self.bg = ui.BG_APP
        self.scroll = False
        self.offset = 0
        self.content_h = 0
        self.combo_item_h = 26
        self._brush = None
        self.uninstalling = uninstall
        self.preview = preview
        self.busy = False
        self.process_handle = None
        self.request_dir = None
        self.result = None
        ui.register_class("QSInstaller")
        title = "青石五笔 · " + ("卸载" if uninstall else "安装")
        ui.Widget.__init__(self, None, title, (0, 0, W_DESIGN, H_DESIGN),
                           style=w32.WS_POPUP | w32.WS_CAPTION | w32.WS_SYSMENU |
                           w32.WS_CLIPCHILDREN)
        style = w32.WS_POPUP | w32.WS_CAPTION | w32.WS_SYSMENU | w32.WS_CLIPCHILDREN
        window_w, window_h = ui.client_window_size(W_DESIGN, H_DESIGN, style)
        user32.SetWindowPos(self.hwnd, None, 0, 0, window_w, window_h,
                            w32.SWP_NOZORDER | w32.SWP_NOACTIVATE)
        self.brand = "青石五笔输入法"
        self.version = "v" + VERSION

        self.heading = Label(self, "卸载青石五笔" if uninstall else "开始使用青石五笔",
                             (40, 104, 600, 34), px=23, weight=w32.FW_SEMIBOLD,
                             color=ui.TEXT_STRONG)
        self.description = Label(
            self,
            "移除输入法、后台服务与程序文件。" if uninstall
            else "安装五笔 86、五笔 98 与新世纪五笔，保留原版码表词序。",
            (40, 142, 600, 44), px=12, color=ui.MUTED, multiline=True)
        if uninstall:
            detail_text = ("将清理\n\n输入法注册与语言列表\n开机启动、开始菜单和旧版青石程序\n"
                           "被占用的输入法文件将在重启后删除")
        else:
            installer = Installer()
            detail_text = ("Windows 10 / 11 · x64\n当前构建适用于 64 位应用\n\n"
                           f"程序位置\n{installer.root}\n\n用户设置\n{installer.data}")
        self.details = Label(self, detail_text, (40, 196, 600, 150), px=12,
                             color=ui.MUTED, multiline=True)
        self.clear_data = Check(self, "同时删除设置、自定义词条与用户词库",
                                (40, 356, 460, 24),
                                on_change=lambda checked: self.btn_start.set_text(
                                    "完整卸载" if checked else "卸载并保留数据"))
        self.clear_data.set_checked(True)
        self.notice = Label(
            self,
            "完整卸载会删除上述用户数据，无法恢复。其他 Rime 方案的数据会保留。" if uninstall
            else "安装需要管理员权限；检测到旧版青石时会迁移已有设置。",
            (40, 390, 600, 40), px=11, color=ui.MUTED, multiline=True)
        self.progress_label = Label(self, "", (40, 424, 600, 40), px=12, color=ui.MUTED,
                                    multiline=True)
        self.progress = ProgressBar(self, (40, 472, 600, 6))

        self.btn_cancel = Button(self, "取消", (0, 0, 90, 38), kind="ghost", on_click=self.close)
        self.btn_wizard = Button(self, "打开设置向导", (0, 0, 130, 38), on_click=self.open_wizard)
        self.btn_start = Button(self, "完整卸载" if uninstall else "安装", (0, 0, 114, 38),
                                kind="primary", on_click=self.begin)
        self.layout_all()
        self.set_state("idle")

    # ---- 布局 ----
    def layout_all(self):
        rect = w32.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rect))
        height = int(rect.bottom / (ui.SCALE or 1))
        y = height - 58
        y = height - 28 - 36
        self.btn_start.move(W_DESIGN - 40 - 114, y, 114, 36)
        self.btn_wizard.move(W_DESIGN - 40 - 114 - 10 - 130, y, 130, 36)
        cancel_x = W_DESIGN - 40 - 114 - 10 - 90
        self.btn_cancel.move(cancel_x, y, 90, 36)

    def set_state(self, state):
        self.state = state
        self.clear_data.show(state == "idle" and self.uninstalling)
        self.progress_label.show(state != "idle")
        self.progress.show(state != "idle")
        self.btn_wizard.show(state == "done" and not self.uninstalling)
        self.btn_cancel.show(state != "done")
        if state == "idle":
            self.progress.set_value(0)

    # ---- 动作 ----
    def begin(self):
        if self.result and self.result.get("ok"):
            self.close()
            return
        if self.preview:
            self.show_progress(48, "预览：正在移除输入法注册" if self.uninstalling
                               else "预览：正在注册输入法")
            return
        if not getattr(sys, "frozen", False):
            ui.message(self, "请运行打包后的 QingshiSetup.exe 完成安装或卸载。", "请使用安装包")
            return
        if self.uninstalling:
            text = ("将删除程序、设置和自定义词条。确认完整卸载？" if self.clear_data.is_checked()
                    else "将移除程序，保留设置与词条。确认卸载？")
            if not ui.confirm(self, text, "卸载青石五笔"):
                return
        self.request_dir = Path(tempfile.mkdtemp(prefix="qingshi-operation-"))
        request_file = self.request_dir / "request.json"
        atomic_json(request_file, {"action": "uninstall" if self.uninstalling else "install",
                                   "clear_data": self.clear_data.is_checked(),
                                   "profile": str(Path.home()),
                                   "executable": sys.executable})
        try:
            self.process_handle = elevate_worker(sys.executable, request_file)
        except OSError as error:
            self.progress_label.show()
            self.progress_label.set_text("管理员授权已取消，可以重试。" if error.winerror == 1223
                                         else f"无法开始操作：{error}")
            self.clean_request()
            return
        self.busy = True
        self.btn_start.enable(False)
        self.btn_cancel.enable(False)
        self.clear_data.enable(False)
        self.show_progress(0, "正在准备卸载" if self.uninstalling else "正在准备安装")
        user32.SetTimer(self.hwnd, 1, 300, None)

    def show_progress(self, value, message):
        self.progress_label.show()
        self.progress.show()
        self.progress.set_value(value)
        self.progress_label.set_text(message)

    def poll(self):
        status = read_json(self.request_dir / "status.json") if self.request_dir else {}
        if status.get("finished"):
            if worker_active(self.process_handle):
                return
            self.finish(status)
        elif not worker_active(self.process_handle):
            self.finish({"ok": False, "error": "操作进程意外退出。请重试；卸载入口会继续保留以便清理。"})
        elif status:
            self.show_progress(status.get("percent", 0), status.get("message", "正在处理"))

    def finish(self, status):
        user32.KillTimer(self.hwnd, 1)
        self.busy = False
        self.result = status
        self.btn_cancel.enable(True)
        self.btn_start.enable(True)
        self.clear_data.enable(True)
        if self.process_handle:
            kernel32.CloseHandle(wt.HANDLE(self.process_handle))
            self.process_handle = None
        if status.get("ok"):
            reboot = status.get("reboot", False)
            leftover = len(status.get("leftover") or [])
            self.heading.set_text("卸载完成" if self.uninstalling else "安装完成")
            if self.uninstalling and leftover:
                self.description.set_text(
                    f"输入法已从系统移除。有 {leftover} 个文件仍被占用未能删除，"
                    "重启后再卸载一次即可清理干净。")
            elif self.uninstalling:
                self.description.set_text(
                    "输入法已从系统移除。部分正在使用的文件会在下次重启时清理；现在可以继续使用电脑。"
                    if reboot else "输入法与程序文件已移除。")
            else:
                self.description.set_text("三套码表已就绪。可从开始菜单打开青石五笔设置。")
            self.details.set_text(
                "用户设置与词条已删除。" if self.uninstalling and status.get("data_removed")
                else ("设置与词条已保留，下次安装可继续使用。" if self.uninstalling
                      else "使用 Win + 空格切换到青石五笔。"))
            self.notice.set_text("其他 Rime 方案的数据已保留。" if self.uninstalling
                                 else "可在设置向导中选择默认方案与候选窗显示。")
            self.show_progress(100, "卸载已完成 · 占用文件将在下次重启时清理" if reboot else "已完成")
            self.btn_start.set_text("稍后重启" if reboot else "完成")
            self.set_state("done")
            if not self.uninstalling:
                self.btn_wizard.show(True)
                if not self.preview and status.get("runtime"):
                    subprocess.Popen([str(Path(status["runtime"]) / "WeaselServer.exe")],
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            self.heading.set_text("卸载未完成" if self.uninstalling else "安装未完成")
            self.show_progress(self.progress.value, status.get("error", "请重试"))
            self.btn_start.set_text("重试")
        for label in (self.heading, self.description, self.details, self.notice):
            label.invalidate()
        self.invalidate()
        self.clean_request()

    def open_wizard(self):
        if not self.preview:
            runtime = Installer().managed().get("runtime")
            if runtime:
                environment = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
                subprocess.Popen([str(Path(runtime) / "settings/QingshiSettings.exe"), "--wizard"],
                                 env=environment)

    def clean_request(self):
        if self.request_dir:
            shutil.rmtree(self.request_dir, ignore_errors=True)
            self.request_dir = None

    def close(self):
        if self.busy:
            return
        self.clean_request()
        user32.DestroyWindow(self.hwnd)

    # ---- 窗口消息 ----
    def on_message(self, msg, wparam, lparam):
        if msg == w32.WM_TIMER:
            self.poll()
            return 0
        if msg == w32.WM_CLOSE:
            self.close()
            return 0
        if msg == w32.WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return super().on_message(msg, wparam, lparam)

    def paint(self, g, width, height):
        ui.brand_mark(g, 40, 32, 36)
        ui.w32.text(g, self.brand, (ui.s(86), ui.s(32), ui.s(420), ui.s(68)),
                    ui.FONTS.get(16, w32.FW_SEMIBOLD), ui.TEXT_STRONG)
        ui.w32.text(g, self.version, (width - ui.s(120), ui.s(38), width - ui.s(40), ui.s(58)),
                    ui.FONTS.get(12), ui.MUTED, w32.DT_RIGHT | w32.DT_VCENTER | w32.DT_SINGLELINE)


def elevate_worker(executable, request):
    class ShellInfo(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("fMask", wt.ULONG), ("hwnd", wt.HWND),
                    ("lpVerb", wt.LPCWSTR), ("lpFile", wt.LPCWSTR), ("lpParameters", wt.LPCWSTR),
                    ("lpDirectory", wt.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wt.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wt.LPCWSTR), ("hkeyClass", wt.HKEY),
                    ("dwHotKey", wt.DWORD), ("hIcon", wt.HANDLE), ("hProcess", wt.HANDLE)]
    info = ShellInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100
    info.lpVerb = "runas"
    info.lpFile = str(executable)
    info.lpParameters = subprocess.list2cmdline(["--worker", str(request)])
    info.nShow = 0
    function = ctypes.WinDLL("shell32", use_last_error=True).ShellExecuteExW
    function.argtypes = [ctypes.POINTER(ShellInfo)]
    function.restype = wt.BOOL
    previous = os.environ.get("PYINSTALLER_RESET_ENVIRONMENT")
    os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    try:
        if not function(ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if previous is None:
            os.environ.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
        else:
            os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = previous
    return info.hProcess


def worker_active(handle):
    if not handle:
        return False
    function = kernel32.GetExitCodeProcess
    function.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    code = wt.DWORD()
    if not function(wt.HANDLE(handle), ctypes.byref(code)):
        return False
    return code.value == 259
