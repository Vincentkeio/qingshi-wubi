"""Qt-free routing for installed settings, wizard and silent update checks."""
import ctypes
import os
from pathlib import Path
import subprocess
import winreg


def installed_settings():
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'Software\QingshiWubi', 0,
                        winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        runtime = winreg.QueryValueEx(key, 'RuntimeDir')[0]
    return Path(runtime) / 'settings/QingshiSettings.exe'


def open_installed_settings(wizard=False):
    target = installed_settings()
    if not target.is_file():
        return 1
    arguments = [str(target)] + (['--wizard'] if wizard else [])
    subprocess.Popen(arguments, env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'))
    return 0


def background_update():
    from app_paths import user_directory
    from rime_config import APP_VER
    from update_checker import UpdateChecker
    try:
        result = UpdateChecker(user_directory()).check(APP_VER, manual=False)
    except Exception:
        return 0
    if result.get('newer'):
        answer = ctypes.windll.user32.MessageBoxW(
            None, f"发现 v{result['version']}，是否打开官方发布页？", '青石五笔有更新', 0x24)
        if answer == 6:
            import webbrowser
            webbrowser.open(result['url'])
    return 0
