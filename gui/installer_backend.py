"""青石安装事务与卸载。仅 worker 在提权后执行，预览不调用任何变更。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
import winreg
import zipfile

APP_ID = 'QingshiWubi'
VERSION = '1.0.13'
APP_KEY = r'Software\QingshiWubi'
RIME_KEY = r'Software\Rime\Weasel'
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\QingshiWubi'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
CLSID = '{A3F4CDED-B1E9-41EE-9CA6-7B4D0DE6CB0A}'
PROFILE = '{3D02CAB6-2B8E-4781-BA20-1C9267529467}'
TIP_KEY = rf'Software\Microsoft\CTF\TIP\{CLSID}'
CLASS_KEY = rf'Software\Classes\CLSID\{CLSID}'
MARKER = '.qingshi-install.json'
DATA_MARKER = '.qingshi-data.json'
VIEWS = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
# Keep native modules in the application's own system directory. Versioned
# filenames allow upgrades while existing applications still hold the old DLL.
SYSTEM_IME_DIR = Path(os.environ['WINDIR']) / 'System32' / 'IME' / APP_ID
SYSTEM_IME_DLL = Path(os.environ['WINDIR']) / 'System32' / 'weaselx64.dll'


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def below(path, parent):
    path, parent = Path(path).resolve(), Path(parent).resolve()
    return path != parent and parent in path.parents


def no_reparse(path):
    """Never follow a symlink/junction during privileged file operations."""
    path = Path(path)
    for part in (path, *path.parents):
        if part.exists() and part.lstat().st_file_attributes & 0x400:
            raise RuntimeError(f'路径包含链接或目录联接，已停止：{part}')


_kernel32 = None


def _move_file_ex(path):
    """把文件排进"重启后删除"队列。返回 False 表示排不进（不抛异常）。"""
    global _kernel32
    if _kernel32 is None:
        # WinDLL() 每次调用都会 LoadLibrary 一遍；逐个文件新建会把
        # 卸载拖慢，这里缓存一次。
        library = ctypes.WinDLL('kernel32', use_last_error=True)
        library.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        library.MoveFileExW.restype = wintypes.BOOL
        _kernel32 = library
    return bool(_kernel32.MoveFileExW(str(path), None, 4))


class Registry:
    def get(self, hive, key, name='', view=winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                return winreg.QueryValueEx(handle, name)[0]
        except FileNotFoundError:
            return None

    def set(self, hive, key, name, value, view=winreg.KEY_WOW64_64KEY):
        with winreg.CreateKeyEx(hive, key, 0, winreg.KEY_WRITE | view) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ, value)

    def children(self, hive, key, view=winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                return [winreg.EnumKey(handle, i) for i in range(winreg.QueryInfoKey(handle)[0])]
        except FileNotFoundError:
            return []

    def values(self, hive, key, view=winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                return [winreg.EnumValue(handle, i)[0] for i in range(winreg.QueryInfoKey(handle)[1])]
        except FileNotFoundError:
            return []

    def delete(self, hive, key, view=winreg.KEY_WOW64_64KEY):
        for child in self.children(hive, key, view):
            self.delete(hive, key + '\\' + child, view)
        try:
            winreg.DeleteKeyEx(hive, key, view, 0)
        except FileNotFoundError:
            pass

    def delete_value(self, hive, key, name, view=winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(hive, key, 0, winreg.KEY_SET_VALUE | view) as handle:
                winreg.DeleteValue(handle, name)
        except FileNotFoundError:
            pass


class Windows:
    def __init__(self, registry=None):
        self.reg = registry or Registry()
        self.pending = []
        self.leftover = []
        # InstallLayoutOrTip 整表替换时被误删、随后补回来的其他输入法
        self.restored_input_methods = []
        from game_compat import GameIme
        self.game_ime = GameIme(self.reg, self.schedule_delete)

    def command(self, arguments, timeout=180, env=None):
        result = subprocess.run([str(a) for a in arguments], timeout=timeout, env=env,
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise RuntimeError(f'{Path(arguments[0]).name} 执行失败（{result.returncode}）')

    def register(self, dll, remove=False, x86=False):
        system = 'SysWOW64' if x86 else 'System32'
        env = os.environ.copy()
        env['TEXTSERVICE_PROFILE'] = 'hans'
        args = [Path(os.environ['WINDIR']) / system / 'regsvr32.exe', '/s']
        if remove:
            args.append('/u')
        self.command([*args, dll], env=env)

    def install_system_ime(self, source):
        """把输入法 DLL 放进系统目录。

        带反作弊的游戏只加载系统目录下的输入法 DLL，装在 Program Files 里
        它们连加载都不会尝试（日志里看不到任何激活记录）。旧文件可能正被
        进程加载着，删不掉就先改名让位。
        """
        no_reparse(SYSTEM_IME_DIR)
        SYSTEM_IME_DIR.mkdir(parents=True, exist_ok=True)
        target = SYSTEM_IME_DIR / ('weaselx64-' + uuid.uuid4().hex + '.dll')
        shutil.copy2(source, target)
        return target

    def remove_system_ime(self):
        """卸载时清掉系统目录里的副本；删不掉就排进重启删除队列。"""
        no_reparse(SYSTEM_IME_DIR)
        if SYSTEM_IME_DIR.exists():
            for target in SYSTEM_IME_DIR.iterdir():
                if target.name == 'weaselx64.dll' or re.fullmatch(r'weaselx64-[0-9a-f]{32}\.dll', target.name):
                    try:
                        target.unlink()
                    except OSError:
                        self.schedule_delete(target)

    def install_game_ime(self, source):
        self.game_ime.install(source)

    def rollback_game_ime(self):
        self.game_ime.rollback()

    def finish_game_ime(self):
        self.game_ime.finish()

    def remove_game_ime(self):
        self.game_ime.remove()

    def input_method_entries(self):
        """当前用户"中文(简体)"下的输入法列表（0804:... 条目）。"""
        key = r'Control Panel\International\User Profile\zh-Hans-CN'
        return {name: self.reg.get(winreg.HKEY_CURRENT_USER, key, name)
                for name in self.reg.values(winreg.HKEY_CURRENT_USER, key)
                if name.startswith('0804:')}

    def add_input_method_entry(self, name, value=1):
        self.reg.set(winreg.HKEY_CURRENT_USER,
                     r'Control Panel\International\User Profile\zh-Hans-CN', name, value)

    def tip(self, remove=False):
        """把本输入法加入/移出用户的输入法列表。

        InstallLayoutOrTip 在部分 Windows 版本上是**整表替换**语义：只传自己
        那一项，会把用户原有的其他输入法（例如微软拼音）一起清掉 —— 卸载之后
        语言列表里就只剩我们一个，Win+Space 变成没东西可切，游戏里输入法一失效
        就彻底没有兜底。这里先备份整张表，调用后把被清掉的条目补回去。
        """
        entry = f'0804:{CLSID}{PROFILE}'
        before = self.input_method_entries()
        dll = ctypes.WinDLL('input.dll')
        function = dll.InstallLayoutOrTip
        function.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        function.restype = wintypes.BOOL
        success = function(entry, 1 if remove else 0)
        after = self.input_method_entries()
        for name, value in before.items():
            if name != entry and name not in after:
                self.add_input_method_entry(name, value)
                self.restored_input_methods.append(name)
        if not success:
            raise ctypes.WinError()

    def disarm_autostart(self, roots):
        """先撤掉启动脚本，再停服务。

        TSF DLL 还挂在 explorer.exe 等一堆进程里，`_EnsureServerConnected()`
        会在按键/切焦点时执行 start_service.bat 把 WeaselServer 重新拉起来。
        卸载时如果不先撤掉这个脚本，就会变成"卸载器杀服务、输入法又拉起来"的
        拉锯战：文件一直锁着删不掉，而且每次按键都会阻塞调用方几秒钟。

        只改名不删除：万一卸载中途失败，还能把它改回来。
        """
        for root in roots:
            script = Path(root) / 'start_service.bat'
            disabled = script.with_name('start_service.bat.disabled')
            if not script.is_file():
                continue
            for attempt in range(6):
                try:
                    script.rename(disabled)
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    time.sleep(0.2)

    def rearm_autostart(self, roots):
        """卸载没走完时把启动脚本还原，避免留下一个起不来的输入法。"""
        for root in roots:
            script = Path(root) / 'start_service.bat'
            disabled = script.with_name('start_service.bat.disabled')
            if script.is_file() or not disabled.is_file():
                continue
            try:
                disabled.rename(script)
            except OSError:
                pass

    def stop(self, roots):
        """Only terminate engine/settings processes whose full executable path is owned."""
        from ctypes import wintypes as wt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        class Entry(ctypes.Structure):
            _fields_ = [('size', wt.DWORD), ('usage', wt.DWORD), ('pid', wt.DWORD),
                        ('heap', ctypes.c_size_t), ('module', wt.DWORD), ('threads', wt.DWORD),
                        ('parent', wt.DWORD), ('priority', wt.LONG), ('flags', wt.DWORD), ('name', wt.WCHAR * 260)]
        kernel.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wt.HANDLE
        kernel.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(Entry)]
        kernel.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(Entry)]
        kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        kernel.OpenProcess.restype = wt.HANDLE
        kernel.CloseHandle.argtypes = [wt.HANDLE]
        kernel.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        kernel.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        kernel.WaitForSingleObject.restype = wt.DWORD
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = Entry()
            entry.size = ctypes.sizeof(entry)
            present = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while present:
                if entry.pid != os.getpid() and entry.name.lower() in {'weaselserver.exe', 'weaseldeployer.exe', 'qingshi.exe'}:
                    handle = kernel.OpenProcess(0x00101000, False, entry.pid)
                    if handle:
                        try:
                            buffer = ctypes.create_unicode_buffer(32768)
                            size = wt.DWORD(len(buffer))
                            if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                                if any(below(buffer.value, root) for root in roots):
                                    if entry.name.lower() == 'weaselserver.exe':
                                        # /q asks the server to exit through its IPC loop. Its normal
                                        # shutdown removes the tray icon with Shell_NotifyIcon(NIM_DELETE).
                                        self.command([buffer.value, '/q'], timeout=15)
                                        if kernel.WaitForSingleObject(handle, 5000) != 0:
                                            raise RuntimeError('输入法托盘服务没有正常退出。卸载已暂停，请稍后重试。')
                                    else:
                                        self.command(['taskkill.exe', '/PID', str(entry.pid), '/T', '/F'], timeout=15)
                        finally:
                            kernel.CloseHandle(handle)
                present = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)

    def remove_tree(self, path, allow_root):
        path, allow_root = Path(path).resolve(), Path(allow_root).resolve()
        if path != allow_root and not below(path, allow_root):
            raise RuntimeError('清理路径超出已核实的安装目录')
        no_reparse(path)
        if not path.exists():
            return
        # Walk one directory at a time. Building and sorting a Path list for
        # every entry made complete removal consume unbounded memory and stall
        # Windows when a user's Rime data/build cache contained many files.
        def reject_reparse(entry):
            # 只对目录做 stat：文件若是符号链接，unlink 只会删掉链接本身，
            # 不会碰到目标；而 entry.stat() 在 Windows 上是一次额外系统调用，
            # 对成千上万个文件逐个调用会把卸载拖慢一个数量级。
            if not entry.is_dir(follow_symlinks=False):
                return
            try:
                attributes = entry.stat(follow_symlinks=False).st_file_attributes
            except OSError:
                # 拿不到属性就不要让整个卸载崩掉；后面的 unlink/rmdir 失败会被记账。
                return
            if attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
                raise RuntimeError(f'路径包含链接或目录联接，已停止：{entry.path}')

        try:
            root_stat = path.lstat()
        except FileNotFoundError:
            return
        if root_stat.st_file_attributes & 0x400:
            raise RuntimeError(f'路径包含链接或目录联接，已停止：{path}')
        if not stat.S_ISDIR(root_stat.st_mode):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                self.schedule_delete(path)
            return

        # First pass validates the full tree before deleting anything. Keep
        # one iterator per nesting level instead of queuing every sibling
        # directory: user data can contain many build/cache subdirectories.
        validation = []
        try:
            validation.append((path, os.scandir(path)))
            while validation:
                directory, entries = validation[-1]
                try:
                    entry = next(entries)
                except StopIteration:
                    entries.close()
                    validation.pop()
                    continue
                reject_reparse(entry)
                if entry.is_dir(follow_symlinks=False):
                    try:
                        validation.append((Path(entry.path), os.scandir(entry.path)))
                    except FileNotFoundError:
                        continue
        except FileNotFoundError:
            for _, iterator in validation:
                iterator.close()
            return
        except BaseException:
            for _, iterator in validation:
                iterator.close()
            raise

        # Second pass uses open scandir iterators as a depth-first stack and
        # removes each directory after its children. This avoids a giant list
        # or recursive Python calls while preserving the no-follow policy.
        try:
            stack = [(path, os.scandir(path))]
        except FileNotFoundError:
            return
        while stack:
            directory, entries = stack[-1]
            try:
                entry = next(entries)
            except StopIteration:
                entries.close()
                stack.pop()
                try:
                    directory.rmdir()
                except FileNotFoundError:
                    pass
                except OSError:
                    self.schedule_delete(directory)
                continue
            try:
                reject_reparse(entry)
            except RuntimeError:
                for _, iterator in stack:
                    iterator.close()
                raise
            child = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                try:
                    stack.append((child, os.scandir(child)))
                except FileNotFoundError:
                    continue
                except OSError:
                    # 打不开的子目录（权限/占用）不该让整个卸载中断。
                    self.leftover.append(str(child))
                    continue
            else:
                try:
                    child.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    self.schedule_delete(child)

    def schedule_delete(self, path):
        path = str(path)
        if _move_file_ex(path):
            self.pending.append(path)
            return True
        # 排不进"重启后删除"队列也不该让整个卸载中断：剩下的残留留给下一次
        # 安装/重启清理，并在结果里如实报告（leftover）。
        self.leftover.append(path)
        return False

    def shortcut(self, link, executable, arguments=''):
        # Use a saved PowerShell script; paths and arguments are passed as parameters.
        helper = Path(__file__).with_name('shortcut.ps1')
        self.command(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                      helper, '-LinkPath', link, '-Executable', executable, '-Arguments', arguments])


class Installer:
    def __init__(self, source=None, system=None, progress=None, install_root=None, profile=None):
        self.system = system or Windows()
        self.reg = self.system.reg
        self.source = Path(source or Path(__file__).with_name('payload.zip'))
        self.root = Path(install_root or Path(os.environ['ProgramFiles']) / APP_ID).resolve()
        self.profile = Path(profile or Path.home()).resolve()
        self.data = self.profile / 'AppData/Roaming/QingshiWubi'
        self.progress = progress or (lambda percent, text: None)
        self.changes = []

    def write(self, hive, key, name, value, view=winreg.KEY_WOW64_64KEY):
        address = (hive, key, name, view)
        if not any(change[0] == address for change in self.changes):
            self.changes.append((address, self.reg.get(hive, key, name, view)))
        self.reg.set(hive, key, name, value, view)

    def restore_registry(self):
        for (hive, key, name, view), value in reversed(self.changes):
            if value is None:
                self.reg.delete_value(hive, key, name, view)
            else:
                self.reg.set(hive, key, name, value, view)

    def remove_value(self, hive, key, name, view=winreg.KEY_WOW64_64KEY):
        self.changes.append(((hive, key, name, view), self.reg.get(hive, key, name, view)))
        self.reg.delete_value(hive, key, name, view)

    def managed(self):
        manifest = read_json(self.root / MARKER)
        return manifest if manifest.get('app_id') == APP_ID else {}

    def registered_dll(self, view=winreg.KEY_WOW64_64KEY):
        value = self.reg.get(winreg.HKEY_LOCAL_MACHINE, CLASS_KEY + r'\InprocServer32', view=view)
        return Path(value) if value else None

    def legacy_root(self):
        dll = self.registered_dll()
        if not dll or below(dll, self.root):
            return None
        if dll.resolve() == SYSTEM_IME_DLL.resolve() or below(dll, SYSTEM_IME_DIR):
            # 我们自己的系统目录副本，不是别人装的输入法
            return None
        # Older QingShi builds registered the right DLL and unique TSF class,
        # but some Windows builds omitted the profile Description value.
        # The branded module name plus the canonical Weasel install location
        # is sufficient ownership evidence; a different module remains foreign.
        if dll.name.lower() != 'qingshi-weaselx64.dll':
            raise RuntimeError('已安装另一套小狼毫/Rime。请先卸载它，再安装青石五笔。')
        for program_files in filter(None, [os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')]):
            parent = Path(program_files) / 'Rime'
            if dll.parent.parent == parent and dll.parent.name.lower().startswith('weasel-'):
                no_reparse(dll.parent)
                return dll.parent
        raise RuntimeError('检测到旧版青石，但安装位置不在可核实范围内，已停止自动清理。')

    def validate_root(self):
        expected = (Path(os.environ['ProgramFiles']) / APP_ID).resolve()
        if self.root != expected:
            raise RuntimeError('安装位置必须是青石专用程序目录')
        no_reparse(self.root)
        if self.root.exists() and not self.managed():
            entries = list(self.root.iterdir())

            def known_uninstall_residue(entry):
                no_reparse(entry)
                if entry.name == 'Qingshi.exe' and entry.is_file():
                    return True
                if not entry.is_dir() or not entry.name.startswith('runtime-'):
                    return False
                version, separator, token = entry.name[len('runtime-'):].rpartition('-')
                return (bool(separator) and len(token) == 8 and
                        all(char in '0123456789abcdefABCDEF' for char in token) and
                        bool(re.fullmatch(r'\d+\.\d+\.\d+', version)))

            # An uninstall can remove its manifest while Windows still holds
            # files from a versioned runtime loaded in Explorer. Those paths
            # are scheduled for reboot deletion, but must not block a fresh
            # install into a new versioned runtime directory.
            if entries and not all(known_uninstall_residue(entry) for entry in entries):
                raise RuntimeError('安装目录中存在无法确认归属的文件，已停止')

    def preflight(self):
        if platform.machine().upper() not in ('AMD64', 'X86_64'):
            raise RuntimeError('当前安装包仅支持 Windows x64，不支持 ARM64 或 32 位系统。')
        if sys.getwindowsversion().major < 10:
            raise RuntimeError('当前安装包需要 Windows 10 或 Windows 11。')
        self.validate_root()
        legacy = self.legacy_root()
        x86 = self.registered_dll(winreg.KEY_WOW64_32KEY)
        if x86 and not below(x86, self.root) and (not legacy or not below(x86, legacy)):
            raise RuntimeError('32 位输入法注册属于其他安装。请先卸载原输入法。')
        if not self.source.is_file():
            raise RuntimeError('安装包缺少程序数据，请重新下载安装包。')
        with zipfile.ZipFile(self.source) as archive:
            entries = archive.namelist()
            hashes = json.loads(archive.read('checksums.json'))
            required = {'runtime/WeaselServer.exe', 'runtime/WeaselDeployer.exe', 'runtime/weaselx64.dll', 'runtime/rime.dll', 'runtime/qingshi_game.ime'}
            if not required.issubset(hashes):
                raise RuntimeError('安装包缺少必要的输入法组件')
            if len(entries) != len(set(entries)) or set(entries) != set(hashes) | {'checksums.json'}:
                raise RuntimeError('安装包文件清单不一致')
            for name in entries:
                if name == 'checksums.json':
                    continue
                if name not in hashes or hashlib.sha256(archive.read(name)).hexdigest() != hashes[name]:
                    raise RuntimeError(f'安装包校验失败：{name}')
                if not below(self.root / name, self.root):
                    raise RuntimeError('安装包包含越界路径')
                if name.split('/', 1)[0] not in ('runtime', 'user') or '\\' in name or ':' in name:
                    raise RuntimeError('安装包包含无效路径')
        return legacy

    def install(self, executable):
        self.progress(4, '正在检查系统与安装包')
        legacy = self.preflight()
        no_reparse(self.data)
        if self.data.exists() and any(self.data.iterdir()) and read_json(self.data / DATA_MARKER).get('app_id') != APP_ID:
            raise RuntimeError('专用用户目录包含无法确认归属的数据，已停止')
        previous = self.managed()
        old_user_settings = previous.get('previous_user_settings')
        if old_user_settings is None:
            old_user_settings = {
                name: self.reg.get(winreg.HKEY_CURRENT_USER, RIME_KEY, name)
                for name in ('RimeUserDir', 'Profile')
            }
        runtime = self.root / ('runtime-' + VERSION + '-' + uuid.uuid4().hex[:8])
        old_dll = self.registered_dll()
        old_runtime = self.reg.get(winreg.HKEY_LOCAL_MACHINE, RIME_KEY, 'WeaselRoot', winreg.KEY_WOW64_32KEY)
        self.root.mkdir(parents=True, exist_ok=True)
        self.data.mkdir(parents=True, exist_ok=True)
        existing_data = {p.name for p in self.data.iterdir()}
        # The marker is written before extraction so a failed install remains removable.
        manifest = {'app_id': APP_ID, 'version': VERSION, 'runtime': str(runtime),
                    'profiles': list(dict.fromkeys(previous.get('profiles', []) + [str(self.profile)])),
                    'legacy_roots': list(dict.fromkeys(previous.get('legacy_roots', []) + ([str(legacy)] if legacy else []))),
                    'previous_user_settings': old_user_settings}
        atomic_json(self.root / MARKER, manifest)
        target_exe = self.root / 'Qingshi.exe'
        if Path(executable).resolve() != target_exe.resolve():
            shutil.copy2(executable, target_exe)
        # Register recovery/removal before invoking native tools, even if installation later fails.
        for name, value in {
            'DisplayName': '青石五笔输入法', 'DisplayVersion': VERSION, 'Publisher': '青石五笔',
            'InstallLocation': str(self.root), 'DisplayIcon': str(target_exe),
            'UninstallString': f'"{target_exe}" --uninstall', 'NoModify': 1, 'NoRepair': 1,
        }.items():
            self.reg.set(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, name, value)
        self.progress(15, '正在写入输入法与三套码表')
        system_dll = None
        try:
            with zipfile.ZipFile(self.source) as archive:
                for entry in archive.namelist():
                    if entry == 'checksums.json':
                        continue
                    category, relative = entry.split('/', 1)
                    target = runtime / relative if category == 'runtime' else self.data / relative
                    no_reparse(target)
                    if category == 'user' and target.exists():
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(entry))
            # Carry forward only the fork's settings/phrases, never overwrite a user's word list.
            legacy_data = self.profile / 'AppData/Roaming/Rime'
            for name in ('weasel.custom.yaml', 'default.custom.yaml', 'custom_phrase.txt', 'qingshi_pin_history.tsv',
                         'wubi86.custom.yaml', 'wubi98.custom.yaml', 'wubi06.custom.yaml'):
                source = legacy_data / name
                target = self.data / name
                if name not in existing_data and source.is_file() and '青石' in source.read_text(encoding='utf-8', errors='ignore')[:1024]:
                    shutil.copy2(source, target)
            atomic_json(self.data / DATA_MARKER, {'app_id': APP_ID})
            from fixed_order import ensure_fixed_order
            ensure_fixed_order(self.data)
            self.progress(35, '正在停止旧版输入法服务')
            self.system.stop([self.root] + ([legacy] if legacy else []))
            self.progress(45, '正在注册输入法')
            # 游戏只加载系统目录下的输入法 DLL，所以放一份到 System32 并从那份注册。
            self.system.install_game_ime(runtime / 'qingshi_game.ime')
            system_dll = self.system.install_system_ime(runtime / 'weaselx64.dll')
            self.system.register(system_dll)
            for view in VIEWS:
                for name, value in {'WeaselRoot': str(runtime), 'InstallDir': str(self.root), 'ServerExecutable': 'WeaselServer.exe'}.items():
                    self.write(winreg.HKEY_LOCAL_MACHINE, RIME_KEY, name, value, view)
            self.write(winreg.HKEY_CURRENT_USER, RIME_KEY, 'RimeUserDir', str(self.data))
            self.write(winreg.HKEY_CURRENT_USER, RIME_KEY, 'Profile', 'hans')
            self.write(winreg.HKEY_CURRENT_USER, RIME_KEY, 'QingshiShiftLetterDirect', 1)
            self.system.tip()
            self.progress(60, '正在编译五笔码表')
            self.system.command([runtime / 'WeaselDeployer.exe', '/deploy'], timeout=240)
            if not (self.data / 'build/wubi86.table.bin').is_file():
                raise RuntimeError('词库编译未生成结果，请重新运行安装以修复。')
            self.progress(82, '正在创建设置、向导与卸载入口')
            for name, value in {'InstallDir': str(self.root), 'RuntimeDir': str(runtime), 'Version': VERSION}.items():
                self.write(winreg.HKEY_LOCAL_MACHINE, APP_KEY, name, value)
            self.write(winreg.HKEY_LOCAL_MACHINE, RUN_KEY, 'QingshiWubi', f'"{runtime / "WeaselServer.exe"}"')
            self.write(winreg.HKEY_CURRENT_USER, RUN_KEY, 'QingshiUpdate', f'"{target_exe}" --check-update')
            for view in VIEWS:
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    command = self.reg.get(hive, RUN_KEY, 'WeaselServer', view)
                    if legacy and command and str(legacy).lower() in command.lower():
                        self.remove_value(hive, RUN_KEY, 'WeaselServer', view)
            self.shortcuts(target_exe)
            registered = self.registered_dll()
            if not registered or registered.resolve() != system_dll.resolve():
                raise RuntimeError('输入法注册结果不匹配，请重新安装。')
            self.system.stop([self.root] + ([legacy] if legacy else []))
            self.system.finish_game_ime()
        except Exception:
            self.system.rollback_game_ime()
            # Restore the previously active input method instead of leaving a half-registered new one.
            if old_dll and old_dll.is_file():
                self.system.register(old_dll)
                self.system.tip()
            else:
                active = self.registered_dll()
                if active and (below(active, runtime) or below(active, SYSTEM_IME_DIR)):
                    self.system.tip(remove=True)
                    self.system.register(active, remove=True)
            self.restore_registry()
            if previous:
                atomic_json(self.root / MARKER, previous)
            if system_dll and system_dll.exists():
                try:
                    system_dll.unlink()
                except OSError:
                    self.system.schedule_delete(system_dll)
            raise
        self.progress(100, '安装完成')
        return {'ok': True, 'action': 'install', 'runtime': str(runtime), 'reboot': False}

    def menu_directories(self):
        all_users = Path(os.environ['ProgramData']) / 'Microsoft/Windows/Start Menu/Programs/青石五笔'
        user = self.profile / 'AppData/Roaming/Microsoft/Windows/Start Menu/Programs/青石五笔'
        return [all_users, user]

    def shortcuts(self, executable):
        menu = self.menu_directories()[0]
        no_reparse(menu)
        menu.mkdir(parents=True, exist_ok=True)
        for name, arguments in [('青石五笔设置', ''), ('配置向导', '--wizard'), ('卸载青石五笔', '--uninstall')]:
            self.system.shortcut(menu / (name + '.lnk'), executable, arguments)

    def cleanup_legacy_data(self):
        data = self.profile / 'AppData/Roaming/Rime'
        if not data.exists():
            return
        no_reparse(data)
        names = ['wubi86', 'wubi98', 'wubi06']
        phrase_source = data / 'custom_phrase.txt'
        own_phrase = phrase_source.is_file() and '青石' in phrase_source.read_text(encoding='utf-8', errors='ignore')[:1024]
        own_legacy = any(
            (data / name).is_file() and (
                '青石' in (data / name).read_text(encoding='utf-8', errors='ignore')[:1024]
                or (name == 'default.custom.yaml' and
                    (data / name).read_text(encoding='utf-8', errors='ignore').startswith('# 五笔输入法 · 方案与候选设置'))
            )
            for name in ('weasel.custom.yaml', 'default.custom.yaml', 'custom_phrase.txt',
                         'wubi86.custom.yaml', 'wubi98.custom.yaml', 'wubi06.custom.yaml')
        )
        for schema in names:
            # Schema IDs are common across Rime packages. Remove them only
            # when a neighboring QingShi-owned settings file proves the tree.
            if own_legacy:
                for pattern in (schema + '.schema.yaml', schema + '.dict.yaml', schema + '.custom.yaml',
                                schema + '.userdb', 'build/' + schema + '.*'):
                    for file in data.glob(pattern):
                        self.system.remove_tree(file, data)
        for name in ('default.custom.yaml', 'weasel.custom.yaml', 'custom_phrase.txt', 'qingshi_pin_history.tsv'):
            file = data / name
            header = file.read_text(encoding='utf-8', errors='ignore')[:1024] if file.is_file() else ''
            if ('青石' in header or
                    (name == 'default.custom.yaml' and header.startswith(('# 五笔三版本方案切换', '# 五笔输入法 · 方案与候选设置')))):
                self.system.remove_tree(file, data)
        for name in ('custom_phrase.userdb', 'custom_phrase.stabledb'):
            file = data / name
            # This stable database is shared; delete only if its phrase source was ours and no longer exists.
            if own_phrase and file.exists():
                self.system.remove_tree(file, data)
        if own_legacy:
            for name in ('build/default.yaml', 'build/weasel.yaml'):
                file = data / name
                if file.is_file():
                    content = file.read_text(encoding='utf-8', errors='ignore')
                    if 'qingshi_' in content or all(schema in content for schema in names):
                        self.system.remove_tree(file, data)
        # Remove only the fork's schema history from a shared Rime state file.
        state = data / 'user.yaml'
        if own_legacy and state.is_file():
            import yaml
            content = yaml.safe_load(state.read_text(encoding='utf-8')) or {}
            variables = content.get('var') or {}
            if variables.get('previously_selected_schema') in names:
                variables.pop('previously_selected_schema')
            access = variables.get('schema_access_time') or {}
            for schema in names:
                access.pop(schema, None)
            if not access:
                variables.pop('schema_access_time', None)
            if variables:
                content['var'] = variables
            else:
                content.pop('var', None)
            state.write_text(yaml.safe_dump(content, allow_unicode=True), encoding='utf-8')

    def dedicated_data_directories(self):
        profiles = {self.profile}
        key = r'Software\Microsoft\Windows NT\CurrentVersion\ProfileList'
        for child in self.reg.children(winreg.HKEY_LOCAL_MACHINE, key):
            value = self.reg.get(winreg.HKEY_LOCAL_MACHINE, key + '\\' + child, 'ProfileImagePath')
            if value:
                profiles.add(Path(os.path.expandvars(value)).resolve())
        for profile in profiles:
            directory = profile / 'AppData/Roaming/QingshiWubi'
            if read_json(directory / DATA_MARKER).get('app_id') == APP_ID:
                no_reparse(directory)
                yield directory

    def uninstall(self, clear_data=True):
        self.validate_root()
        manifest = self.managed()
        legacy = self.legacy_root()
        if not manifest and not legacy:
            raise RuntimeError('未检测到可核实的青石五笔安装')
        # Validate all deletion targets before unregistering anything.
        data_directories = list(self.dedicated_data_directories()) if clear_data else []
        if clear_data and self.data.exists() and self.data not in data_directories:
            raise RuntimeError('用户数据缺少青石归属标记，未执行删除')
        roots = [self.root] if manifest else []
        for value in manifest.get('legacy_roots', []) + ([str(legacy)] if legacy else []):
            path = Path(value).resolve()
            allowed = [Path(p) / 'Rime' for p in filter(None, [os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')])]
            if path.parent not in allowed or not path.name.lower().startswith('weasel-'):
                raise RuntimeError('旧版安装位置不符合清理范围')
            no_reparse(path)
            if path not in roots:
                roots.append(path)
        self.progress(8, '正在退出输入法与设置程序')
        x86 = self.registered_dll(winreg.KEY_WOW64_32KEY)
        if x86 and not any(below(x86, root) for root in roots):
            raise RuntimeError('32 位输入法注册属于其他安装，已停止清理以免误删。')
        self.system.disarm_autostart(roots)
        try:
            self.system.stop(roots)
        except BaseException:
            self.system.rearm_autostart(roots)
            raise
        self.progress(22, '正在移除输入法注册与语言配置')
        active = self.registered_dll()
        if active:
            # 正常情况下注册指向 System32 里的副本（游戏只认那里），
            # 旧版本则指向安装目录里的 DLL —— 两种都算我们的。
            ours = any(below(active, root) for root in roots) or active.resolve() == SYSTEM_IME_DLL.resolve() or below(active, SYSTEM_IME_DIR)
            if not ours:
                raise RuntimeError('输入法注册已由其他程序接管，已停止卸载')
            self.system.tip(remove=True)
            self.system.register(active, remove=True)
        x86 = self.registered_dll(winreg.KEY_WOW64_32KEY)
        if x86 and x86.is_file() and any(below(x86, root) for root in roots):
            self.system.register(x86, remove=True, x86=True)
        # 注册已经撤掉，系统目录里的副本也清掉，别给系统留垃圾。
        self.system.remove_system_ime()
        self.system.remove_game_ime()
        for view in VIEWS:
            for key in (CLASS_KEY, TIP_KEY):
                self.reg.delete(winreg.HKEY_LOCAL_MACHINE, key, view)
            rime_root = self.reg.get(winreg.HKEY_LOCAL_MACHINE, RIME_KEY, 'WeaselRoot', view)
            if rime_root and any(Path(rime_root).resolve() == root or below(rime_root, root) for root in roots):
                # This is a shared Rime key. Remove only values written for this
                # installation, leaving any other Weasel/Rime settings intact.
                self.reg.delete_value(winreg.HKEY_LOCAL_MACHINE, RIME_KEY, 'WeaselRoot', view)
                install_dir = self.reg.get(winreg.HKEY_LOCAL_MACHINE, RIME_KEY, 'InstallDir', view)
                if install_dir and Path(install_dir).resolve() == self.root:
                    self.reg.delete_value(winreg.HKEY_LOCAL_MACHINE, RIME_KEY, 'InstallDir', view)
                server = self.reg.get(winreg.HKEY_LOCAL_MACHINE, RIME_KEY, 'ServerExecutable', view)
                if server == 'WeaselServer.exe':
                    self.reg.delete_value(winreg.HKEY_LOCAL_MACHINE, RIME_KEY, 'ServerExecutable', view)
            for name in ('QingshiWubi', 'WeaselServer', 'QingshiUpdate'):
                command = self.reg.get(winreg.HKEY_LOCAL_MACHINE, RUN_KEY, name, view)
                if command and any(str(root).lower() in command.lower() for root in roots):
                    self.reg.delete_value(winreg.HKEY_LOCAL_MACHINE, RUN_KEY, name, view)
        self.progress(42, '正在清理开机启动与开始菜单')
        for menu in self.menu_directories():
            self.system.remove_tree(menu, menu)
        # Old NSIS installed its menu under the upstream display name.
        for name in ('小狼毫输入法', 'Weasel', '小狼毫輸入法'):
            menu = self.menu_directories()[0].parent / name
            if legacy:
                self.system.remove_tree(menu, menu)
        self.progress(56, '正在清理用户设置与词条' if clear_data else '正在保留用户设置与词条')
        if clear_data:
            for directory in data_directories:
                self.system.remove_tree(directory, directory)
            if legacy or manifest.get('legacy_roots'):
                self.cleanup_legacy_data()
            import tempfile
            temp_root = Path(tempfile.gettempdir())
            logs = temp_root / 'qingshi.wubi'
            self.system.remove_tree(logs, logs)
            # 卸载入口每次都会把主程序复制到 %TEMP% 再运行，PyInstaller 还会在
            # 临时目录解包上百 MB。这些残留不清理会一直占着用户磁盘。
            # 跳过当前正在运行的这一份（删不掉，也没必要）。
            try:
                current = Path(sys.executable).resolve().parent
            except OSError:
                current = None
            for stale in temp_root.glob('qingshi-uninstall-*'):
                try:
                    if current is not None and stale.resolve() == current:
                        continue
                except OSError:
                    continue
                if stale.is_dir():
                    self.system.remove_tree(stale, temp_root)
        for view in VIEWS:
            for key in (APP_KEY, TIP_KEY, CLASS_KEY):
                self.reg.delete(winreg.HKEY_CURRENT_USER, key, view)
            userdir = self.reg.get(winreg.HKEY_CURRENT_USER, RIME_KEY, 'RimeUserDir', view)
            owns_userdir = userdir and Path(userdir).resolve() == self.data.resolve()
            if owns_userdir:
                prior = manifest.get('previous_user_settings', {}).get('RimeUserDir')
                if prior is None:
                    self.reg.delete_value(winreg.HKEY_CURRENT_USER, RIME_KEY, 'RimeUserDir', view)
                else:
                    self.reg.set(winreg.HKEY_CURRENT_USER, RIME_KEY, 'RimeUserDir', prior, view)
            profile = self.reg.get(winreg.HKEY_CURRENT_USER, RIME_KEY, 'Profile', view)
            if owns_userdir and profile == 'hans':
                prior = manifest.get('previous_user_settings', {}).get('Profile')
                if prior is None:
                    self.reg.delete_value(winreg.HKEY_CURRENT_USER, RIME_KEY, 'Profile', view)
                else:
                    self.reg.set(winreg.HKEY_CURRENT_USER, RIME_KEY, 'Profile', prior, view)
            self.reg.delete_value(winreg.HKEY_CURRENT_USER, RIME_KEY, 'QingshiShiftLetterDirect', view)
            for name in ('QingshiWubi', 'WeaselServer', 'QingshiUpdate'):
                command = self.reg.get(winreg.HKEY_CURRENT_USER, RUN_KEY, name, view)
                if command and any(str(root).lower() in command.lower() for root in roots):
                    self.reg.delete_value(winreg.HKEY_CURRENT_USER, RUN_KEY, name, view)
            # Delete only this application's uninstall records, never Software\Rime.
            self.reg.delete(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, view)
            old_key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\Weasel'
            old_command = self.reg.get(winreg.HKEY_LOCAL_MACHINE, old_key, 'UninstallString', view)
            if old_command and any(str(root).lower() in old_command.lower() for root in roots):
                self.reg.delete(winreg.HKEY_LOCAL_MACHINE, old_key, view)
        self.progress(76, '正在删除程序文件')
        for root in roots:
            self.system.remove_tree(root, root)
        self.reg.delete(winreg.HKEY_LOCAL_MACHINE, APP_KEY)
        if self.registered_dll() or self.reg.get(winreg.HKEY_LOCAL_MACHINE, RUN_KEY, 'QingshiWubi'):
            raise RuntimeError('系统仍保留输入法注册或启动项，请重试卸载。')
        self.progress(100, '卸载完成，需要重启以删除占用文件' if self.system.pending else '卸载完成')
        return {'ok': True, 'action': 'uninstall', 'reboot': bool(self.system.pending),
                'pending': self.system.pending, 'leftover': self.system.leftover,
                'data_removed': clear_data}


def run_worker(request_file):
    request_file = Path(request_file).resolve()
    import tempfile
    parent = request_file.parent
    if (request_file.name != 'request.json' or parent.parent != Path(tempfile.gettempdir()).resolve()
            or not parent.name.startswith('qingshi-operation-')):
        return 1
    no_reparse(request_file)
    request = read_json(request_file)
    output = request_file.parent / 'status.json'
    try:
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise RuntimeError('需要管理员权限来注册或移除输入法。')
        if Path(request.get('profile', '')).resolve() != Path.home().resolve():
            raise RuntimeError('请使用当前登录账户确认管理员权限，不能使用其他账户安装。')
        if Path(request.get('executable', '')).resolve() != Path(sys.executable).resolve():
            raise RuntimeError('操作入口与安装包不一致，请重新运行安装包。')
        def progress(percent, message):
            atomic_json(output, {'finished': False, 'percent': percent, 'message': message})
        installer = Installer(progress=progress)
        if request.get('action') == 'install':
            result = installer.install(request['executable'])
        elif request.get('action') == 'uninstall':
            result = installer.uninstall(bool(request.get('clear_data', True)))
        else:
            raise RuntimeError('不支持的操作')
        atomic_json(output, {'finished': True, **result})
        return 0
    except Exception as exc:
        atomic_json(output, {'finished': True, 'ok': False, 'error': str(exc)})
        return 1
