"""与设置中心共用视觉语言的安装和卸载界面。"""
from pathlib import Path
import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
import tempfile

from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QCheckBox, QProgressBar, QMessageBox)
from installer_backend import Installer, APP_ID, VERSION, atomic_json, read_json


class InstallerWindow(QWidget):
    def __init__(self, uninstall=False, preview=False):
        super().__init__()
        self.uninstalling = uninstall
        self.preview = preview
        self.busy = False
        self.process_handle = None
        self.request_dir = None
        self.result = None
        self.setWindowTitle('青石五笔 · ' + ('卸载' if uninstall else '安装'))
        self.setObjectName('root')
        self.resize(680, 590)
        self.setMinimumSize(640, 560)
        icon = QIcon(str(Path(__file__).with_name('qingshi-mark.png')))
        self.setWindowIcon(icon)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 28)
        layout.setSpacing(16)
        brand_row = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icon.pixmap(QSize(36, 36)))
        brand_row.addWidget(mark)
        brand = QLabel('青石五笔输入法')
        brand.setObjectName('brandTitle')
        brand_row.addWidget(brand)
        brand_row.addStretch()
        version = QLabel('v' + VERSION)
        version.setObjectName('muted')
        brand_row.addWidget(version)
        layout.addLayout(brand_row)
        layout.addSpacing(18)
        self.heading = QLabel('卸载青石五笔' if uninstall else '开始使用青石五笔')
        self.heading.setObjectName('wizardTitle')
        layout.addWidget(self.heading)
        self.description = QLabel(
            '移除输入法、后台服务与程序文件。' if uninstall else
            '安装五笔 86、五笔 98 与新世纪五笔，保留原版码表词序。')
        self.description.setObjectName('wizardText')
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setObjectName('wizardText')
        if uninstall:
            self.details.setText('将清理\n\n输入法注册与语言列表\n开机启动、开始菜单和旧版青石程序\n被占用的输入法文件将在重启后删除')
        else:
            self.details.setText('Windows 10 / 11 · x64\n当前构建适用于 64 位应用\n\n程序位置\n' + str(Installer().root) + '\n\n用户设置\n' + str(Installer().data))
        layout.addWidget(self.details)
        self.clear_data = QCheckBox('同时删除设置、自定义词条与用户词库')
        self.clear_data.setChecked(True)
        self.clear_data.setVisible(uninstall)
        layout.addWidget(self.clear_data)
        self.notice = QLabel('完整卸载会删除上述用户数据，无法恢复。其他 Rime 方案的数据会保留。' if uninstall
                            else '安装需要管理员权限；检测到旧版青石时会迁移已有设置。')
        self.notice.setObjectName('hint')
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        layout.addStretch(1)
        self.progress_label = QLabel('')
        self.progress_label.setObjectName('hint')
        self.progress_label.setWordWrap(True)
        self.progress_label.setAccessibleName('安装进度')
        self.progress_label.hide()
        layout.addWidget(self.progress_label)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel = QPushButton('取消')
        self.cancel.setObjectName('ghost')
        self.cancel.clicked.connect(self.close)
        self.start = QPushButton('完整卸载' if uninstall else '安装')
        self.start.setObjectName('primary')
        self.start.setMinimumWidth(114)
        self.start.clicked.connect(self.begin)
        self.configure = QPushButton('打开设置向导')
        self.configure.clicked.connect(self.open_wizard)
        self.configure.hide()
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.configure)
        buttons.addWidget(self.start)
        layout.addLayout(buttons)
        self.clear_data.toggled.connect(lambda checked: self.start.setText('完整卸载' if checked else '卸载并保留数据'))
        self.timer = QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.poll)

    def begin(self):
        if self.result and self.result.get('ok'):
            self.close()
            return
        if self.preview:
            self.show_progress(48, '预览：正在移除输入法注册' if self.uninstalling else '预览：正在注册输入法')
            return
        if not getattr(sys, 'frozen', False):
            QMessageBox.information(self, '请使用安装包', '请运行打包后的 QingshiSetup.exe 完成安装或卸载。')
            return
        if self.uninstalling:
            message = ('将删除程序、设置和自定义词条。确认完整卸载？' if self.clear_data.isChecked()
                       else '将移除程序，保留设置与词条。确认卸载？')
            if QMessageBox.question(self, '卸载青石五笔', message,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        self.request_dir = Path(tempfile.mkdtemp(prefix='qingshi-operation-'))
        request_file = self.request_dir / 'request.json'
        atomic_json(request_file, {'action': 'uninstall' if self.uninstalling else 'install',
                    'clear_data': self.clear_data.isChecked(), 'profile': str(Path.home()), 'executable': sys.executable})
        try:
            self.process_handle = elevate_worker(sys.executable, request_file)
        except OSError as exc:
            self.progress_label.show()
            self.progress_label.setText('管理员授权已取消，可以重试。' if exc.winerror == 1223 else f'无法开始操作：{exc}')
            self.clean_request()
            return
        self.busy = True
        self.start.setEnabled(False)
        self.cancel.setEnabled(False)
        self.clear_data.setEnabled(False)
        self.show_progress(0, '正在准备卸载' if self.uninstalling else '正在准备安装')
        self.timer.start()

    def show_progress(self, value, message):
        self.progress_label.show()
        self.progress.show()
        self.progress.setValue(value)
        self.progress_label.setText(message)

    def poll(self):
        status = read_json(self.request_dir / 'status.json')
        if status.get('finished'):
            # Wait for the worker to finish before deleting its temporary request directory.
            if worker_active(self.process_handle):
                return
            self.finish(status)
        elif not worker_active(self.process_handle):
            self.finish({'ok': False, 'error': '操作进程意外退出。请重试；卸载入口会继续保留以便清理。'})
        elif status:
            self.show_progress(status.get('percent', 0), status.get('message', '正在处理'))

    def finish(self, status):
        self.timer.stop()
        self.busy = False
        self.result = status
        self.cancel.setEnabled(True)
        self.start.setEnabled(True)
        self.clear_data.setEnabled(True)
        if self.process_handle:
            close = ctypes.windll.kernel32.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close(self.process_handle)
            self.process_handle = None
        if status.get('ok'):
            reboot = status.get('reboot', False)
            leftover = len(status.get('leftover') or [])
            self.heading.setText('卸载完成' if self.uninstalling else '安装完成')
            if self.uninstalling and leftover:
                self.description.setText(
                    f'输入法已从系统移除。有 {leftover} 个文件仍被占用未能删除，重启后再卸载一次即可清理干净。')
            elif self.uninstalling:
                self.description.setText('输入法已从系统移除。部分正在使用的文件会在下次重启时清理；现在可以继续使用电脑。' if reboot else
                    '输入法与程序文件已移除。')
            else:
                self.description.setText('三套码表已就绪。可从开始菜单打开青石五笔设置。')
            self.details.setText('用户设置与词条已删除。' if self.uninstalling and status.get('data_removed') else
                                 ('设置与词条已保留，下次安装可继续使用。' if self.uninstalling else '使用 Win + 空格切换到青石五笔。'))
            self.clear_data.hide()
            self.notice.setText('其他 Rime 方案的数据已保留。' if self.uninstalling else '可在设置向导中选择默认方案与候选窗显示。')
            self.show_progress(100, '卸载已完成 · 占用文件将在下次重启时清理' if reboot else '已完成')
            self.start.setText('稍后重启' if reboot else '完成')
            self.cancel.hide()
            if not self.uninstalling:
                self.configure.show()
                if not self.preview and status.get('runtime'):
                    subprocess.Popen([str(Path(status['runtime']) / 'WeaselServer.exe')],
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            self.heading.setText('卸载未完成' if self.uninstalling else '安装未完成')
            self.show_progress(self.progress.value(), status.get('error', '请重试'))
            self.start.setText('重试')
        self.clean_request()

    def open_wizard(self):
        if not self.preview:
            subprocess.Popen([str(Installer().root / 'Qingshi.exe'), '--wizard'])

    def clean_request(self):
        if self.request_dir:
            import shutil
            shutil.rmtree(self.request_dir, ignore_errors=True)
            self.request_dir = None

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            self.clean_request()
            event.accept()


def elevate_worker(executable, request):
    class ShellInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
                    ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                    ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
                    ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                    ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]
    info = ShellInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100  # retain process handle; don't show an extra shell error dialog
    info.lpVerb = 'runas'
    info.lpFile = str(executable)
    info.lpParameters = subprocess.list2cmdline(['--worker', str(request)])
    info.nShow = 0
    function = ctypes.WinDLL('shell32', use_last_error=True).ShellExecuteExW
    function.argtypes = [ctypes.POINTER(ShellInfo)]
    function.restype = wintypes.BOOL
    previous = os.environ.get('PYINSTALLER_RESET_ENVIRONMENT')
    os.environ['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    try:
        if not function(ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if previous is None:
            os.environ.pop('PYINSTALLER_RESET_ENVIRONMENT', None)
        else:
            os.environ['PYINSTALLER_RESET_ENVIRONMENT'] = previous
    return info.hProcess


def worker_active(handle):
    function = ctypes.windll.kernel32.GetExitCodeProcess
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    code = wintypes.DWORD()
    if not function(handle, ctypes.byref(code)):
        return False
    return code.value == 259
