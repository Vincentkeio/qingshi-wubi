"""Owned IMM component deployment; no changes to other IMEs or game files."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import shutil
import uuid
import winreg

IME_NAME = 'qingshi_game.ime'
LAYOUTS = r'SYSTEM\CurrentControlSet\Control\Keyboard Layouts'
PRELOAD = r'Keyboard Layout\Preload'
SUBSTITUTES = r'Keyboard Layout\Substitutes'


class GameIme:
    def __init__(self, registry, schedule_delete, system_dir=None):
        self.reg = registry
        self.schedule_delete = schedule_delete
        self.directory = Path(system_dir or (Path(os.environ['WINDIR']) / 'System32'))
        self.target = self.directory / IME_NAME
        self.backup = None
        self.created_layouts = []
        self.deployed = False

    def layouts(self):
        return [name for name in self.reg.children(winreg.HKEY_LOCAL_MACHINE, LAYOUTS)
                if str(self.reg.get(winreg.HKEY_LOCAL_MACHINE, LAYOUTS + '\\' + name,
                                    'Ime File') or '').lower() == IME_NAME]

    def install(self, source):
        source = Path(source)
        for part in (self.directory, *self.directory.parents):
            if part.exists() and part.lstat().st_file_attributes & 0x400:
                raise RuntimeError('游戏兼容组件目录包含链接，已停止')
        before = set(self.layouts())
        if self.target.is_symlink() or (self.target.exists() and self.target.lstat().st_file_attributes & 0x400):
            raise RuntimeError('游戏兼容组件路径包含链接，已停止')
        if self.target.exists():
            identical = hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(self.target.read_bytes()).digest()
            if before and identical:
                return  # already registered by an earlier installation
            if not before and not identical:
                raise RuntimeError('系统目录有未注册的同名兼容组件，未覆盖')
            self.backup = self.target.with_name(IME_NAME + '.' + uuid.uuid4().hex + '.old')
            self.target.rename(self.backup)
        try:
            shutil.copy2(source, self.target)
            self.deployed = True
            dll = ctypes.WinDLL('imm32', use_last_error=True)
            install = dll.ImmInstallIMEW
            install.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            install.restype = wintypes.HKL
            layout = install(str(self.target), '青石五笔（游戏兼容）')
            if not layout:
                raise RuntimeError('Windows 未能注册游戏兼容组件')
            self.created_layouts = list(set(self.layouts()) - before)
        except BaseException:
            self.created_layouts = list(set(self.layouts()) - before)
            self.rollback()
            raise

    def _remove_layouts(self, names):
        for name in names:
            key = LAYOUTS + '\\' + name
            if str(self.reg.get(winreg.HKEY_LOCAL_MACHINE, key, 'Ime File') or '').lower() != IME_NAME:
                continue
            user = ctypes.WinDLL('user32')
            unload = user.UnloadKeyboardLayout
            unload.argtypes = [wintypes.HKL]
            unload.restype = wintypes.BOOL
            unload(ctypes.c_void_p(ctypes.c_int32(int(name, 16)).value))
            self.reg.delete(winreg.HKEY_LOCAL_MACHINE, key)
            for key_name in (PRELOAD, SUBSTITUTES):
                for value_name in self.reg.values(winreg.HKEY_CURRENT_USER, key_name):
                    value = self.reg.get(winreg.HKEY_CURRENT_USER, key_name, value_name)
                    if str(value).upper() == name.upper():
                        self.reg.delete_value(winreg.HKEY_CURRENT_USER, key_name, value_name)

    def rollback(self):
        self._remove_layouts(self.created_layouts)
        if self.deployed and self.target.exists():
            stale = self.target.with_name(IME_NAME + '.' + uuid.uuid4().hex + '.failed')
            self.target.rename(stale)
            self.schedule_delete(stale)
        if self.backup and self.backup.exists():
            self.backup.rename(self.target)
        self.deployed = False
        self.created_layouts = []

    def finish(self):
        if self.backup and self.backup.exists():
            self.schedule_delete(self.backup)

    def remove(self):
        names = self.layouts()
        if names and self.target.exists():
            try:
                self.target.unlink()
            except OSError:
                # Schedule only a unique retired filename; reinstalling before
                # reboot must not cause the new component to be deleted.
                stale = self.target.with_name(IME_NAME + '.' + uuid.uuid4().hex + '.old')
                self.target.rename(stale)
                self.schedule_delete(stale)
        self._remove_layouts(names)
