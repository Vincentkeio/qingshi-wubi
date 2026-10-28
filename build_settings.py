"""Build the installed settings center without one-file extraction or payload.zip."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent / 'work'
GUI = ROOT / 'gui'


def build_settings():
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError('Build with Python 3.11 for the bundled PyQt6 runtime.')
    sys.path[:0] = [str(WORK / 'build-tools'), str(WORK / 'package-deps')]
    import PyInstaller.__main__
    import PyQt6
    arguments = [str(GUI / 'settings_app.py'), '--noconfirm', '--onedir', '--windowed',
                 '--name', 'QingshiSettings', '--paths', str(GUI),
                 '--icon', str(ROOT / 'weasel/resource/weasel.ico'),
                 '--distpath', str(ROOT / 'dist'), '--workpath', str(WORK / 'settings-build'),
                 '--specpath', str(WORK / 'settings-build'),
                 '--exclude-module', 'tkinter', '--exclude-module', 'installer_backend',
                 '--exclude-module', 'installer_ui', '--exclude-module', 'qingshi_app',
                 '--exclude-module', 'PyQt6.QtQml', '--exclude-module', 'PyQt6.QtQuick']
    for asset in [*GUI.glob('*.svg'), GUI / 'qingshi-mark.png']:
        arguments += ['--add-data', str(asset) + os.pathsep + '.']
    qt_bin = Path(PyQt6.__file__).parent / 'Qt6/bin'
    for pattern in ('vcruntime140*.dll', 'msvcp140*.dll', 'concrt140.dll'):
        for binary in qt_bin.glob(pattern):
            arguments += ['--add-binary', str(binary) + os.pathsep + '.']
    original = os.environ.get('PATH', '')
    os.environ['PATH'] = os.pathsep.join(p for p in original.split(os.pathsep) if 'poppler' not in p.lower())
    try:
        PyInstaller.__main__.run(arguments)
    finally:
        os.environ['PATH'] = original
    return ROOT / 'dist/QingshiSettings'


if __name__ == '__main__':
    build_settings()
