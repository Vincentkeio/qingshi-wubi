"""Discover installed runtime and user data without hard-coded development paths."""
import json
import os
from pathlib import Path

INSTALL_RECORD = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'QingshiWubi' / '.qingshi-install.json'


def installed_runtime():
    """安装器写的记录里那个 runtime 目录。

    这是唯一不绑版本号的路子：每次安装都会把新目录写进 .qingshi-install.json，
    升级到 1.0.14、1.0.15 都不用改任何脚本。
    """
    try:
        data = json.loads(INSTALL_RECORD.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    runtime = data.get('runtime') if isinstance(data, dict) else None
    if runtime and (Path(runtime) / 'WeaselServer.exe').is_file():
        return str(runtime)
    return None


def registry_value(hive, key, name):
    try:
        import winreg
        root = getattr(winreg, hive)
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(root, key, 0, winreg.KEY_READ | view) as handle:
                    value = winreg.QueryValueEx(handle, name)[0]
                    if value:
                        return value
            except OSError:
                continue
    except ImportError:
        pass
    return None


def user_directory():
    if registry_value('HKEY_LOCAL_MACHINE', r'Software\QingshiWubi', 'RuntimeDir'):
        return os.path.join(os.environ.get('APPDATA', ''), 'QingshiWubi')
    return (registry_value('HKEY_CURRENT_USER', r'Software\Rime\Weasel', 'RimeUserDir')
            or os.path.join(os.environ.get('APPDATA', ''), 'Rime'))


def runtime_directories():
    values = [
        installed_runtime(),   # 安装记录优先：不绑版本号，升级后自动跟随
        registry_value('HKEY_LOCAL_MACHINE', r'Software\QingshiWubi', 'RuntimeDir'),
        registry_value('HKEY_LOCAL_MACHINE', r'Software\Rime\Weasel', 'WeaselRoot'),
        r'C:\Program Files\Rime\weasel-0.17.4',
        r'C:\Program Files (x86)\Rime\weasel-0.17.4',
    ]
    return list(dict.fromkeys(str(Path(p)) for p in values if p))
