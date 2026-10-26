"""Discover installed runtime and user data without hard-coded development paths."""
import os
from pathlib import Path


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
        registry_value('HKEY_LOCAL_MACHINE', r'Software\QingshiWubi', 'RuntimeDir'),
        registry_value('HKEY_LOCAL_MACHINE', r'Software\Rime\Weasel', 'WeaselRoot'),
        r'C:\Program Files\Rime\weasel-0.17.4',
        r'C:\Program Files (x86)\Rime\weasel-0.17.4',
    ]
    return list(dict.fromkeys(str(Path(p)) for p in values if p))
