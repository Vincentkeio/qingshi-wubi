"""Build the installed settings center (native Win32, no Qt) as a onedir bundle."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent / 'work'
GUI = ROOT / 'gui'


def build_settings():
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError('Build with Python 3.11 for the bundled runtime.')
    sys.path[:0] = [str(WORK / 'build-tools'), str(WORK / 'package-deps')]
    import PyInstaller.__main__
    arguments = [str(GUI / 'settings_native.py'), '--noconfirm', '--onedir', '--windowed',
                 '--name', 'QingshiSettings', '--paths', str(GUI),
                 '--icon', str(ROOT / 'weasel/resource/weasel.ico'),
                 '--distpath', str(ROOT / 'dist'), '--workpath', str(WORK / 'settings-build'),
                 '--specpath', str(WORK / 'settings-build'),
                 '--add-data', str(GUI / 'qingshi-mark.png') + ';.',
                 '--exclude-module', 'tkinter',
                 '--exclude-module', 'numpy',
                 '--exclude-module', 'scipy',
                 '--exclude-module', 'pandas',
                 '--exclude-module', 'matplotlib',
                 '--exclude-module', 'PIL',
                 '--exclude-module', 'PyQt6',
                 '--exclude-module', 'PySide6',
                 '--exclude-module', 'installer_backend',
                 '--exclude-module', 'installer_ui',
                 '--exclude-module', 'qingshi_app',
                 '--exclude-module', 'wubi_settings',
                 '--exclude-module', 'hotkey_page',
                 '--exclude-module', 'ui_theme',
                 '--exclude-module', 'navigation',
                 '--exclude-module', 'backup_page',
                 '--exclude-module', 'setup_wizard',
                 '--exclude-module', 'smoke_test']
    original = os.environ.get('PATH', '')
    os.environ['PATH'] = os.pathsep.join(
        p for p in original.split(os.pathsep) if 'poppler' not in p.lower())
    try:
        PyInstaller.__main__.run(arguments)
    finally:
        os.environ['PATH'] = original
    return ROOT / 'dist/QingshiSettings'


if __name__ == '__main__':
    build_settings()
